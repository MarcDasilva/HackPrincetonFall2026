"""L1 acoustic model (spec 07): insertion gain of a passive horn earpiece over the open ear.

Plane-wave 2x2 transmission matrices [p1, U1] = [[A, B], [C, D]] @ [p2, U2], input side toward the
sound. Both paths are driven by the SAME blocked pressure at the concha opening (rim plane) and end
in the SAME eardrum load, so G = P_aid / P_open counts the open-ear resonance the device removes.

    aided:  p_b, mouth radiation -> bore (throat..mouth flare, viscothermal loss) -> canal stem at the
            throat area -> residual canal -> eardrum;  vent: p_b, inlet radiation -> vent tube -> joins
            at the stem tip
    open:   p_b, concha-opening radiation -> concha (wide tube) -> whole canal -> eardrum

Design variables `x` (mm, mm2; names shared with earpiece.py where they mean the same thing):
    throat_mm2, mouth_mm2, flare_mid1, flare_mid2   as earpiece.py (flare = share of the RADIUS change
                                                    done 1/3 and 2/3 of the way from throat to mouth)
    length_mm          flared bore, throat to mouth (the coiled path in aid.py)
    canal_stem_mm      as earpiece.py: how far the device runs into the canal; the bore continues
                       through it at the throat area and the residual canal is the rest
    vent_count, vent_diameter_mm, vent_length_mm      faceplate -> stem tip; count 0 = sealed (the
                       diameter must still be > 0)
    damper_pos, damper_ohm     series acoustic resistance in the bore at 0 (throat) .. 1 (mouth),
                               cgs acoustic ohms as hearing-aid dampers are rated; optional, absent = none
Values may be numpy arrays; x, canal and freqs broadcast together with frequency on the LAST axis.

A canal sample is one entry of context.py's canals.json, {"length_mm": ...}: a RESIDUAL canal
(volume / assumed area). Its area comes from ear_params["canal_diameter_mm"].
"""
import numpy as np
from scipy.special import j1, struve

C = 343.0          # m/s; SAME as wavesim.C so the two models are comparable
RHO = 1.204        # kg/m3, air at 20 C (standard tables, e.g. Kinsler et al. 4th ed. App. A10)
# Eardrum as a pure resistance, in units of rho*c / canal area. CALIBRATION KNOB, not a measurement;
# the SAME value as wavesim.EARDRUM_Z. With it the validation ear (90 deg, 25 mm canal) peaks at 17.3 dB
# at 2.99 kHz: inside the published 10-20 dB, and level with spec 03's wave run (17.3 dB at 2.53-2.56 kHz)
# though ~17% higher in frequency. 2.0 gives a ~16 dB peak, 5.0 gives ~21 dB. A real drum is also
# compliant at low frequencies; no sourced lumped values are in hand, so that term is left out.
DRUM_Z = 3.0
HEAD_RADIUS_M = 0.0875                   # Brown & Duda 1998 (IEEE TSAP 6(5)) average head
BD_ALPHA_MIN, BD_THETA_MIN = 0.1, 150.0  # Brown & Duda 1998, head-shadow model constants
# ASSUMPTION: a canal sample is the residual beyond aid.py's 6 mm tip (DEFAULT["tip_length_mm"]), so
# the whole canal is sample + 6 mm (17.5-26.2 mm over canals.json; wavesim assumes 25). The SAME
# whole canal is used in both paths, so a deeper stem shortens the residual, never the patient's canal.
CANAL_SAMPLE_TIP_MM = 6.0
BORE_SEGMENTS = 40                       # cylinder steps along the flare; see test_acoustics convergence
OHM_CGS = 1e5                            # 1 cgs acoustic ohm (dyn s / cm^5) = 1e5 Pa s / m^3


def _tube(r_m, length_m, w):
    """Lossy cylinder. Keefe (1984, JASA 75:58) large-rv expansion of the Kirchhoff viscothermal
    wavenumber and impedance; rv = r*sqrt(w*rho/eta) must stay above ~2 (r >= 0.4 mm at 100 Hz)."""
    rv = r_m * np.sqrt(w * RHO / 1.81e-5)                  # eta: air at 20 C, Pa s (same tables)
    z0 = RHO * C / (np.pi * r_m ** 2)
    zc = z0 * (1 + 0.369 / rv - 1j * (0.369 / rv + 1.149 / rv ** 2 + 0.303 / rv ** 3))
    gl = (w / C) * (1.045 / rv + 1.080 / rv ** 2 + 0.750 / rv ** 3 + 1j * (1 + 1.045 / rv)) * length_m
    ch, sh = np.cosh(gl), np.sinh(gl)
    return ch, zc * sh, sh / zc, ch


def _mul(m, n):
    return (m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3])


def _radiation(area_m2, w):
    """Piston in an infinite baffle (Rayleigh; Kinsler et al. 4th ed. eq. 7.5.11): the faceplate or
    the head around the concha opening is the baffle."""
    x = 2 * (w / C) * np.sqrt(area_m2 / np.pi)
    return RHO * C / area_m2 * (1 - 2 * j1(x) / x + 2j * struve(1, x) / x)


def _thevenin(m, z_src):
    """Open-circuit pressure (per unit source pressure) and source impedance at a two-port's output."""
    a, b, c, d = m
    den = a + c * z_src
    return 1 / den, (b + d * z_src) / den


def _to_drum(p_oc, z_src, canal_m, area_m2, w):
    """Pressure at the eardrum for a source (p_oc, z_src) feeding a canal of `canal_m` metres."""
    a, b, c, d = _tube(np.sqrt(area_m2 / np.pi), canal_m, w)
    z_drum = DRUM_Z * RHO * C / area_m2
    z_in = (a * z_drum + b) / (c * z_drum + d)
    return p_oc * z_in / (z_in + z_src) / (a + b / z_drum)


def bore_radii(x, n=None):
    """Bore radius (m) at n segment midpoints, throat (index 0) to mouth: earpiece.py's profile."""
    n = n or BORE_SEGMENTS
    s = (np.arange(n) + 0.5) / n
    r_t, r_m = (np.sqrt(np.asarray(x[k], float)[..., None] / np.pi) * 1e-3 for k in ("throat_mm2", "mouth_mm2"))
    m1, m2 = (np.asarray(x[k], float)[..., None] for k in ("flare_mid1", "flare_mid2"))
    g = np.where(s < 1 / 3, 3 * s * m1, np.where(s < 2 / 3, m1 + (3 * s - 1) * (m2 - m1), m2 + (3 * s - 2) * (1 - m2)))
    return r_t + (r_m - r_t) * g                      # [..., n]


def horn(radii_m, length_m, w, damper=None):
    """Mouth-to-throat matrix of a bore given as radii[..., n] from throat to mouth (cylinder steps).
    `damper` = (pos 0..1, resistance Pa s/m3) is inserted at the step boundary nearest pos."""
    n = radii_m.shape[-1]
    dl = np.asarray(length_m, float)[..., None] / n
    k_d = None if damper is None else np.round(np.clip(damper[0], 0, 1) * n)
    series = lambda k: (1, np.where(k_d == k, damper[1], 0.0)[..., None], 0, 1)
    m = (1, 0, 0, 1)
    for i in range(n - 1, -1, -1):                   # mouth first: the input side faces the sound
        if k_d is not None:
            m = _mul(m, series(i + 1))
        m = _mul(m, _tube(radii_m[..., i, None], dl, w))
    return m if k_d is None else _mul(m, series(0))


def _head(theta_deg, w):
    """Blocked pressure at the ear on a rigid sphere vs free field: Brown & Duda 1998 one-pole/one-zero
    head-shadow model. theta_deg is spec azimuth (0 front, 90 straight out from this ear)."""
    t = np.abs(np.asarray(theta_deg, float) - 90.0)
    alpha = (1 + BD_ALPHA_MIN / 2) + (1 - BD_ALPHA_MIN / 2) * np.cos(np.radians(t / BD_THETA_MIN * 180.0))
    q = w * HEAD_RADIUS_M / (2 * C)
    return (1 + 1j * alpha * q) / (1 + 1j * q)


def _canal(ear_params, canal):
    """Canal area (m2) and WHOLE canal length (m), canal opening to eardrum."""
    area = np.pi * (ear_params["canal_diameter_mm"] * 1e-3) ** 2 / 4
    return area, (np.asarray(canal["length_mm"], float)[..., None] + CANAL_SAMPLE_TIP_MM) * 1e-3


def _open(ear_params, canal, w):
    area, L = _canal(ear_params, canal)
    # the tube keeps the bowl's air volume (a uniform tube at the opening area would hold ~50% more on
    # the validation ear); the opening area sets only the radiation load
    depth = ear_params["concha_depth_mm"] * 1e-3
    concha = _tube(np.sqrt(ear_params["bowl_volume_cc"] * 1e-6 / depth / np.pi), depth, w)
    p_oc, z = _thevenin(concha, _radiation(ear_params["opening_area_mm2"] * 1e-6, w))
    return _to_drum(p_oc, z, L, area, w)


def _aid(x, ear_params, canal, w):
    area, L = _canal(ear_params, canal)
    g = lambda k: np.asarray(x[k], float)[..., None]
    damper = (g("damper_pos")[..., 0], g("damper_ohm")[..., 0] * OHM_CGS) if "damper_ohm" in x else None
    m = horn(bore_radii(x), g("length_mm")[..., 0] * 1e-3, w, damper)
    stem = g("canal_stem_mm") * 1e-3
    m = _mul(m, _tube(np.sqrt(g("throat_mm2") * 1e-6 / np.pi), stem, w))
    p_oc, z = _thevenin(m, _radiation(g("mouth_mm2") * 1e-6, w))
    # vent: a second source in parallel at the stem tip (Norton sum); count 0 leaves the bore alone
    r_v = g("vent_diameter_mm") * 0.5e-3
    pv, zv = _thevenin(_tube(r_v, g("vent_length_mm") * 1e-3, w), _radiation(np.pi * r_v ** 2, w))
    yv = g("vent_count") / zv
    y = 1 / z + yv
    return _to_drum((p_oc / z + pv * yv) / y, 1 / y, L - stem, area, w)


def insertion_gain(x, ear_params, canal, freqs_hz, theta_deg=0):
    """Eardrum pressure with the earpiece over the open ear, dB. theta_deg cancels: both paths share
    the source and no mouth offset from the canal opening is modelled yet (spec 03 will add it)."""
    w = 2 * np.pi * np.asarray(freqs_hz, float)
    return 20 * np.log10(np.abs(_aid(x, ear_params, canal, w) / _open(ear_params, canal, w)))


def open_ear_gain(ear_params, canal, freqs_hz, theta_deg=0):
    """Open-ear eardrum pressure over the free field, dB (head + concha + canal), for checks."""
    w = 2 * np.pi * np.asarray(freqs_hz, float)
    return 20 * np.log10(np.abs(_head(theta_deg, w) * _open(ear_params, canal, w)))
