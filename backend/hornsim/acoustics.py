"""1D acoustic model of the passive in-ear horn: geometry -> insertion gain at the eardrum.

Sound in a bore this narrow travels as plane waves (first cross-mode of a 5 mm duct is near 40 kHz), so
every air path is a chain of short tubes. Each tube is a 2x2 transmission matrix relating (pressure,
volume flow) at its two ends, input side toward the sound:

    [p_in]   [A B] [p_out]
    [U_in] = [C D] [U_out]

One engine, two front doors
  Profile door   Design (any bore area profile, vents, dampers, concha_fill) + Canal (residual volume)
                 -> open_ear, aided, insertion_gain_db, pressure_along_bore, evaluate.
  Dial door      a design dict of named dials shared with the earpiece builder (throat_mm2, mouth_mm2,
                 flare_mid1/2, length_mm, canal_stem_mm, vent_*, damper_*) + the patient's ear_params
                 -> insertion_gain, open_ear_gain. Values may be arrays; design, canal and frequency
                 broadcast together with frequency on the LAST axis.
  Design.from_dials turns a dial design into a profile design, so either door can run any dial design.

Pieces, and what Settings can change about each
  bore / vent / canal   lossy circular tubes. Wall losses: exact circular-tube solution (Zwikker & Kosten
                        1949; Keefe 1984, JASA 75:58), read from a table of the exact function.
  flare                 short slices, as many as a convergence rule asks for. The profile door steps the
                        area profile in uniform tubes, as both earlier models did. The dial door's flare is
                        piecewise conical, so it uses conical slices (the spherical-wave solution of a cone,
                        with the wall losses of the slice's mean radius): same answer as ever finer stepped
                        tubes, with about 8 times fewer slices.
  mouth, vent inlet     radiation impedance of a piston in an infinite baffle, exact (Rayleigh; Kinsler et
                        al. 4th ed. eq. 7.5.11). The low-ka form is kept as an option.
  eardrum               series resistance-mass-compliance. SIMPLIFIED: values in the published adult range,
                        chosen so the compliance matches the IEC 60318-4 ear simulator's volume. A pure
                        resistance or any measured impedance function can be swapped in.
  concha / open ear     "bump": the open ear gets the concha's resonance boost (one bump approximating
                        Shaw's 1974 average concha component) and a shell removes it in proportion to
                        concha_fill. "tube": the open ear is the patient's own concha (a wide tube sized from
                        ear_params) radiating from its opening. "auto" uses "tube" when ear_params carries
                        the concha geometry and "bump" otherwise.
  vents                 any number of identical vents in parallel with the bore at the tip.
  dampers               series acoustic resistances anywhere along the bore, in cgs acoustic ohms as
                        hearing-aid dampers are rated.

Settings and presets
  Every response function takes `settings=`; passing nothing means UNIFIED.
    UNIFIED           resistance-mass-compliance eardrum, exact wall losses, exact piston radiation, air
                      at 35 C, slices counted by a convergence rule.
    LEGACY_MAIN       reproduces this module as it was on main before unification (low-ka radiation,
                      0.25 mm cylinder steps).
    LEGACY_MARC_SIM   reproduces the marc-sim branch's acoustics.py (20 C air, eardrum = 3 rho c / S,
                      Keefe's large-radius loss expansion, 40 cylinder steps, 6 mm tip convention).

Insertion gain = eardrum pressure with the aid / eardrum pressure with the ear open, both for the same
free-field sound. Head and torso effects are common to both and cancel, so the direction of the sound
does not change insertion gain; it only enters open_ear_gain.

    python -m hornsim.acoustics <patient_dir>      # needs <patient_dir>/aid/design.json
"""
import dataclasses
import functools
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple, Union

import numpy as np
from scipy.special import j1, jve, struve

# Air at about 35 C (ear canal / worn device): the unified default. Air.at(35.0) agrees to the digits shown.
C0 = 351.9          # speed of sound, m/s
RHO = 1.146         # density, kg/m^3
MU = 1.88e-5        # dynamic viscosity, Pa s
PR = 0.71           # Prandtl number
GAMMA = 1.40        # ratio of specific heats
C = C0              # the dial door's name for the speed of sound (marc-sim had 343.0, air at 20 C)

# Eardrum (see module docstring: simplified)
EARDRUM_R = 3.5e7       # Pa s/m^3   (~350 cgs acoustic ohms)
EARDRUM_VEQ_CC = 0.75   # equivalent volume of the middle-ear compliance, cm^3
EARDRUM_M = 4.0e2       # kg/m^4
DRUM_Z = 3.0            # the "resistance" eardrum, in units of rho c / canal area (marc-sim's calibration knob)

# Concha resonance (see module docstring: simplified)
CONCHA_PEAK_DB, CONCHA_F0, CONCHA_WIDTH_OCT = 9.0, 4800.0, 0.5

HEAD_RADIUS_M = 0.0875                   # Brown & Duda 1998 (IEEE TSAP 6(5)) average head
BD_ALPHA_MIN, BD_THETA_MIN = 0.1, 150.0  # Brown & Duda 1998, head-shadow model constants
# Dial door: a canal sample is the residual beyond a 6 mm tip, so the whole canal is sample + 6 mm and a
# deeper stem shortens the residual, never the patient's canal. Settings.canal_sample_tip_mm overrides it.
CANAL_SAMPLE_TIP_MM = 6.0
# None = the number of flare segments follows the convergence rule (Settings.slice_tol_db). Set an integer
# to force that many in the dial door; marc-sim's convergence test does.
BORE_SEGMENTS = None
LEGACY_BORE_SEGMENTS = 40                # what bore_radii() returns when nothing else says how many
OHM_CGS = 1e5                            # 1 cgs acoustic ohm (dyn s / cm^5) = 1e5 Pa s / m^3

DEFAULT_FREQS = np.geomspace(100.0, 8000.0, 160)

_R_DRY_AIR = 287.05                      # J/(kg K)
_SLICE_F_REF = 8000.0                    # slices are sized for at least this frequency, so a call for a
                                         # few low frequencies returns the same numbers as a full sweep
# Worst error of cutting a flare into n slices, in dB, with V the total change of ln(radius) along the flare
# and k L its phase length at the top frequency:
#     conical slices   _K_CONES V^2 (1 + k L) / n^2
#     stepped tubes    _K_STEPS V ((k L)^2 + 6 V) / n^2
# Upper envelopes over random designs (0.5-40 mm2 throats, up to 100x flare, 3-90 mm, with vents); the
# typical design is 10 to 50 times better. tests/test_acoustics_unified.py checks both against fine slicing.
_K_CONES, _K_STEPS = 3.0, 10.0
_SLICE_LADDER = np.unique(np.r_[1, 2, 3, 2 ** np.arange(2, 14), 3 * 2 ** np.arange(1, 13)])


# ---------------------------------------------------------------- settings

@dataclass(frozen=True)
class Air:
    """Properties of the air in the device. Air.at(temp_c) derives them from a temperature."""
    c: float = C0          # speed of sound, m/s
    rho: float = RHO       # density, kg/m^3
    mu: float = MU         # dynamic viscosity, Pa s
    pr: float = PR         # Prandtl number
    gamma: float = GAMMA   # ratio of specific heats

    @staticmethod
    def at(temp_c, pressure_pa=101325.0):
        """Dry air at `temp_c`: ideal gas for c and rho, Sutherland's law for the viscosity."""
        t = temp_c + 273.15
        if not t > 0:
            raise ValueError(f"temperature {temp_c} C is below absolute zero")
        return Air(c=float(np.sqrt(GAMMA * _R_DRY_AIR * t)), rho=pressure_pa / (_R_DRY_AIR * t),
                   mu=1.716e-5 * (t / 273.15) ** 1.5 * (273.15 + 110.4) / (t + 110.4))


@dataclass(frozen=True)
class Settings:
    """Every modelling assumption that used to be baked in. Defaults are the unified model.

    eardrum            "rcm" (resistance + compliance + mass, the eardrum_* numbers below), "resistance"
                       (eardrum_rho_c x rho c / canal area), or a function freqs_hz -> impedance in Pa s/m^3.
    concha             "auto", "bump", "tube" or "none" (see the module docstring). "tube" needs ear_params
                       with concha_depth_mm, bowl_volume_cc and opening_area_mm2.
    radiation          "piston" (exact flanged piston) or "low_ka" (its small-opening approximation).
    wall_losses        "exact", "none", or "keefe" (the large-radius expansion marc-sim used: off by a
                       third for a 0.3 mm vent at 100 Hz; kept for regression only).
    air                Air(...); Air.at(20.0) for room temperature. with_temperature() is a shortcut.
    canal_diameter_mm  None = use Canal.diameter_mm / ear_params["canal_diameter_mm"]; a number overrides both.
    canal_sample_tip_mm
                       How canal samples are read. None = each door's own convention: in the profile door a
                       Canal is the air beyond THIS design's tip (whole canal = residual + tip_length_mm); in
                       the dial door the whole canal is sample + CANAL_SAMPLE_TIP_MM. A number = the whole
                       canal is sample + that number in both doors, and a deeper tip shortens the residual.
    flare_slices       How the dial door cuts its flare: "cones" (exact for its piecewise-linear radius) or
                       "cylinders" (stepped tubes). The profile door always steps its area profile in tubes.
    slice_tol_db       How far the sliced flare may be from the converged answer: the number of slices is the
                       smallest the convergence rule allows for this worst-case error.
    slice_count        Force this many slices (dial door: flare segments) instead of the rule.
    slice_step_mm      Force a fixed slice length instead of the rule (at least 8 slices).
    """
    air: Air = Air()
    eardrum: Union[str, Callable] = "rcm"
    eardrum_r: float = EARDRUM_R
    eardrum_veq_cc: float = EARDRUM_VEQ_CC
    eardrum_m: float = EARDRUM_M
    eardrum_rho_c: float = DRUM_Z
    concha: str = "auto"
    concha_peak_db: float = CONCHA_PEAK_DB
    concha_f0: float = CONCHA_F0
    concha_width_oct: float = CONCHA_WIDTH_OCT
    radiation: str = "piston"
    wall_losses: str = "exact"
    canal_diameter_mm: Optional[float] = None
    canal_sample_tip_mm: Optional[float] = None
    flare_slices: str = "cones"
    slice_tol_db: float = 0.05
    slice_count: Optional[int] = None
    slice_step_mm: Optional[float] = None

    def __post_init__(self):
        def choice(name, allowed):
            if getattr(self, name) not in allowed:
                raise ValueError(f"Settings.{name} must be one of {allowed}, got {getattr(self, name)!r}")
        if not callable(self.eardrum):
            choice("eardrum", ("rcm", "resistance"))
        choice("concha", ("auto", "bump", "tube", "none"))
        choice("radiation", ("piston", "low_ka"))
        choice("wall_losses", ("exact", "keefe", "none"))
        choice("flare_slices", ("cones", "cylinders"))
        for name in ("eardrum_r", "eardrum_veq_cc", "eardrum_rho_c", "concha_width_oct", "concha_f0", "slice_tol_db"):
            if not getattr(self, name) > 0:
                raise ValueError(f"Settings.{name} must be positive, got {getattr(self, name)!r}")
        if not self.eardrum_m >= 0:
            raise ValueError(f"Settings.eardrum_m must not be negative, got {self.eardrum_m!r}")
        for name in ("canal_diameter_mm", "slice_step_mm"):
            if getattr(self, name) is not None and not getattr(self, name) > 0:
                raise ValueError(f"Settings.{name} must be positive or None, got {getattr(self, name)!r}")
        if self.canal_sample_tip_mm is not None and not self.canal_sample_tip_mm >= 0:
            raise ValueError(f"Settings.canal_sample_tip_mm must not be negative, got {self.canal_sample_tip_mm!r}")
        if self.slice_count is not None and not (int(self.slice_count) == self.slice_count and self.slice_count >= 1):
            raise ValueError(f"Settings.slice_count must be a positive integer or None, got {self.slice_count!r}")

    def replace(self, **changes):
        """A copy with some fields changed."""
        return dataclasses.replace(self, **changes)

    def with_temperature(self, temp_c):
        """A copy with the air properties derived from `temp_c`."""
        return self.replace(air=Air.at(temp_c))


UNIFIED = Settings()
LEGACY_MAIN = Settings(radiation="low_ka", concha="bump", flare_slices="cylinders", slice_step_mm=0.25)
LEGACY_MARC_SIM = Settings(air=Air(c=343.0, rho=1.204, mu=1.81e-5), eardrum="resistance", eardrum_rho_c=3.0,
                           concha="tube", wall_losses="keefe", flare_slices="cylinders", slice_count=40,
                           canal_sample_tip_mm=6.0)
PRESETS = {"unified": UNIFIED, "legacy_main": LEGACY_MAIN, "legacy_marc_sim": LEGACY_MARC_SIM}


def _settings(settings):
    if settings is None:
        return UNIFIED
    if isinstance(settings, str):
        if settings not in PRESETS:
            raise ValueError(f"unknown settings preset {settings!r}; choose from {sorted(PRESETS)}")
        return PRESETS[settings]
    if not isinstance(settings, Settings):
        raise TypeError(f"settings must be a Settings, a preset name or None, got {type(settings).__name__}")
    return settings


def _loss(st, lossy):
    """The wall-loss model for one call: `lossy` (the profile door's old switch) overrides the settings."""
    if lossy is None:
        return st.wall_losses
    if not lossy:
        return "none"
    return "exact" if st.wall_losses == "none" else st.wall_losses


def _require(ok, message):
    """Raise ValueError unless every element of `ok` is true (NaN comparisons are false, so NaN is rejected)."""
    if not np.all(ok):
        raise ValueError(message)


def _span(values):
    v = np.asarray(values, float)
    return f"{v.min():g}" if v.size == 1 or v.min() == v.max() else f"{v.min():g} to {v.max():g}"


def _omega(freqs):
    f = np.asarray(freqs, float)
    _require(f > 0, f"frequencies must be positive, got {_span(f) if f.size else 'none'}")
    return 2 * np.pi * f


# ---------------------------------------------------------------- designs and canals (profile door)

@dataclass
class Design:
    """Acoustic description of one aid. Lengths in mm, areas in mm^2."""
    s_mm: np.ndarray                 # positions along the bore, mouth (0) -> throat outlet
    area_mm2: np.ndarray             # bore area at each position
    vent_diameter_mm: float = 0.0    # 0 = no vent
    vent_length_mm: float = 0.0      # 0 = no vent
    concha_fill: float = 1.0         # 0 = concha left open, 1 = shell fills it ("bump" concha model only)
    tip_length_mm: float = 9.0       # how far the tip reaches into the canal
    vent_count: int = 1              # identical vents in parallel; 0 = no vent
    dampers: Sequence[Tuple[float, float]] = ()   # (position s in mm, resistance in cgs acoustic ohms)

    @staticmethod
    def from_design_json(d):
        a = d["acoustic"]
        return Design(np.asarray(a["s_mm"], float), np.asarray(a["area_mm2"], float),
                      a.get("vent_diameter_mm", 0.0), a.get("vent_length_mm", 0.0),
                      a.get("concha_fill", 1.0), a.get("tip_length_mm", 9.0),
                      a.get("vent_count", 1), tuple(tuple(p) for p in a.get("dampers", ())))

    @staticmethod
    def from_dials(x, concha_fill=1.0, points=601):
        """The profile-door Design of one dial design (scalars): mouth -> flare -> canal stem.

        The flare is sampled at `points` positions; tip_length_mm is the stem, so the profile door's open
        ear uses the same whole canal the dial door would.
        """
        _check_dials(x)
        g = lambda k, default=None: float(np.asarray(x[k] if default is None else x.get(k, default), float))
        length, stem, throat = g("length_mm"), g("canal_stem_mm"), g("throat_mm2")
        s = np.linspace(0.0, length, points)
        r = _flare_radius(np.sqrt(throat / np.pi), np.sqrt(g("mouth_mm2") / np.pi), g("flare_mid1"), g("flare_mid2"),
                          1 - s / length if length > 0 else np.ones(points))
        area = np.pi * r ** 2
        if stem > 0:
            s, area = np.r_[s, length + stem], np.r_[area, throat]
        dampers = [(length * (1 - float(np.asarray(p, float))), float(np.asarray(ohm, float))) for p, ohm in _dial_dampers(x)]
        return Design(s, area, g("vent_diameter_mm", 0.0), g("vent_length_mm", 0.0), concha_fill, stem,
                      int(round(g("vent_count", 0))), tuple(dampers))


@dataclass
class Canal:
    """One sampled ear canal. `volume_cc` is the air left between the tip and the eardrum."""
    volume_cc: float
    diameter_mm: float = 7.5

    @staticmethod
    def from_length(length_mm, diameter_mm=7.5):
        """A canal sample given as a residual length (the dial door's way) instead of a volume."""
        return Canal(length_mm * np.pi * diameter_mm ** 2 / 4 / 1000.0, diameter_mm)

    @property
    def area_m2(self):
        return np.pi * (self.diameter_mm / 2000.0) ** 2

    @property
    def residual_length_m(self):
        return self.volume_cc * 1e-6 / self.area_m2


def _check_design(design):
    s, area = np.asarray(design.s_mm, float), np.asarray(design.area_mm2, float)
    _require(s.ndim == 1 and s.shape == area.shape and s.size >= 2,
             f"Design.s_mm and Design.area_mm2 must be 1D arrays of the same length (>= 2), got shapes {s.shape} and {area.shape}")
    _require(np.diff(s) >= 0, "Design.s_mm must not decrease from the mouth to the throat outlet (a negative length)")
    _require(area > 0, f"Design.area_mm2 must be positive everywhere, got {_span(area)} mm^2")
    _require(design.vent_diameter_mm >= 0, f"Design.vent_diameter_mm must not be negative, got {design.vent_diameter_mm}")
    _require(design.vent_length_mm >= 0, f"Design.vent_length_mm must not be negative, got {design.vent_length_mm}")
    _require(design.vent_count >= 0, f"Design.vent_count must not be negative, got {design.vent_count}")
    _require(design.tip_length_mm >= 0, f"Design.tip_length_mm must not be negative, got {design.tip_length_mm}")
    _require(0 <= design.concha_fill <= 1, f"Design.concha_fill must be between 0 and 1, got {design.concha_fill}")
    for pos, ohm in design.dampers:
        _require(s[0] <= pos <= s[-1], f"damper at s = {pos} mm is outside the bore ({s[0]:g} to {s[-1]:g} mm)")
        _require(ohm >= 0, f"damper resistance must not be negative, got {ohm} cgs ohms")


def _canal_arrays(canals, tip_length_mm, st):
    """Canal area (m^2), whole length and residual length behind the tip (m), each [n_canals, 1]."""
    for c in canals:
        _require(c.volume_cc >= 0, f"Canal.volume_cc must not be negative, got {c.volume_cc}")
        _require(c.diameter_mm > 0, f"Canal.diameter_mm must be positive, got {c.diameter_mm}")
    diameter = np.array([st.canal_diameter_mm or c.diameter_mm for c in canals], float)[:, None]
    area = np.pi * (diameter / 2000.0) ** 2
    sample = np.array([c.volume_cc for c in canals], float)[:, None] * 1e-6 / area
    if st.canal_sample_tip_mm is None:
        return area, sample + tip_length_mm * 1e-3, sample
    whole = sample + st.canal_sample_tip_mm * 1e-3
    _require(whole >= tip_length_mm * 1e-3,
             f"the tip ({tip_length_mm:g} mm) is longer than the canal ({_span(whole * 1e3)} mm)")
    return area, whole, whole - tip_length_mm * 1e-3


# ---------------------------------------------------------------- tubes

_TABLE_N = 32768
_TABLE_LOG_LO, _TABLE_LOG_HI = np.log(1e-2), np.log(1e4)
_TABLE_SCALE = (_TABLE_N - 1) / (_TABLE_LOG_HI - _TABLE_LOG_LO)


def _wall_function(s):
    """1 - 2 J1(z) / (z J0(z)) at z = s sqrt(-j): how much of a tube's cross-section moves freely when the
    boundary layer is 1/s of the radius (Zwikker & Kosten). s = r sqrt(w rho / mu)."""
    z = np.sqrt(-1j) * np.asarray(s, float)
    return 1 - 2 * jve(1, z) / (z * jve(0, z))


def _exact_factors(s, pr, gamma):
    """Propagation constant / (j w / c) and characteristic impedance / (rho c / S) of the exact solution."""
    viscous = _wall_function(s)
    root = np.sqrt((gamma - (gamma - 1) * _wall_function(s * np.sqrt(pr))) / viscous)
    return root, 1 / (viscous * root)


@functools.lru_cache(maxsize=8)
def _exact_table(pr, gamma):
    """The two exact factors on a log grid of s, with their forward differences, for linear lookup.
    32768 points over s = 0.01 to 10000 keep the lookup within 1e-7 of the exact function."""
    g, z = _exact_factors(np.exp(np.linspace(_TABLE_LOG_LO, _TABLE_LOG_HI, _TABLE_N)), pr, gamma)
    return g, np.diff(g, append=g[-1:]), z, np.diff(z, append=z[-1:])


def _tube_constants(r_m, w, st, loss):
    """Propagation constant (1/m) and characteristic impedance (Pa s/m^3); r_m broadcasts against w."""
    air = st.air
    z0 = air.rho * air.c / (np.pi * r_m ** 2)
    if loss == "none":
        return 1j * w / air.c + 0 * r_m, z0 + 0j * w
    if loss == "keefe":
        rv = r_m * np.sqrt(w * air.rho / air.mu)
        return ((w / air.c) * (1.045 / rv + 1.080 / rv ** 2 + 0.750 / rv ** 3 + 1j * (1 + 1.045 / rv)),
                z0 * (1 + 0.369 / rv - 1j * (0.369 / rv + 1.149 / rv ** 2 + 0.303 / rv ** 3)))
    g_tab, dg_tab, z_tab, dz_tab = _exact_table(air.pr, air.gamma)
    t = (np.log(r_m) + 0.5 * np.log(w * air.rho / air.mu) - _TABLE_LOG_LO) * _TABLE_SCALE
    inside = (t >= 0) & (t < _TABLE_N - 1)
    if inside.all():
        i = t.astype(np.intp)
        frac = t - i
        g, z = g_tab[i] + frac * dg_tab[i], z_tab[i] + frac * dz_tab[i]
    else:                                    # beyond the table (hair-thin or metre-wide tubes): evaluate directly
        g, z = _exact_factors(r_m * np.sqrt(w * air.rho / air.mu), air.pr, air.gamma)
    return (1j * w / air.c) * g, z0 * z


def _tube(r_m, length_m, w, st, loss):
    """Transmission matrix (a, b, c, d) of one uniform tube; r_m and length_m broadcast against w."""
    g, zc = _tube_constants(r_m, w, st, loss)
    e = np.exp(g * length_m)
    ei = 1 / e
    ch, sh = 0.5 * (e + ei), 0.5 * (e - ei)
    return ch, zc * sh, sh / zc, ch


def _cone(r_in, r_out, length_m, w, st, loss):
    """Transmission matrix (a, b, c, d) of one conical slice, radius r_in at the sound side to r_out.

    The spherical-wave solution of a cone (Benade 1988, JASA 83:1764), with the propagation constant and
    impedance of a lossy tube at the slice's geometric-mean radius. It is the uniform tube when r_in = r_out,
    and a chain of these converges to the same answer as ever finer stepped tubes.
    """
    r_mean = np.sqrt(r_in * r_out)
    g, zc = _tube_constants(r_mean, w, st, loss)
    gl = g * length_m
    e = np.exp(gl)
    ei = 1 / e
    ch, sh = 0.5 * (e + ei), 0.5 * (e - ei)
    empty = gl == 0                          # a slice of no length passes everything through unchanged
    safe = np.where(empty, 1.0, gl)
    shc = np.where(empty, 1.0, sh / safe)    # sinh(x) / x
    step = r_out - r_in
    return ((r_out / r_in) * ch - (step / r_in) * shc, zc * sh,
            (sh + (step ** 2 / (r_in * r_out)) * np.where(empty, 0.0, (ch - shc) / safe)) / zc,
            (r_in / r_out) * ch + (step / r_out) * shc)


def _slice(r_in, r_out, length_m, w, st, loss):
    """One slice of a bore: a uniform tube when r_out is r_in (the same object), a cone otherwise."""
    return _tube(r_in, length_m, w, st, loss) if r_out is r_in else _cone(r_in, r_out, length_m, w, st, loss)


def _mul(m, n):
    return (m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3])


def _chain(r_in, r_out, lengths_m, w, st, loss, dampers=None):
    """Transmission matrix of n slices, sound side first. Slice i runs from radius r_in[..., i] to
    r_out[..., i] over lengths_m[..., i]; pass the same array twice for stepped tubes.

    dampers = (boundary[..., D], resistance[..., D]): a series resistance (Pa s/m^3) at slice boundary
    `boundary` (0 = in front of the first slice, n = behind the last).
    """
    n = r_in.shape[-1]
    lengths_m = np.broadcast_to(lengths_m, np.broadcast_shapes(np.shape(lengths_m), r_in.shape))
    cylinders = r_out is r_in
    m = (1.0, 0.0, 0.0, 1.0)
    for i in range(n + 1):
        if dampers is not None:
            here = dampers[0] == i
            if here.any():
                res = np.where(here, dampers[1], 0.0).sum(-1)[..., None]
                m = (m[0], m[0] * res + m[1], m[2], m[2] * res + m[3])
        if i < n:
            a = r_in[..., i, None]
            m = _mul(m, _slice(a, a if cylinders else r_out[..., i, None], lengths_m[..., i, None], w, st, loss))
    return m


def _slices_needed(length_m, variation, f_max, st, cones):
    """Slices a flare needs for Settings.slice_tol_db (float, unrounded; arrays broadcast).

    `variation` is the total change of ln(radius) along the flare. A uniform tube needs one slice.
    """
    kl = 2 * np.pi * max(float(f_max), _SLICE_F_REF) / st.air.c * np.asarray(length_m, float)
    v = np.asarray(variation, float)
    if cones:
        return v * np.sqrt(_K_CONES * (1 + kl) / st.slice_tol_db)
    return np.sqrt(_K_STEPS * v * (kl ** 2 + 6 * v) / st.slice_tol_db)


def _ladder(n, multiple=1):
    """Round slice counts up to `multiple` x (1, 2, 3, 4, 6, 8, 12, 16, ...), so a batch splits into few
    groups. A count of zero (a uniform tube) becomes one slice."""
    n = np.asarray(n, float)
    _require(n <= multiple * _SLICE_LADDER[-1], f"the bore needs more than {multiple * _SLICE_LADDER[-1]} slices; raise Settings.slice_tol_db")
    return np.where(n > 0, multiple * _SLICE_LADDER[np.searchsorted(_SLICE_LADDER, np.maximum(n / multiple, 1) - 1e-9)], 1)


def _warped_edges(n, positions):
    """Slice edges as fractions [..., n + 1] from 0 to 1, moved so every damper sits exactly on an edge.

    positions[..., D] are fractions along the bore. Returns (edges, boundary[..., D], order[..., D]) with
    the dampers sorted along the bore; `order` sorts the resistances the same way. Needs n >= 2 (D + 1).
    """
    positions = np.asarray(positions, float)
    order = np.argsort(positions, -1)
    p = np.take_along_axis(positions, order, -1)
    count = p.shape[-1]
    k = np.rint(p * n)
    for j in range(count):                   # a damper inside the bore keeps a slice on each side of it
        low = np.where(p[..., j] > 0, 1.0, 0.0)
        if j:
            low = np.maximum(low, k[..., j - 1] + (p[..., j] > p[..., j - 1]))
        k[..., j] = np.maximum(k[..., j], low)
    for j in range(count - 1, -1, -1):
        high = np.where(p[..., j] < 1, n - 1.0, float(n))
        if j < count - 1:
            high = np.minimum(high, k[..., j + 1] - (p[..., j + 1] > p[..., j]))
        k[..., j] = np.minimum(k[..., j], high)
    zero, one = np.zeros(p.shape[:-1] + (1,)), np.ones(p.shape[:-1] + (1,))
    knots_k, knots_p = np.concatenate([zero, k, n * one], -1), np.concatenate([zero, p, one], -1)
    index = np.arange(n + 1.0)
    edges = np.zeros(p.shape[:-1] + (n + 1,))
    for j in range(count + 1):
        ka, kb, pa, pb = (a[..., j + d, None] for a in (knots_k, knots_p) for d in (0, 1))
        edges = np.where((index >= ka) & (index <= kb), pa + (index - ka) * (pb - pa) / np.maximum(kb - ka, 1), edges)
    return edges, k, order


def tube_constants(radius_m, freqs, lossy=None, settings=None):
    """Propagation constant (1/m) and characteristic impedance (Pa s/m^3) of a circular tube.

    radius_m: scalar or array [N]; freqs: [F]. Returns arrays [N, F] (or [F] for a scalar radius).
    """
    st = _settings(settings)
    radius = np.asarray(radius_m, float)
    _require(radius > 0, f"tube radius must be positive, got {_span(radius)} m")
    g, zc = _tube_constants(np.atleast_1d(radius)[:, None], _omega(freqs)[None, :], st, _loss(st, lossy))
    return (g[0], zc[0]) if radius.ndim == 0 else (g, zc)


def _stack(m, shape):
    """(a, b, c, d) -> array shape + (2, 2)."""
    out = np.empty(shape + (2, 2), complex)
    out[..., 0, 0], out[..., 0, 1], out[..., 1, 0], out[..., 1, 1] = m
    return out


def tube_abcd(radius_m, length_m, freqs, lossy=None, settings=None):
    """Transmission matrix [F, 2, 2] of one uniform tube."""
    st = _settings(settings)
    _require(radius_m > 0, f"tube radius must be positive, got {radius_m} m")
    _require(length_m >= 0, f"tube length must not be negative, got {length_m} m")
    w = _omega(freqs)
    return _stack(_tube(float(radius_m), float(length_m), w, st, _loss(st, lossy)), w.shape)


def bore_slices(s_mm, area_mm2, freqs, lossy=None, ds_mm=0.25, settings=None):
    """Per-slice matrices [N, F, 2, 2] for a bore with varying area, and the slice edges [N + 1] in mm.

    Stepped short tubes every ds_mm, as before. ds_mm=None counts the slices the way `settings` says
    instead (by default the convergence rule)."""
    st = _settings(settings)
    w = _omega(freqs)
    if ds_mm is not None:
        st = st.replace(slice_count=None, slice_step_mm=ds_mm)
    edges, radii, _ = _profile_slices(Design(np.asarray(s_mm, float), np.asarray(area_mm2, float)), w.max() / (2 * np.pi), st)
    m = _tube(radii[:, None], np.diff(edges)[:, None] * 1e-3, w[None, :], st, _loss(st, lossy))
    return _stack(m, (len(radii), len(w))), edges


def chain(mats):
    """Product of per-slice matrices [N, F, 2, 2] in order -> [F, 2, 2]."""
    out = mats[0]
    for m in mats[1:]:
        out = out @ m
    return out


def _profile_slices(design, f_max, st):
    """Step a profile design in uniform tubes: edges [N + 1] (mm), tube radii [N] (m) and the dampers as
    (boundary [D], resistance [D] in Pa s/m^3) or None."""
    _check_design(design)
    s, area = np.asarray(design.s_mm, float), np.asarray(design.area_mm2, float)
    length = s[-1] - s[0]
    if st.slice_count is not None:
        n = int(st.slice_count)
    elif st.slice_step_mm is not None:
        n = max(8, int(np.ceil(length / st.slice_step_mm)))
    else:
        steps = np.abs(np.diff(np.log(area))) / 2            # change of ln(radius) between samples
        flared = float(np.sum(np.diff(s)[steps > 1e-12]))     # the part of the bore whose area changes
        n = 1 if flared == 0 else int(np.ceil(float(_slices_needed(flared * 1e-3, steps.sum(), f_max, st, cones=False)) * length / flared))
        n = max(n, 1)
    dampers = None
    if len(design.dampers) and length > 0:
        n = max(n, 2 * (len(design.dampers) + 1))
        pos, ohm = np.array(design.dampers, float).T
        fractions, boundary, order = _warped_edges(n, (pos - s[0]) / length)
        dampers = (boundary, ohm[order] * OHM_CGS)
    else:
        fractions = np.linspace(0.0, 1.0, n + 1)
        if len(design.dampers):                              # a bore of no length: everything sits at its one point
            dampers = (np.zeros(len(design.dampers)), np.array(design.dampers, float)[:, 1] * OHM_CGS)
    edges = s[0] + length * fractions
    mid = 0.5 * (edges[:-1] + edges[1:])
    return edges, np.sqrt(np.interp(mid, s, area) * 1e-6 / np.pi), dampers


# ---------------------------------------------------------------- terminations and sources

def _radiation(area_m2, w, st):
    """Radiation impedance (Pa s/m^3) of an opening of this area in a baffle."""
    air = st.air
    ka = (w / air.c) * np.sqrt(area_m2 / np.pi)
    z0 = air.rho * air.c / area_m2
    if st.radiation == "low_ka":
        return z0 * (ka ** 2 / 2 + 1j * 8 * ka / (3 * np.pi))
    x = 2 * ka
    small = x < 1e-2                         # the closed forms lose digits here; their series do not
    xs = np.where(small, 1.0, x)
    resistance = np.where(small, x ** 2 / 8 - x ** 4 / 192, 1 - 2 * j1(xs) / xs)
    reactance = np.where(small, (4 / np.pi) * (x / 3 - x ** 3 / 45), 2 * struve(1, xs) / xs)
    return z0 * (resistance + 1j * reactance)


def radiation_impedance(radius_m, freqs, settings=None):
    """Radiation impedance (Pa s/m^3) of a flanged circular opening: exact piston, or the low-ka form."""
    _require(np.asarray(radius_m) > 0, f"opening radius must be positive, got {radius_m} m")
    return _radiation(np.pi * np.asarray(radius_m, float) ** 2, _omega(freqs), _settings(settings))


def _drum(w, canal_area_m2, st):
    """Eardrum impedance (Pa s/m^3)."""
    air = st.air
    if callable(st.eardrum):
        return np.asarray(st.eardrum(w / (2 * np.pi)), complex)
    if st.eardrum == "resistance":
        return st.eardrum_rho_c * air.rho * air.c / canal_area_m2 + 0j * w
    compliance = st.eardrum_veq_cc * 1e-6 / (air.rho * air.c ** 2)
    return st.eardrum_r + 1j * w * st.eardrum_m + 1 / (1j * w * compliance)


def eardrum_impedance(freqs, settings=None, canal_area_m2=None):
    """Eardrum impedance (Pa s/m^3). The "resistance" eardrum scales with the canal area (default: 7.5 mm)."""
    st = _settings(settings)
    if canal_area_m2 is None:
        canal_area_m2 = np.pi * ((st.canal_diameter_mm or 7.5) / 2000.0) ** 2
    return _drum(_omega(freqs), canal_area_m2, st)


def _concha_bump_db(w, st):
    octaves = np.log2(w / (2 * np.pi) / st.concha_f0)
    return st.concha_peak_db * np.exp(-0.5 * (octaves / st.concha_width_oct) ** 2)


def concha_gain_db(freqs, settings=None):
    """Pressure boost of the open concha at the canal entrance: one bump on a log-frequency axis."""
    return _concha_bump_db(_omega(freqs), _settings(settings))


_CONCHA_KEYS = ("concha_depth_mm", "bowl_volume_cc", "opening_area_mm2")


def _concha_model(st, ear_params):
    """Which concha model this call uses: "bump", "tube" or "none"."""
    has_geometry = ear_params is not None and all(k in ear_params for k in _CONCHA_KEYS)
    if st.concha == "auto":
        return "tube" if has_geometry else "bump"
    if st.concha == "tube":
        _require(has_geometry, f'Settings.concha = "tube" needs ear_params with {", ".join(_CONCHA_KEYS)}')
        for k in _CONCHA_KEYS:
            _require(ear_params[k] > 0, f"ear_params[{k!r}] must be positive, got {ear_params[k]}")
    return st.concha


def _thevenin(m, z_src):
    """Open-circuit pressure (per unit source pressure) and source impedance at a two-port's output."""
    a, b, c, d = m
    den = a + c * z_src
    return 1 / den, (b + d * z_src) / den


def _to_drum(p_src, z_src, canal_m, area_m2, w, st, loss):
    """Pressure at the eardrum for a source (open-circuit pressure, impedance) feeding `canal_m` of canal."""
    g, zc = _tube_constants(np.sqrt(area_m2 / np.pi), w, st, loss)
    z_drum = _drum(w, area_m2, st)
    e = np.exp(g * canal_m)
    alpha, beta = 1 + z_src / z_drum, zc / z_drum + z_src / zc
    return 2 * p_src / (e * (alpha + beta) + (alpha - beta) / e)


def _open_ear(whole_m, area_m2, w, st, loss, ear_params):
    """Open-ear eardrum pressure over the pressure with the canal blocked (no head)."""
    model = _concha_model(st, ear_params)
    if model == "tube":
        # the tube keeps the bowl's air volume (a uniform tube at the opening area would hold ~50% more on
        # the validation ear); the opening area sets only the radiation load
        depth = ear_params["concha_depth_mm"] * 1e-3
        concha = _tube(np.sqrt(ear_params["bowl_volume_cc"] * 1e-6 / depth / np.pi), depth, w, st, loss)
        p_oc, z = _thevenin(concha, _radiation(ear_params["opening_area_mm2"] * 1e-6, w, st))
        return _to_drum(p_oc, z, whole_m, area_m2, w, st, loss)
    src = 10 ** (_concha_bump_db(w, st) / 20) if model == "bump" else 1.0
    return _to_drum(src, _radiation(area_m2, w, st), whole_m, area_m2, w, st, loss)


def _aided_source(concha_fill, w, st, ear_params):
    """Pressure at the device's openings over the blocked pressure: what is left of the concha's boost."""
    model = _concha_model(st, ear_params)
    if model == "bump":
        return 10 ** ((1 - concha_fill) * _concha_bump_db(w, st) / 20)
    _require(model == "none" or np.asarray(concha_fill) == 1,
             'a concha left open (concha_fill < 1) needs Settings(concha="bump"): the geometry-based concha '
             "model has no aided path through an open concha")
    return 1.0


def _vent(count, radius_m, length_m, w, st, loss):
    """Admittance and short-circuit flow (per unit source pressure) of `count` identical vents in parallel.
    A count, a radius or a length of zero is no vent."""
    active = (count > 0) & (radius_m > 0) & (length_m > 0)
    if not np.any(active):
        return 0.0, 0.0
    r = np.where(active, radius_m, 1e-3)
    p_v, z_v = _thevenin(_tube(r, length_m, w, st, loss), _radiation(np.pi * r ** 2, w, st))
    y = np.where(active, count, 0.0) / z_v
    return y, p_v * y


# ---------------------------------------------------------------- responses (profile door)

@dataclass(eq=False)
class _Parts:
    """Everything about an aided design that does not depend on the canal."""
    flow: np.ndarray          # short-circuit volume flow at the tip outlet per unit free-field pressure, [F]
    admittance: np.ndarray    # source admittance at the tip outlet, [F]
    bore_flow: np.ndarray     # the bore's own share of `flow`
    bore_admittance: np.ndarray
    edges_mm: np.ndarray
    radii_m: np.ndarray
    dampers: Optional[tuple]


def _aided_parts(design, freqs, lossy=None, settings=None, ear_params=None):
    """Norton equivalent of bore + vents at the tip outlet (canal-independent)."""
    st = _settings(settings)
    w, loss = _omega(freqs), _loss(st, lossy)
    edges, radii, dampers = _profile_slices(design, w.max() / (2 * np.pi), st)
    src = _aided_source(design.concha_fill, w, st, ear_params)
    bore = _chain(radii, radii, np.diff(edges) * 1e-3, w, st, loss, dampers)
    p_b, z_b = _thevenin(bore, _radiation(design.area_mm2[0] * 1e-6, w, st))
    y_b, i_b = 1 / z_b + 0 * w, src * p_b / z_b + 0 * w
    y_v, i_v = _vent(float(design.vent_count), design.vent_diameter_mm / 2000.0, design.vent_length_mm * 1e-3, w, st, loss)
    return _Parts(i_b + src * i_v, y_b + y_v, i_b, y_b, edges, radii, dampers)


def open_ear(canal: Canal, freqs, tip_length_mm=9.0, lossy=None, settings=None, ear_params=None):
    """Eardrum pressure / free-field pressure for the open ear (complex, [F])."""
    st = _settings(settings)
    w = _omega(freqs)
    area, whole, _ = _canal_arrays([canal], tip_length_mm, st)     # the tip sits in the outer part
    return _open_ear(whole, area, w, st, _loss(st, lossy), ear_params)[0]


def aided(design: Design, canal: Canal, freqs, lossy=None, parts=None, settings=None, ear_params=None):
    """Eardrum pressure / free-field pressure with the aid in place (complex, [F])."""
    st = _settings(settings)
    w = _omega(freqs)
    parts = parts or _aided_parts(design, freqs, lossy, st, ear_params)
    area, _, residual = _canal_arrays([canal], design.tip_length_mm, st)
    return _to_drum(parts.flow / parts.admittance, 1 / parts.admittance, residual, area, w, st, _loss(st, lossy))[0]


def insertion_gain_db(design: Design, canals, freqs=DEFAULT_FREQS, lossy=None, settings=None, ear_params=None):
    """Insertion gain in dB, shape [n_canals, F].

    `ear_params` (the dial door's patient geometry) is optional: with it, the open-ear reference is the
    patient's own concha instead of the average resonance bump (Settings.concha).
    """
    st = _settings(settings)
    w, loss = _omega(freqs), _loss(st, lossy)
    canals = list(canals)
    if not canals:
        return np.empty((0, len(w)))
    parts = _aided_parts(design, freqs, lossy, st, ear_params)
    area, whole, residual = _canal_arrays(canals, design.tip_length_mm, st)
    with_aid = _to_drum(parts.flow / parts.admittance, 1 / parts.admittance, residual, area, w, st, loss)
    return 20 * np.log10(np.abs(with_aid) / np.abs(_open_ear(whole, area, w, st, loss, ear_params)))


def pressure_along_bore(design: Design, canal: Canal, freqs, lossy=None, settings=None, ear_params=None):
    """|pressure| / free-field pressure at each slice edge of the bore, [N+1, F] (for the 3D view)."""
    st = _settings(settings)
    w, loss = _omega(freqs), _loss(st, lossy)
    parts = _aided_parts(design, freqs, lossy, st, ear_params)
    area, _, residual = _canal_arrays([canal], design.tip_length_mm, st)
    # tip pressure from the node equation, then the bore's own outflow, then walk back to the mouth
    p_drum = _to_drum(parts.flow / parts.admittance, 1 / parts.admittance, residual, area, w, st, loss)[0]
    a, b, _, _ = _tube(np.sqrt(area[0] / np.pi), residual[0], w, st, loss)
    p = p_drum * (a + b / _drum(w, area[0], st))
    u = parts.bore_flow - p * parts.bore_admittance
    n = len(parts.radii_m)
    lengths = np.diff(parts.edges_mm) * 1e-3
    out = [np.abs(p)]
    for i in range(n, -1, -1):
        if i < n:
            ta, tb, tc, td = _tube(parts.radii_m[i], lengths[i], w, st, loss)
            p, u = ta * p + tb * u, tc * p + td * u
            out.append(np.abs(p))
        if parts.dampers is not None:
            p = p + u * np.where(parts.dampers[0] == i, parts.dampers[1], 0.0).sum()
            out[-1] = np.abs(p)              # an edge with a damper reports the pressure on its sound side
    return np.array(out[::-1]), parts.edges_mm


# ---------------------------------------------------------------- responses (dial door)

_DIAL_KEYS = ("throat_mm2", "mouth_mm2", "flare_mid1", "flare_mid2", "length_mm", "canal_stem_mm")
_VENT_KEYS = ("vent_count", "vent_diameter_mm", "vent_length_mm")


def _dial_dampers(x):
    """[(pos, ohm), ...] from a dial design: the damper_pos / damper_ohm pair and/or a "dampers" list."""
    pairs = [tuple(p) for p in x.get("dampers", ())]
    if "damper_ohm" in x:
        pairs.append((x.get("damper_pos", 0.0), x["damper_ohm"]))
    return pairs


def _check_dials(x):
    for k in _DIAL_KEYS:
        if k not in x:
            raise ValueError(f"the design is missing {k!r}")
    v = lambda k: np.asarray(x[k], float)
    for k in ("throat_mm2", "mouth_mm2"):
        _require(v(k) > 0, f"{k} must be positive, got {_span(v(k))} mm^2")
    _require(v("mouth_mm2") >= v("throat_mm2"),
             "mouth_mm2 is smaller than throat_mm2: the dial door describes a horn that widens toward the "
             "sound (use Design with an area profile for other shapes)")
    for k in ("length_mm", "canal_stem_mm") + tuple(k for k in _VENT_KEYS if k in x):
        _require(v(k) >= 0, f"{k} must not be negative, got {_span(v(k))}")
    r_t, r_m = np.sqrt(v("throat_mm2")), np.sqrt(v("mouth_mm2"))
    for k in ("flare_mid1", "flare_mid2"):
        _require(r_t + (r_m - r_t) * v(k) > 0, f"{k} = {_span(v(k))} gives a bore of no or negative radius")
    if "concha_fill" in x:
        _require((v("concha_fill") >= 0) & (v("concha_fill") <= 1), f"concha_fill must be between 0 and 1, got {_span(v('concha_fill'))}")
    for pos, ohm in _dial_dampers(x):
        pos, ohm = np.asarray(pos, float), np.asarray(ohm, float)
        _require((pos >= 0) & (pos <= 1), f"damper_pos must be between 0 (throat) and 1 (mouth), got {_span(pos)}")
        _require(ohm >= 0, f"damper_ohm must not be negative, got {_span(ohm)}")


def _flare_radius(r_throat, r_mouth, mid1, mid2, s):
    """Bore radius at fraction s from throat (0) to mouth (1): earpiece.py's flare, piecewise linear with
    mid1 / mid2 the share of the radius change done 1/3 and 2/3 of the way."""
    g = np.where(s < 1 / 3, 3 * s * mid1, np.where(s < 2 / 3, mid1 + (3 * s - 1) * (mid2 - mid1), mid2 + (3 * s - 2) * (1 - mid2)))
    return r_throat + (r_mouth - r_throat) * g


def bore_radii(x, n=None):
    """Bore radius (m) at n segment midpoints, throat (index 0) to mouth: earpiece.py's profile.
    Shape [..., n]. n defaults to BORE_SEGMENTS, or 40 when that is None."""
    n = n or BORE_SEGMENTS or LEGACY_BORE_SEGMENTS
    r_t, r_m = (np.sqrt(np.asarray(x[k], float)[..., None] / np.pi) * 1e-3 for k in ("throat_mm2", "mouth_mm2"))
    m1, m2 = (np.asarray(x[k], float)[..., None] for k in ("flare_mid1", "flare_mid2"))
    return _flare_radius(r_t, r_m, m1, m2, (np.arange(n) + 0.5) / n)


def horn(radii_m, length_m, w, damper=None, settings=None):
    """Mouth-to-throat matrix (a, b, c, d) of a bore given as radii[..., n] from throat to mouth (equal
    cylinder steps, whatever Settings.flare_slices says; `w` is angular frequency). `damper` = (pos 0..1, resistance Pa s/m3) is inserted at
    the step boundary nearest pos. Any collector shape can be passed here as its radii."""
    st = _settings(settings)
    radii_m = np.asarray(radii_m, float)
    _require(radii_m > 0, f"bore radii must be positive, got {_span(radii_m)} m")
    _require(np.asarray(length_m) >= 0, f"bore length must not be negative, got {_span(length_m)} m")
    n = radii_m.shape[-1]
    dampers = None
    if damper is not None:
        boundary = n - np.round(np.clip(damper[0], 0, 1) * n)             # counted from the mouth
        dampers = (np.asarray(boundary, float)[..., None], np.asarray(damper[1], float)[..., None])
    lengths = np.asarray(length_m, float)[..., None] / n
    from_mouth = radii_m[..., ::-1]
    return _chain(from_mouth, from_mouth, lengths, np.asarray(w, float), st, st.wall_losses, dampers)


def _head(theta_deg, w, settings=None):
    """Blocked pressure at the ear on a rigid sphere vs free field: Brown & Duda 1998 one-pole/one-zero
    head-shadow model. theta_deg is spec azimuth (0 front, 90 straight out from this ear)."""
    t = np.abs(np.asarray(theta_deg, float) - 90.0)
    alpha = (1 + BD_ALPHA_MIN / 2) + (1 - BD_ALPHA_MIN / 2) * np.cos(np.radians(t / BD_THETA_MIN * 180.0))
    q = w * HEAD_RADIUS_M / (2 * _settings(settings).air.c)
    return (1 + 1j * alpha * q) / (1 + 1j * q)


def _canal(ear_params, canal, settings=None):
    """Canal area (m2) and WHOLE canal length (m, [..., 1]), canal opening to eardrum."""
    st = _settings(settings)
    diameter = st.canal_diameter_mm or ear_params["canal_diameter_mm"]
    _require(diameter > 0, f"canal_diameter_mm must be positive, got {diameter}")
    tip = CANAL_SAMPLE_TIP_MM if st.canal_sample_tip_mm is None else st.canal_sample_tip_mm
    whole = (np.asarray(canal["length_mm"], float)[..., None] + tip) * 1e-3
    _require(whole >= 0, f"the canal has a negative length: sample {_span(canal['length_mm'])} mm + {tip:g} mm tip")
    return np.pi * (diameter * 1e-3) ** 2 / 4, whole


def _open(ear_params, canal, w, settings=None):
    """Dial door: open-ear eardrum pressure over the blocked pressure at the ear, [..., F]."""
    st = _settings(settings)
    area, whole = _canal(ear_params, canal, st)
    return _open_ear(whole, area, np.asarray(w, float), st, st.wall_losses, ear_params)


def _flare(x, w, st):
    """Mouth-to-throat matrix of the flare of every design in x, each [X..., F] with X the designs' shape."""
    names = ("throat_mm2", "mouth_mm2", "flare_mid1", "flare_mid2", "length_mm")
    pairs = _dial_dampers(x)
    arrays = [np.asarray(x[k], float) for k in names] + [np.asarray(v, float) for p in pairs for v in p]
    shape = np.broadcast_shapes(*(a.shape for a in arrays))
    flat = [np.broadcast_to(a, shape).reshape(-1) for a in arrays]
    throat, mouth, mid1, mid2, length = flat[:5]
    r_t, r_m, length = np.sqrt(throat / np.pi) * 1e-3, np.sqrt(mouth / np.pi) * 1e-3, length * 1e-3
    cones = st.flare_slices == "cones"
    forced = BORE_SEGMENTS or st.slice_count
    if forced:
        counts = np.full(len(r_t), int(forced))
    elif st.slice_step_mm is not None:
        counts = _ladder(np.maximum(8, np.ceil(length * 1e3 / st.slice_step_mm)))
    else:
        knots = np.log(_flare_radius(r_t[:, None], r_m[:, None], mid1[:, None], mid2[:, None], np.array([0, 1 / 3, 2 / 3, 1])))
        # multiples of 3, so slice edges fall on the flare's two corners and the cones follow it exactly
        counts = _ladder(_slices_needed(length, np.abs(np.diff(knots)).sum(-1), w.max() / (2 * np.pi), st, cones), multiple=3)
    if pairs:
        # dampers move the slice edges; cones also pin the flare's corners, as two more points with no resistance
        corners = np.broadcast_to([1 / 3, 2 / 3] if cones else [], (len(r_t), 2 if cones else 0))
        counts = np.maximum(counts, 2 * (len(pairs) + corners.shape[1] + 1))
        position = np.concatenate([1 - np.stack(flat[5::2], -1), corners], -1)   # dial 0 = throat; the chain runs from the mouth
        resistance = np.concatenate([np.stack(flat[6::2], -1) * OHM_CGS, 0 * corners], -1)
    out = [np.empty((len(r_t), w.shape[-1]), complex) for _ in range(4)]
    for n in np.unique(counts):                              # designs that need the same number of steps go together
        pick = np.nonzero(counts == n)[0]
        col = lambda a: a[pick, None]
        dampers = None
        if pairs:
            fractions, boundary, order = _warped_edges(int(n), position[pick])
            dampers = (boundary, np.take_along_axis(resistance[pick], order, -1))
        else:
            fractions = np.linspace(0.0, 1.0, int(n) + 1)
        radius = lambda at: _flare_radius(col(r_t), col(r_m), col(mid1), col(mid2), 1 - at)
        if cones:
            at_edges = radius(fractions)
            r_in, r_out = at_edges[..., :-1], at_edges[..., 1:]
        else:
            r_in = r_out = radius(0.5 * (fractions[..., :-1] + fractions[..., 1:]))
        m = _chain(r_in, r_out, col(length) * np.diff(fractions), w, st, st.wall_losses, dampers)
        for full, part in zip(out, m):
            full[pick] = part
    return tuple(a.reshape(shape + (w.shape[-1],)) for a in out)


def _aid(x, ear_params, canal, w, settings=None):
    """Dial door: eardrum pressure with the earpiece over the blocked pressure at the ear, [..., F]."""
    st = _settings(settings)
    w = np.asarray(w, float)
    _require(w.ndim == 1 and w.size > 0, "frequencies must be a 1D array")
    _check_dials(x)
    loss = st.wall_losses
    area, whole = _canal(ear_params, canal, st)
    g = lambda k, default=None: np.asarray(x[k] if default is None else x.get(k, default), float)[..., None]
    stem = g("canal_stem_mm") * 1e-3
    _require(stem <= whole, f"canal_stem_mm ({_span(stem * 1e3)} mm) is longer than the canal ({_span(whole * 1e3)} mm)")
    m = _mul(_flare(x, w, st), _tube(np.sqrt(g("throat_mm2") * 1e-6 / np.pi), stem, w, st, loss))
    p_oc, z = _thevenin(m, _radiation(g("mouth_mm2") * 1e-6, w, st))
    # vents: more sources in parallel at the stem tip (Norton sum); a count, diameter or length of 0 is no vent
    y_v, i_v = _vent(g("vent_count", 0.0), g("vent_diameter_mm", 0.0) * 0.5e-3, g("vent_length_mm", 0.0) * 1e-3, w, st, loss)
    y = 1 / z + y_v
    src = _aided_source(g("concha_fill", 1.0), w, st, ear_params)
    return _to_drum(src * (p_oc / z + i_v) / y, 1 / y, whole - stem, area, w, st, loss)


def _dial_shape(x, canal, w):
    """The shape B-style callers expect: every dial and the canal broadcast together, frequency last."""
    keys = [k for k in _DIAL_KEYS + _VENT_KEYS + ("damper_pos", "damper_ohm", "concha_fill") if k in x]
    return np.broadcast_shapes(*(np.shape(x[k]) for k in keys), np.shape(canal["length_mm"])) + w.shape[-1:]


def insertion_gain(x, ear_params, canal, freqs_hz, theta_deg=0, settings=None):
    """Eardrum pressure with the earpiece over the open ear, dB (the dial door).

    x            design dials (mm, mm2), names shared with earpiece.py:
                   throat_mm2, mouth_mm2, flare_mid1, flare_mid2, length_mm (flared bore, throat to mouth),
                   canal_stem_mm (how far the device runs into the canal; the bore continues through it at
                   the throat area), vent_count, vent_diameter_mm, vent_length_mm (optional; a count or a
                   diameter of 0 is no vent), damper_pos (0 throat .. 1 mouth) and damper_ohm (cgs acoustic
                   ohms; optional), "dampers" (optional list of (pos, ohm) pairs for more than one),
                   concha_fill (optional; "bump" concha model only).
    ear_params   the patient's ear: canal_diameter_mm, and for the geometry-based open ear concha_depth_mm,
                 bowl_volume_cc, opening_area_mm2.
    canal        {"length_mm": ...}: residual canal samples; the whole canal is sample + CANAL_SAMPLE_TIP_MM.
    Values may be numpy arrays; x, canal and freqs broadcast together with frequency on the LAST axis.

    theta_deg is accepted and ignored: both paths share the source, so the direction of the sound cancels in
    insertion gain (no mouth offset from the canal opening is modelled). It only changes open_ear_gain.

    DEFAULT PHYSICS: the unified model, not marc-sim's. Numbers differ from marc-sim's acoustics.py, mostly
    below 1 kHz (the eardrum now has compliance: sealed designs move by several dB there) and by a shift of
    about 2.6 % in every resonance frequency (air at 35 C, not 20 C). Pass settings=LEGACY_MARC_SIM to get
    the old numbers back.
    """
    w = _omega(freqs_hz)
    st = _settings(settings)
    gain = 20 * np.log10(np.abs(_aid(x, ear_params, canal, w, st) / _open(ear_params, canal, w, st)))
    shape = _dial_shape(x, canal, w)
    return gain if gain.shape == shape else np.broadcast_to(gain, shape).copy()


def open_ear_gain(ear_params, canal, freqs_hz, theta_deg=0, settings=None):
    """Open-ear eardrum pressure over the free field, dB (head + concha + canal), for checks.

    theta_deg (0 front, 90 straight out from this ear) sets the head's contribution; this is the only
    place the direction of the sound enters the model.
    """
    w = _omega(freqs_hz)
    st = _settings(settings)
    return 20 * np.log10(np.abs(_head(theta_deg, w, st) * _open(ear_params, canal, w, st)))


# ---------------------------------------------------------------- patient-level run

def evaluate(patient_dir, freqs=DEFAULT_FREQS, plot=True, log=print, settings=None):
    """Insertion gain of the built aid across the patient's sampled canals. Writes aid/acoustics.json (+ .png)."""
    aid_dir, ctx = os.path.join(patient_dir, "aid"), os.path.join(patient_dir, "context")
    d = json.load(open(os.path.join(aid_dir, "design.json")))
    cj = json.load(open(os.path.join(ctx, "canals.json")))
    design = Design.from_design_json(d)
    canals = [Canal(c["volume_cc"], cj["assumed_diameter_mm"]) for c in cj["canals"]]
    ig = insertion_gain_db(design, canals, freqs, settings=settings)
    oe = 20 * np.log10(np.abs(np.array([open_ear(c, freqs, design.tip_length_mm, settings=settings) for c in canals])))
    med = np.median(ig, 0)
    band = lambda lo, hi: float(np.mean(med[(freqs >= lo) & (freqs <= hi)]))
    out = {
        "freqs_hz": np.round(freqs, 1).tolist(),
        "insertion_gain_db": {"median": np.round(med, 2).tolist(), "min": np.round(ig.min(0), 2).tolist(),
                              "max": np.round(ig.max(0), 2).tolist()},
        "open_ear_gain_db_median": np.round(np.median(oe, 0), 2).tolist(),
        "summary": {"mean_ig_500_1k_db": round(band(500, 1000), 1), "mean_ig_1k_2k_db": round(band(1000, 2000), 1),
                    "mean_ig_2k_4k_db": round(band(2000, 4000), 1), "mean_ig_4k_8k_db": round(band(4000, 8000), 1),
                    "peak_ig_db": round(float(med.max()), 1), "peak_ig_hz": round(float(freqs[med.argmax()]))},
        "notes": ["1D plane-wave model with viscothermal losses.",
                  "Eardrum and concha use simplified average models; canal size is a sampled range."],
    }
    json.dump(out, open(os.path.join(aid_dir, "acoustics.json"), "w"), indent=1)
    if plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker
        fig, ax = plt.subplots(figsize=(9, 4.8))
        ax.fill_between(freqs, ig.min(0), ig.max(0), color="#f39a3d", alpha=.3, label=f"{len(canals)} sampled canals")
        ax.plot(freqs, med, c="#c2610a", lw=2.2, label="insertion gain (median canal)")
        ax.plot(freqs, np.median(oe, 0), c="#2459c9", lw=1.4, ls="--", label="open-ear natural boost (what the aid must beat)")
        ax.axhline(0, c="k", lw=.8)
        ax.set_xscale("log"); ax.set_xticks([125, 250, 500, 1000, 2000, 4000, 8000])
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.set_xlim(100, 8000); ax.set_xlabel("Hz"); ax.set_ylabel("dB"); ax.grid(alpha=.3); ax.legend(fontsize=8)
        ax.set_title("Insertion gain: eardrum level with the aid vs the open ear")
        plt.tight_layout(); plt.savefig(os.path.join(aid_dir, "insertion_gain.png"), dpi=90); plt.close(fig)
    log(f"acoustics: insertion gain 1-2 kHz {out['summary']['mean_ig_1k_2k_db']} dB, 2-4 kHz "
        f"{out['summary']['mean_ig_2k_4k_db']} dB, peak {out['summary']['peak_ig_db']} dB at {out['summary']['peak_ig_hz']} Hz")
    return out


if __name__ == "__main__":
    print(json.dumps(evaluate(sys.argv[1])["summary"], indent=1))
