"""1D acoustic model of the in-ear horn: geometry -> insertion gain at the eardrum.

Sound in a bore this narrow travels as plane waves (first cross-mode of a 5 mm duct is
near 40 kHz), so the bore is a chain of short tube slices. Each slice is a 2x2
transmission matrix relating (pressure, volume flow) at its two ends:

    [p_in]   [A B] [p_out]
    [U_in] = [C D] [U_out]

Pieces
  bore / vent / canal   lossy circular tubes. Viscous and thermal wall losses use the exact
                        circular-tube solution (Zwikker & Kosten 1949; Keefe 1984, JASA 75:58).
  mouth, vent inlet     flanged-piston radiation impedance, low-ka form (Levine & Schwinger
                        1948 give the unflanged case; the flanged end correction is 8a/3pi).
  eardrum               series resistance-mass-compliance. SIMPLIFIED: values are chosen in the
                        published adult range and so that the open ear reproduces the familiar
                        ~3 kHz canal resonance; swap in measured impedance data when available.
  concha                the open ear gets the concha's resonance boost; a shell that fills the
                        concha removes it in proportion to `concha_fill`. SIMPLIFIED: one
                        resonance bump approximating Shaw's (1974) average concha component.

Insertion gain = eardrum pressure with the aid / eardrum pressure with the ear open, both for
the same free-field sound. Head and torso effects are common to both and cancel.

    python -m hornsim.acoustics <patient_dir>      # needs <patient_dir>/aid/design.json
"""
import json
import os
import sys
from dataclasses import dataclass, field

import numpy as np
from scipy.special import jve

# Air at about 35 C (ear canal / worn device)
C0 = 351.9          # speed of sound, m/s
RHO = 1.146         # density, kg/m^3
MU = 1.88e-5        # dynamic viscosity, Pa s
PR = 0.71           # Prandtl number
GAMMA = 1.40        # ratio of specific heats

# Eardrum (see module docstring: simplified)
EARDRUM_R = 3.5e7       # Pa s/m^3   (~350 cgs acoustic ohms)
EARDRUM_VEQ_CC = 0.75   # equivalent volume of the middle-ear compliance, cm^3
EARDRUM_M = 4.0e2       # kg/m^4

# Concha resonance (see module docstring: simplified)
CONCHA_PEAK_DB, CONCHA_F0, CONCHA_WIDTH_OCT = 9.0, 4800.0, 0.5

DEFAULT_FREQS = np.geomspace(100.0, 8000.0, 160)


@dataclass
class Design:
    """Acoustic description of one aid. Lengths in mm, areas in mm^2."""
    s_mm: np.ndarray                 # positions along the bore, mouth (0) -> throat outlet
    area_mm2: np.ndarray             # bore area at each position
    vent_diameter_mm: float = 0.0    # 0 = no vent
    vent_length_mm: float = 0.0
    concha_fill: float = 1.0         # 0 = concha left open, 1 = shell fills it
    tip_length_mm: float = 9.0       # how far the tip reaches into the canal

    @staticmethod
    def from_design_json(d):
        a = d["acoustic"]
        return Design(np.asarray(a["s_mm"], float), np.asarray(a["area_mm2"], float),
                      a.get("vent_diameter_mm", 0.0), a.get("vent_length_mm", 0.0),
                      a.get("concha_fill", 1.0), a.get("tip_length_mm", 9.0))


@dataclass
class Canal:
    """One sampled ear canal. `volume_cc` is the air left between the tip and the eardrum."""
    volume_cc: float
    diameter_mm: float = 7.5

    @property
    def area_m2(self):
        return np.pi * (self.diameter_mm / 2000.0) ** 2

    @property
    def residual_length_m(self):
        return self.volume_cc * 1e-6 / self.area_m2


# ---------------------------------------------------------------- tubes

def tube_constants(radius_m, freqs, lossy=True):
    """Propagation constant (1/m) and characteristic impedance (Pa s/m^3) of a circular tube.

    radius_m: scalar or array [N]; freqs: [F]. Returns arrays [N, F] (or [F] for a scalar radius).
    """
    a = np.atleast_1d(np.asarray(radius_m, float))[:, None]
    w = 2 * np.pi * np.asarray(freqs, float)[None, :]
    S = np.pi * a ** 2
    if lossy:
        kv = np.sqrt(-1j * w * RHO / MU) * a            # viscous
        kt = kv * np.sqrt(PR)                            # thermal
        Fv = 2 * jve(1, kv) / (kv * jve(0, kv))
        Ft = 2 * jve(1, kt) / (kt * jve(0, kt))
        Z = 1j * w * RHO / S / (1 - Fv)                  # series impedance per metre
        Y = 1j * w * S / (RHO * C0 ** 2) * (1 + (GAMMA - 1) * Ft)   # shunt admittance per metre
    else:
        Z = 1j * w * RHO / S + 0 * a
        Y = 1j * w * S / (RHO * C0 ** 2) + 0 * a
    G, Zc = np.sqrt(Z * Y), np.sqrt(Z / Y)
    if np.ndim(radius_m) == 0:
        return G[0], Zc[0]
    return G, Zc


def tube_abcd(radius_m, length_m, freqs, lossy=True):
    """Transmission matrix [F, 2, 2] of one uniform tube."""
    G, Zc = tube_constants(float(radius_m), freqs, lossy)
    gl = G * length_m
    M = np.empty((len(freqs), 2, 2), complex)
    M[:, 0, 0] = M[:, 1, 1] = np.cosh(gl)
    M[:, 0, 1] = Zc * np.sinh(gl)
    M[:, 1, 0] = np.sinh(gl) / Zc
    return M


def bore_slices(s_mm, area_mm2, freqs, lossy=True, ds_mm=0.25):
    """Per-slice matrices [N, F, 2, 2] for a bore with varying area (stepped short tubes)."""
    s = np.asarray(s_mm, float)
    n = max(8, int(np.ceil((s[-1] - s[0]) / ds_mm)))
    edges = np.linspace(s[0], s[-1], n + 1)
    mid = 0.5 * (edges[:-1] + edges[1:])
    area = np.interp(mid, s, np.asarray(area_mm2, float)) * 1e-6
    r = np.sqrt(area / np.pi)
    G, Zc = tube_constants(r, freqs, lossy)
    gl = G * (np.diff(edges)[:, None] * 1e-3)
    M = np.empty((n, len(freqs), 2, 2), complex)
    M[..., 0, 0] = M[..., 1, 1] = np.cosh(gl)
    M[..., 0, 1] = Zc * np.sinh(gl)
    M[..., 1, 0] = np.sinh(gl) / Zc
    return M, edges


def chain(mats):
    """Product of per-slice matrices [N, F, 2, 2] in order -> [F, 2, 2]."""
    out = mats[0]
    for m in mats[1:]:
        out = out @ m
    return out


# ---------------------------------------------------------------- terminations and sources

def radiation_impedance(radius_m, freqs):
    """Flanged circular opening, low-ka approximation."""
    k = 2 * np.pi * np.asarray(freqs, float) / C0
    ka = k * radius_m
    return RHO * C0 / (np.pi * radius_m ** 2) * (ka ** 2 / 2 + 1j * 8 * ka / (3 * np.pi))


def eardrum_impedance(freqs):
    w = 2 * np.pi * np.asarray(freqs, float)
    comp = EARDRUM_VEQ_CC * 1e-6 / (RHO * C0 ** 2)
    return EARDRUM_R + 1j * w * EARDRUM_M + 1 / (1j * w * comp)


def concha_gain_db(freqs):
    """Pressure boost of the open concha at the canal entrance: one bump on a log-frequency axis."""
    octaves = np.log2(np.asarray(freqs, float) / CONCHA_F0)
    return CONCHA_PEAK_DB * np.exp(-0.5 * (octaves / CONCHA_WIDTH_OCT) ** 2)


def _thevenin(M, z_source):
    """Open-circuit pressure (per unit source pressure) and output impedance of a driven two-port."""
    A, B, Cc, D = M[:, 0, 0], M[:, 0, 1], M[:, 1, 0], M[:, 1, 1]
    den = A + z_source * Cc
    return 1 / den, (B + z_source * D) / den


# ---------------------------------------------------------------- responses

def open_ear(canal: Canal, freqs, tip_length_mm=9.0, lossy=True):
    """Eardrum pressure / free-field pressure for the open ear (complex, [F])."""
    r = canal.diameter_mm / 2000.0
    length = canal.residual_length_m + tip_length_mm * 1e-3      # the tip sits in the outer part
    M = tube_abcd(r, length, freqs, lossy)
    zr, ze = radiation_impedance(r, freqs), eardrum_impedance(freqs)
    src = 10 ** (concha_gain_db(freqs) / 20)
    A, B, Cc, D = M[:, 0, 0], M[:, 0, 1], M[:, 1, 0], M[:, 1, 1]
    return src / (A + zr * Cc + (B + zr * D) / ze)


def _aided_parts(design: Design, freqs, lossy=True):
    """Everything that does not depend on the canal: Thevenin equivalents at the tip outlet."""
    src = 10 ** ((1 - design.concha_fill) * concha_gain_db(freqs) / 20)
    slices, edges = bore_slices(design.s_mm, design.area_mm2, freqs, lossy)
    r_mouth = np.sqrt(design.area_mm2[0] * 1e-6 / np.pi)
    p_b, z_b = _thevenin(chain(slices), radiation_impedance(r_mouth, freqs))
    y = 1 / z_b
    i = src * p_b / z_b
    if design.vent_diameter_mm > 0 and design.vent_length_mm > 0:
        rv = design.vent_diameter_mm / 2000.0
        p_v, z_v = _thevenin(tube_abcd(rv, design.vent_length_mm * 1e-3, freqs, lossy), radiation_impedance(rv, freqs))
        y = y + 1 / z_v
        i = i + src * p_v / z_v
    return i, y, slices, edges, src


def aided(design: Design, canal: Canal, freqs, lossy=True, parts=None):
    """Eardrum pressure / free-field pressure with the aid in place (complex, [F])."""
    i, y, *_ = parts or _aided_parts(design, freqs, lossy)
    M = tube_abcd(canal.diameter_mm / 2000.0, canal.residual_length_m, freqs, lossy)
    ze = eardrum_impedance(freqs)
    A, B, Cc, D = M[:, 0, 0], M[:, 0, 1], M[:, 1, 0], M[:, 1, 1]
    z_in = (A * ze + B) / (Cc * ze + D)
    p_tip = i / (y + 1 / z_in)
    return p_tip / (A + B / ze)


def insertion_gain_db(design: Design, canals, freqs=DEFAULT_FREQS, lossy=True):
    """Insertion gain in dB, shape [n_canals, F]."""
    parts = _aided_parts(design, freqs, lossy)
    out = []
    for c in canals:
        a = aided(design, c, freqs, lossy, parts)
        o = open_ear(c, freqs, design.tip_length_mm, lossy)
        out.append(20 * np.log10(np.abs(a) / np.abs(o)))
    return np.array(out)


def pressure_along_bore(design: Design, canal: Canal, freqs, lossy=True):
    """|pressure| / free-field pressure at each slice edge of the bore, [N+1, F] (for the 3D view)."""
    parts = _aided_parts(design, freqs, lossy)
    i, y, slices, edges, _ = parts
    M = tube_abcd(canal.diameter_mm / 2000.0, canal.residual_length_m, freqs, lossy)
    ze = eardrum_impedance(freqs)
    A, B, Cc, D = M[:, 0, 0], M[:, 0, 1], M[:, 1, 0], M[:, 1, 1]
    z_in = (A * ze + B) / (Cc * ze + D)
    p_tip = i / (y + 1 / z_in)
    # flow out of the bore = flow into canal + flow out through the vent path's share; solve at the node
    slices_all = chain(slices)
    r_mouth = np.sqrt(design.area_mm2[0] * 1e-6 / np.pi)
    _, z_b = _thevenin(slices_all, radiation_impedance(r_mouth, freqs))
    src_b = parts[4] / (slices_all[:, 0, 0] + radiation_impedance(r_mouth, freqs) * slices_all[:, 1, 0])
    u_out = (src_b - p_tip) / z_b
    state = np.stack([p_tip, u_out], -1)[..., None]               # [F, 2, 1] at the outlet
    ps = [np.abs(p_tip)]
    for m in slices[::-1]:
        state = m @ state
        ps.append(np.abs(state[:, 0, 0]))
    return np.array(ps[::-1]), edges


# ---------------------------------------------------------------- patient-level run

def evaluate(patient_dir, freqs=DEFAULT_FREQS, plot=True, log=print):
    """Insertion gain of the built aid across the patient's sampled canals. Writes aid/acoustics.json (+ .png)."""
    aid_dir, ctx = os.path.join(patient_dir, "aid"), os.path.join(patient_dir, "context")
    d = json.load(open(os.path.join(aid_dir, "design.json")))
    cj = json.load(open(os.path.join(ctx, "canals.json")))
    design = Design.from_design_json(d)
    canals = [Canal(c["volume_cc"], cj["assumed_diameter_mm"]) for c in cj["canals"]]
    ig = insertion_gain_db(design, canals, freqs)
    oe = 20 * np.log10(np.abs(np.array([open_ear(c, freqs, design.tip_length_mm) for c in canals])))
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
