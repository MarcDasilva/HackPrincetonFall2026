"""Physics checks for the 1D acoustic model. Run from backend/: .venv/bin/python -m pytest tests -q"""
import numpy as np

from hornsim import acoustics as ac

F = np.geomspace(100, 8000, 400)


def exp_horn(length_mm=187.0, mouth=22.2, throat=1.0, n=400):
    s = np.linspace(0, length_mm, n)
    return s, mouth * (throat / mouth) ** (s / length_mm)


def test_closed_tube_resonances_match_quarter_wave():
    # 100 mm tube, rigid far end: input impedance minima at c/4L, 3c/4L
    L, f = 0.100, np.linspace(200, 3500, 6000)
    M = ac.tube_abcd(0.004, L, f, lossy=False)
    zin = np.abs(M[:, 0, 0] / M[:, 1, 0])
    mins = f[1:-1][(zin[1:-1] < zin[:-2]) & (zin[1:-1] < zin[2:])]
    expect = ac.C0 / (4 * L) * np.array([1, 3])
    assert np.allclose(mins[:2], expect, rtol=0.01)


def test_lossless_horn_gain_approaches_area_ratio_above_cutoff():
    s, area = exp_horn()
    M = ac.chain(ac.bore_slices(s, area, F, lossy=False)[0])
    zl = ac.RHO * ac.C0 / (area[-1] * 1e-6)                    # matched load at the throat
    gain = 20 * np.log10(np.abs(1 / (M[:, 0, 0] + M[:, 0, 1] / zl)))
    hi = gain[(F > 2000) & (F < 8000)].mean()
    assert abs(hi - 10 * np.log10(22.2)) < 1.0                 # ~13.5 dB
    assert gain[F < 200].mean() < hi - 6                       # rolls off below the ~460 Hz cutoff


def test_wall_losses_reduce_horn_gain():
    s, area = exp_horn()
    zl = ac.RHO * ac.C0 / (area[-1] * 1e-6)
    g = {}
    for lossy in (False, True):
        M = ac.chain(ac.bore_slices(s, area, F, lossy=lossy)[0])
        g[lossy] = 20 * np.log10(np.abs(1 / (M[:, 0, 0] + M[:, 0, 1] / zl)))
    band = (F > 2000) & (F < 6000)
    assert g[True][band].mean() < g[False][band].mean() - 1.0


def test_narrow_tube_attenuation_matches_keefe_wide_tube_formula():
    a, f = 0.5e-3, np.array([1000.0])
    G, _ = ac.tube_constants(a, f)
    w = 2 * np.pi * f[0]
    rv = a * np.sqrt(ac.RHO * w / ac.MU)
    alpha = (w / ac.C0) * (1 + (ac.GAMMA - 1) / np.sqrt(ac.PR)) / (np.sqrt(2) * rv)   # leading term
    assert abs(G.real[0] - alpha) / alpha < 0.15


def test_open_ear_has_canal_resonance_near_3k():
    g = 20 * np.log10(np.abs(ac.open_ear(ac.Canal(0.7), F)))
    peak_f, peak = F[g.argmax()], g.max()
    assert 2300 < peak_f < 4200
    assert 8 < peak < 22
    assert abs(g[F < 300].mean()) < 1.5                        # no boost at low frequencies


def _design(vent=0.0, fill=1.0, length=51.0):
    s, area = exp_horn(length)
    return ac.Design(s, area, vent_diameter_mm=vent, vent_length_mm=12.0 if vent else 0.0, concha_fill=fill)


def test_smaller_canal_is_louder_at_low_frequency_when_sealed():
    d = _design()
    lo = (F > 300) & (F < 700)
    small = np.abs(ac.aided(d, ac.Canal(0.5), F))[lo].mean()
    large = np.abs(ac.aided(d, ac.Canal(0.9), F))[lo].mean()
    assert small > large


def test_narrow_throat_into_canal_is_a_low_pass():
    # a 1 mm^2 throat feeding the canal's air volume behaves like an earplug at speech highs
    ig = ac.insertion_gain_db(_design(), [ac.Canal(0.7)], F)[0]
    assert ig[(F > 2000) & (F < 4000)].mean() < -10


def test_wide_vent_brings_highs_back_toward_the_open_ear():
    c, band = [ac.Canal(0.7)], (F > 2000) & (F < 4000)
    sealed = ac.insertion_gain_db(_design(), c, F)[0][band].mean()
    vented = ac.insertion_gain_db(_design(vent=3.0), c, F)[0][band].mean()
    assert sealed < vented < 3


def test_canal_size_horn_is_close_to_the_open_ear():
    # mouth = most of the concha, throat = canal: about what the concha does naturally
    s = np.linspace(0, 18, 200)
    d = ac.Design(s, 300 * (40 / 300) ** (s / 18))
    ig = ac.insertion_gain_db(d, [ac.Canal(0.7)], F)[0]
    assert np.abs(ig[(F > 500) & (F < 4000)]).max() < 6


def test_passive_device_gain_is_bounded_and_finite():
    ig = ac.insertion_gain_db(_design(vent=0.8), [ac.Canal(v) for v in (0.5, 0.7, 0.9)], F)
    assert np.isfinite(ig).all()
    assert ig.max() < 20


def test_pressure_along_bore_is_consistent_with_the_eardrum_response():
    d, c, f = _design(length=120.0), ac.Canal(0.7), np.array([500.0, 2000.0, 4000.0])
    p, edges = ac.pressure_along_bore(d, c, f)
    assert p.shape == (len(edges), len(f)) and np.isfinite(p).all()
    M = ac.tube_abcd(c.diameter_mm / 2000, c.residual_length_m, f)
    p_ed_from_outlet = p[-1] / np.abs(M[:, 0, 0] + M[:, 0, 1] / ac.eardrum_impedance(f))
    assert np.allclose(p_ed_from_outlet, np.abs(ac.aided(d, c, f)), rtol=1e-6)
