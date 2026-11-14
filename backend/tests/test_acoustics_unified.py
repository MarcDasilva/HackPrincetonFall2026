"""The unified acoustic model: known answers, equivalence with the two models it replaced, both front doors.

    backend/.venv/bin/python -m pytest backend/tests/test_acoustics_unified.py -q

Golden values come from data/acoustics_golden.json (see golden_acoustics.py for how they were made).
"""
import json
import math

import numpy as np
import pytest
from scipy.special import jve

import golden_acoustics as golden
from hornsim import acoustics as ac

F = golden.FREQS
GOLD = json.load(open(golden.GOLDEN))
EAR = GOLD["ear_params"]
WHOLE = np.array(GOLD["whole_canal_mm"])
DIAL_CANAL = {"length_mm": WHOLE - 6.0}          # the dial door adds its 6 mm tip back
WIDE = np.geomspace(100, 8000, 300)


def coil(**kw):
    """marc-sim's coil test design: 1 -> 22.2 mm2 over 64 mm, 6 mm stem, one 0.8 mm vent."""
    return {"throat_mm2": 1.0, "mouth_mm2": 22.2, "flare_mid1": 0.182, "flare_mid2": 0.488, "length_mm": 64.0,
            "canal_stem_mm": 6.0, "vent_count": 1, "vent_diameter_mm": 0.8, "vent_length_mm": 20.0} | kw


def earpiece(**kw):
    """A wide sealed in-concha earpiece: 27 -> 150 mm2 over 22 mm, 5 mm stem."""
    return {"throat_mm2": 27.0, "mouth_mm2": 150.0, "flare_mid1": 0.15, "flare_mid2": 0.45, "length_mm": 22.0,
            "canal_stem_mm": 5.0} | kw


def profile_design(d):
    """A common design as main's model received it in the comparison (golden_acoustics.generate)."""
    x = d["x"]
    vent = x["vent_count"] > 0
    return ac.Design(*golden.profile_from_dials(x), vent_diameter_mm=x["vent_diameter_mm"] if vent else 0.0,
                     vent_length_mm=x["vent_length_mm"] if vent else 0.0, concha_fill=d["concha_fill"],
                     tip_length_mm=x["canal_stem_mm"])


def profile_canals(stem_mm):
    return [ac.Canal(v, GOLD["canal_diameter_mm"]) for v in golden.residual_volume_cc(WHOLE, stem_mm)]


def random_dials(n, seed):
    """n random dial designs, each value [n]: 0.5-40 mm2 throats, up to 100x flare, 3-90 mm, 0-2 vents."""
    rng = np.random.default_rng(seed)
    throat = np.exp(rng.uniform(np.log(0.5), np.log(40), n))
    mid1 = rng.uniform(0.0, 0.6, n)
    return {"throat_mm2": throat, "mouth_mm2": np.minimum(throat * np.exp(rng.uniform(np.log(1.05), np.log(100), n)), 600.0),
            "length_mm": rng.uniform(3, 90, n), "canal_stem_mm": rng.uniform(0, 8, n),
            "vent_count": rng.integers(0, 3, n).astype(float), "vent_diameter_mm": rng.uniform(0.5, 3.0, n),
            "vent_length_mm": rng.uniform(5, 25, n), "flare_mid1": mid1, "flare_mid2": mid1 + rng.uniform(0.0, 1.0, n) * (1 - mid1)}


# ---------------------------------------------------------------- known answers

def piston_series(x, terms=40):
    """Rayleigh's flanged-piston functions by their power series: R1 = 1 - 2 J1(x)/x, X1 = 2 H1(x)/x."""
    r1 = sum((-1) ** (k + 1) * (x / 2) ** (2 * k) / (math.factorial(k) * math.factorial(k + 1)) for k in range(1, terms))
    x1, term = 0.0, x / 3
    for k in range(1, terms):
        x1 += term
        term *= -x ** 2 / ((2 * k + 1) * (2 * k + 3))
    return r1, 4 / math.pi * x1


def test_exact_radiation_matches_the_flanged_piston_across_ka():
    a = 0.012                                                    # a 450 mm2 mouth
    for ka in (1e-4, 3e-3, 0.004999, 0.005001, 0.05, 0.3, 1.0, 2.0, 3.0, 5.0):
        f = ka * ac.C0 / (2 * np.pi * a)
        z = ac.radiation_impedance(a, [f])[0] * np.pi * a ** 2 / (ac.RHO * ac.C0)
        r1, x1 = piston_series(2 * ka)
        assert z.real == pytest.approx(r1, rel=1e-9), ka
        assert z.imag == pytest.approx(x1, rel=1e-9), ka
    # the low-ka form is the first term of each series, and is what LEGACY_MAIN still uses
    low = ac.radiation_impedance(a, [50.0], settings=ac.LEGACY_MAIN)[0]
    assert ac.radiation_impedance(a, [50.0])[0] == pytest.approx(low, rel=1e-3)
    ka = 2 * np.pi * 6000 * a / ac.C0                            # 1.3: the low-ka resistance is a third too high here
    high = ac.radiation_impedance(a, [6000.0], settings=ac.LEGACY_MAIN)[0]
    assert high.real * np.pi * a ** 2 / (ac.RHO * ac.C0) == pytest.approx(ka ** 2 / 2)
    assert high.real > 1.3 * ac.radiation_impedance(a, [6000.0])[0].real


def test_bore_matrices_are_reciprocal():
    s, area = golden.exp_horn(70.0)
    det = lambda m: m[..., 0, 0] * m[..., 1, 1] - m[..., 0, 1] * m[..., 1, 0]
    for lossy in (False, True):
        assert np.abs(det(ac.chain(ac.bore_slices(s, area, WIDE, lossy=lossy)[0])) - 1).max() < 1e-9
    w = 2 * np.pi * WIDE
    for settings in (ac.UNIFIED, ac.UNIFIED.replace(wall_losses="none"), ac.LEGACY_MARC_SIM):
        a, b, c, d = ac._flare(coil(damper_pos=0.4, damper_ohm=1500.0), w, settings)     # conical or stepped, with a damper
        assert np.abs(a * d - b * c - 1).max() < 1e-9
    a, b, c, d = ac.horn(ac.bore_radii(coil()), 0.064, w)
    assert np.abs(a * d - b * c - 1).max() < 1e-9


def test_lossless_bore_is_passive_and_lossy_bore_absorbs():
    w = 2 * np.pi * WIDE
    z_load = ac.RHO * ac.C0 / 1e-6
    for losses, absorbs in (("none", False), ("exact", True)):
        a, b, c, d = ac._flare(coil(), w, ac.UNIFIED.replace(wall_losses=losses))
        p_in, u_in = a * z_load + b, c * z_load + d                      # unit flow into the load
        power_in, power_out = (p_in * np.conj(u_in)).real, z_load
        assert (power_in > power_out * (1 + 1e-3)).all() if absorbs else np.allclose(power_in, power_out, rtol=1e-9)


def test_sealed_narrow_bore_tends_to_0_db_at_low_frequency():
    # with no vent the static pressure still equalises through the bore: the aid cannot change the level at DC
    low = np.array([2.0, 5.0, 10.0])
    sealed = ac.Design(*golden.exp_horn(51.0))
    assert np.abs(ac.insertion_gain_db(sealed, [ac.Canal(0.5), ac.Canal(0.9)], low)).max() < 0.02
    assert np.abs(ac.insertion_gain(coil(vent_count=0), EAR, DIAL_CANAL, low)).max() < 0.03
    # the purely resistive eardrum of marc-sim misses this limit by more than 1 dB
    assert np.abs(ac.insertion_gain(coil(vent_count=0), EAR, DIAL_CANAL, low, settings=ac.LEGACY_MARC_SIM)).min() > 1.0


def test_canal_sized_bore_with_the_concha_open_changes_nothing():
    # a tip as wide as the canal, as long as the tip, concha left open: the ear is acoustically untouched
    canal = ac.Canal(0.7)
    s = np.linspace(0, 9.0, 10)
    design = ac.Design(s, np.full(10, canal.area_m2 * 1e6), concha_fill=0.0, tip_length_mm=9.0)
    assert np.abs(ac.insertion_gain_db(design, [canal], WIDE)).max() < 1e-9
    # filling the concha instead costs its boost
    filled = ac.Design(s, np.full(10, canal.area_m2 * 1e6), concha_fill=1.0, tip_length_mm=9.0)
    assert ac.insertion_gain_db(filled, [canal], [4800.0])[0, 0] == pytest.approx(-ac.CONCHA_PEAK_DB)


def test_exact_wall_losses_match_the_bessel_solution():
    # the table lookup against the Zwikker-Kosten expressions evaluated directly, 0.1 mm vents to 10 mm bores
    radii = np.geomspace(0.05e-3, 10e-3, 40)
    freqs = np.geomspace(20, 20000, 60)
    g, zc = ac.tube_constants(radii, freqs)
    w = 2 * np.pi * freqs[None, :]
    a = radii[:, None]
    bessel = lambda k: 2 * jve(1, k) / (k * jve(0, k))
    kv = np.sqrt(-1j * w * ac.RHO / ac.MU) * a
    z = 1j * w * ac.RHO / (np.pi * a ** 2) / (1 - bessel(kv))
    y = 1j * w * np.pi * a ** 2 / (ac.RHO * ac.C0 ** 2) * (1 + (ac.GAMMA - 1) * bessel(kv * np.sqrt(ac.PR)))
    assert np.abs(g / np.sqrt(z * y) - 1).max() < 1e-6
    assert np.abs(zc / np.sqrt(z / y) - 1).max() < 1e-6
    # beyond the table the same expressions are evaluated directly
    g_thin, _ = ac.tube_constants(1e-6, [20.0])
    assert np.isfinite(g_thin).all() and g_thin.real[0] > 0
    # Poiseuille limit: a hair-thin tube's resistance per metre is 8 mu / (pi a^4)
    g, zc = ac.tube_constants(20e-6, [100.0])
    assert (g * zc).real[0] == pytest.approx(8 * ac.MU / (np.pi * 20e-6 ** 4), rel=1e-3)


def test_slicing_converges_within_a_tenth_of_a_db():
    x = random_dials(120, seed=21)
    column = {k: v[:, None] for k, v in x.items()}
    got = ac.insertion_gain(column, EAR, DIAL_CANAL, WIDE)
    fine = ac.insertion_gain(column, EAR, DIAL_CANAL, WIDE, settings=ac.UNIFIED.replace(slice_count=768))
    assert np.abs(got - fine).max() < 0.1
    # conical slices and stepped tubes are two routes to the same converged answer
    steps = ac.insertion_gain(column, EAR, DIAL_CANAL, WIDE, settings=ac.UNIFIED.replace(flare_slices="cylinders", slice_count=3072))
    assert np.abs(fine - steps).max() < 0.01
    # the stepped-tube rule (what the profile door uses) holds the same tolerance
    by_rule = ac.insertion_gain(column, EAR, DIAL_CANAL, WIDE, settings=ac.UNIFIED.replace(flare_slices="cylinders"))
    assert np.abs(by_rule - steps).max() < 0.1


def test_profile_door_slicing_converges_and_agrees_with_the_dial_door():
    x = random_dials(120, seed=22)
    column = {k: v[:, None] for k, v in x.items()}
    dial = ac.insertion_gain(column, EAR, DIAL_CANAL, WIDE)
    for i in range(0, 120, 8):
        xi = {k: float(v[i]) for k, v in x.items()}
        design = ac.Design.from_dials(xi)
        canals = [ac.Canal.from_length(whole - xi["canal_stem_mm"]) for whole in WHOLE]
        got = ac.insertion_gain_db(design, canals, WIDE, ear_params=EAR)
        fine = ac.insertion_gain_db(design, canals, WIDE, ear_params=EAR, settings=ac.UNIFIED.replace(slice_step_mm=0.02))
        assert np.abs(got - fine).max() < 0.1, xi
        assert np.abs(got - dial[i]).max() < 0.1, xi


def test_results_do_not_depend_on_the_batch_or_on_the_other_frequencies():
    x = random_dials(40, seed=23)
    column = {k: v[:, None] for k, v in x.items()}
    together = ac.insertion_gain(column, EAR, DIAL_CANAL, WIDE)
    alone = ac.insertion_gain({k: v[7] for k, v in x.items()}, EAR, DIAL_CANAL, WIDE)
    assert np.array_equal(together[7], alone)
    few = ac.insertion_gain(column, EAR, DIAL_CANAL, WIDE[[10, 40]])
    assert np.allclose(few, together[..., [10, 40]], atol=1e-12)


def test_air_follows_the_temperature():
    warm = ac.Air.at(35.0)
    assert warm.c == pytest.approx(ac.C0, rel=2e-4) and warm.rho == pytest.approx(ac.RHO, rel=1e-3)
    assert warm.mu == pytest.approx(ac.MU, rel=5e-3)
    room = ac.Air.at(20.0)
    assert room.c == pytest.approx(343.2, abs=0.1) and room.rho == pytest.approx(1.204, abs=1e-3)
    # a colder ear canal resonates lower, by the ratio of the sound speeds
    f = np.linspace(1500, 5000, 3501)
    peak = lambda settings: f[np.abs(ac.open_ear(ac.Canal(0.7), f, settings=settings)).argmax()]
    assert peak(ac.UNIFIED.with_temperature(20.0)) / peak(ac.UNIFIED) == pytest.approx(room.c / ac.C0, abs=3e-3)
    with pytest.raises(ValueError):
        ac.Air.at(-300.0)


# ---------------------------------------------------------------- equivalence with the two original models

def band_means(curves_db):
    return np.array(golden.band_means(np.median(np.asarray(curves_db), 0)))


@pytest.mark.parametrize("name", list(GOLD["common"]))
def test_legacy_marc_sim_reproduces_marc_sim_on_the_common_designs(name):
    d = GOLD["common"][name]
    got = ac.insertion_gain(d["x"], EAR, DIAL_CANAL, F, settings=ac.LEGACY_MARC_SIM)
    assert got.shape == (3, len(F))
    assert np.abs(band_means(got) - band_means(d["marc_sim_insertion_gain_db"])).max() < 0.1
    assert np.abs(got - np.array(d["marc_sim_insertion_gain_db"])).max() < 1e-4       # in fact to rounding


@pytest.mark.parametrize("name", list(GOLD["common"]))
def test_legacy_main_reproduces_main_on_the_common_designs(name):
    d = GOLD["common"][name]
    got = ac.insertion_gain_db(profile_design(d), profile_canals(d["x"]["canal_stem_mm"]), F, settings=ac.LEGACY_MAIN)
    assert np.abs(got - np.array(d["main_insertion_gain_db"])).max() < 0.01
    assert np.abs(got - np.array(d["main_insertion_gain_db"])).max() < 1e-4            # in fact to rounding


def test_legacy_main_reproduces_main_in_its_own_parametrisation():
    canals = [ac.Canal(v) for v in GOLD["main_native"]["volumes_cc"]]
    db = lambda p: 20 * np.log10(np.abs(p))
    for name, design in golden.main_native_designs(ac.Design).items():
        want = GOLD["main_native"][name]
        st = ac.LEGACY_MAIN
        assert np.abs(ac.insertion_gain_db(design, canals, F, settings=st) - np.array(want["insertion_gain_db"])).max() < 1e-4
        aided = [db(ac.aided(design, c, F, settings=st)) for c in canals]
        opened = [db(ac.open_ear(c, F, design.tip_length_mm, settings=st)) for c in canals]
        assert np.abs(np.array(aided) - np.array(want["aided_db"])).max() < 1e-4
        assert np.abs(np.array(opened) - np.array(want["open_ear_db"])).max() < 1e-4


def test_legacy_marc_sim_reproduces_vents_damper_and_open_ear():
    want = GOLD["marc_sim_native"]
    st = ac.LEGACY_MARC_SIM
    assert np.abs(ac.insertion_gain(want["x"], EAR, DIAL_CANAL, F, settings=st) - np.array(want["insertion_gain_db"])).max() < 1e-4
    for theta in (0, 90):
        got = ac.open_ear_gain(EAR, DIAL_CANAL, F, theta_deg=theta, settings=st)
        assert np.abs(got - np.array(want[f"open_ear_gain_db_theta_{theta}"])).max() < 1e-4


@pytest.mark.parametrize("name", list(GOLD["common"]))
def test_unified_default_moves_main_only_where_the_radiation_formula_does(name):
    d = GOLD["common"][name]
    design, canals = profile_design(d), profile_canals(d["x"]["canal_stem_mm"])
    old = np.array(d["main_insertion_gain_db"])
    new = ac.insertion_gain_db(design, canals, F)
    radiation_only = ac.insertion_gain_db(design, canals, F, settings=ac.LEGACY_MAIN.replace(radiation="piston"))
    assert np.abs(new - radiation_only).max() < 0.02             # the rest is slicing, far below 0.1 dB
    assert np.abs(new - old)[:, F <= 1000].max() < 0.05          # nothing moves where the openings are small in wavelengths
    shift = band_means(new) - band_means(old)
    limit = {"alan_default": 0.05, "wide_in_concha": 0.3, "open_concha_short": 0.4, "protruding_collector": 1.8}[name]
    assert np.abs(shift).max() < limit                           # 450 mm2 mouth: +1.7 dB at 4-8 kHz; 22 mm2: -0.04 dB


def test_unified_default_moves_marc_sim_mostly_below_1_khz_for_sealed_designs():
    d = GOLD["common"]["wide_in_concha"]
    old = np.median(np.array(d["marc_sim_insertion_gain_db"]), 0)
    new = np.median(ac.insertion_gain(d["x"], EAR, DIAL_CANAL, F), 0)
    drum_only = np.median(ac.insertion_gain(d["x"], EAR, DIAL_CANAL, F, settings=ac.LEGACY_MARC_SIM.replace(eardrum="rcm")), 0)
    low = F <= 1500
    assert np.abs(new - old)[low].max() > 2.0                                  # the eardrum's compliance matters
    assert np.abs(drum_only - new)[low].max() < 0.5                            # and explains the change down there


# ---------------------------------------------------------------- the dial door: shapes and direction

def test_dial_door_shapes_and_broadcasting_match_marc_sim():
    n = 7
    x = {k: v[:, None] for k, v in random_dials(n, seed=3).items()}
    canal32 = {"length_mm": np.linspace(11.5, 20.2, 32)}
    assert ac.insertion_gain(x, EAR, canal32, WIDE).shape == (n, 32, len(WIDE))
    assert ac.insertion_gain(coil(), EAR, canal32, WIDE).shape == (32, len(WIDE))
    assert ac.insertion_gain(coil(), EAR, {"length_mm": 19.0}, [160, 250]).shape == (2,)
    one = {k: np.array([v]) for k, v in coil().items()}
    assert ac.insertion_gain(one, EAR, {"length_mm": np.array([19.0])}, WIDE).shape == (1, len(WIDE))
    assert ac.open_ear_gain(EAR, canal32, WIDE, theta_deg=90).shape == (32, len(WIDE))
    # a design with no vent broadcasts like any other, and vent keys may simply be left out
    sealed = earpiece(vent_count=np.zeros((n, 1)), vent_diameter_mm=0.8, vent_length_mm=0.0)
    got = ac.insertion_gain(sealed, EAR, canal32, WIDE)
    assert got.shape == (n, 32, len(WIDE)) and np.array_equal(got[0], ac.insertion_gain(earpiece(), EAR, canal32, WIDE))
    w = 2 * np.pi * WIDE
    assert ac._aid(x, EAR, canal32, w).shape == (n, 32, len(WIDE)) and np.iscomplexobj(ac._aid(x, EAR, canal32, w))
    assert ac.bore_radii(x).shape == (n, 1, 40) and ac.bore_radii(coil(), 12).shape == (12,)
    assert all(np.shape(m) == (len(WIDE),) for m in ac.horn(ac.bore_radii(coil()), 0.064, w))


def test_direction_cancels_in_insertion_gain_and_only_moves_the_open_ear():
    front = ac.insertion_gain(coil(), EAR, DIAL_CANAL, WIDE, theta_deg=0)
    side = ac.insertion_gain(coil(), EAR, DIAL_CANAL, WIDE, theta_deg=90)
    assert np.array_equal(front, side)
    lift = ac.open_ear_gain(EAR, DIAL_CANAL, WIDE, theta_deg=90) - ac.open_ear_gain(EAR, DIAL_CANAL, WIDE, theta_deg=0)
    # Brown & Duda's head: up to +6 dB facing the ear and about -2.4 dB from the front, nothing at low frequency
    assert lift[:, WIDE > 2000].min() > 6.0 and lift.max() < 8.5 and lift[:, 0].max() < 0.2


def test_bore_segments_override_is_honoured(monkeypatch):
    w = 2 * np.pi * WIDE
    auto = ac._aid(coil(mouth_mm2=150.0), EAR, DIAL_CANAL, w)
    monkeypatch.setattr(ac, "BORE_SEGMENTS", 160)
    forced = ac._aid(coil(mouth_mm2=150.0), EAR, DIAL_CANAL, w)
    assert not np.array_equal(auto, forced)
    assert np.abs(20 * np.log10(np.abs(forced / auto))).max() < 0.1
    assert ac.bore_radii(coil()).shape == (160,)


# ---------------------------------------------------------------- settings

def test_presets_and_settings_validation():
    assert ac.PRESETS["unified"] is ac.UNIFIED
    by_name = ac.insertion_gain(coil(), EAR, DIAL_CANAL, F, settings="legacy_marc_sim")
    assert np.array_equal(by_name, ac.insertion_gain(coil(), EAR, DIAL_CANAL, F, settings=ac.LEGACY_MARC_SIM))
    for bad in ({"eardrum": "drum"}, {"concha": "shell"}, {"radiation": "exact"}, {"wall_losses": "some"}, {"flare_slices": "wedges"},
                {"slice_count": 0}, {"slice_step_mm": -1.0}, {"canal_diameter_mm": 0.0}, {"slice_tol_db": 0.0}, {"canal_sample_tip_mm": -1.0}):
        with pytest.raises(ValueError):
            ac.Settings(**bad)
    with pytest.raises(ValueError):
        ac.insertion_gain(coil(), EAR, DIAL_CANAL, F, settings="marc")
    with pytest.raises(TypeError):
        ac.insertion_gain(coil(), EAR, DIAL_CANAL, F, settings={"radiation": "piston"})


def test_eardrum_models():
    canal = [ac.Canal(0.7)]
    design = ac.Design(*golden.exp_horn(51.0))
    default = ac.insertion_gain_db(design, canal, F)
    # a user-supplied impedance function equal to the built-in model gives the built-in answer
    same = ac.UNIFIED.replace(eardrum=lambda f: ac.eardrum_impedance(f))
    assert np.allclose(ac.insertion_gain_db(design, canal, F, settings=same), default, atol=1e-12)
    # the compliance is the air stiffness of the equivalent volume: 1 / (j w V / (rho c^2)) dominates at 20 Hz
    z = ac.eardrum_impedance([20.0])[0]
    assert -z.imag == pytest.approx(ac.RHO * ac.C0 ** 2 / (2 * np.pi * 20 * ac.EARDRUM_VEQ_CC * 1e-6), rel=1e-3)
    # the resistive eardrum is a multiple of rho c / canal area
    area = np.pi * 0.00375 ** 2
    z = ac.eardrum_impedance(F, settings=ac.UNIFIED.replace(eardrum="resistance"), canal_area_m2=area)
    assert np.allclose(z, 3.0 * ac.RHO * ac.C0 / area)
    stiff = ac.insertion_gain_db(design, canal, F, settings=ac.UNIFIED.replace(eardrum="resistance"))
    assert np.abs(stiff - default)[0, F < 300].min() > 1.0


def test_concha_models():
    canal = [ac.Canal(0.7)]
    s = np.linspace(0, 20, 50)
    filled, left_open = (ac.Design(s, np.full(50, 30.0), concha_fill=fill) for fill in (1.0, 0.0))
    # no ear geometry: the average resonance bump, which a shell removes
    bump = ac.insertion_gain_db(filled, canal, F)
    assert np.array_equal(bump, ac.insertion_gain_db(filled, canal, F, settings=ac.UNIFIED.replace(concha="bump")))
    difference = ac.insertion_gain_db(left_open, canal, F) - bump
    assert np.allclose(difference, ac.concha_gain_db(F), atol=1e-9)
    # with the patient's ear geometry the open ear is their own concha, and "none" drops the concha entirely
    tube = ac.insertion_gain_db(filled, canal, F, ear_params=EAR)
    assert np.abs(tube - bump).max() > 1.0
    none = ac.insertion_gain_db(filled, canal, F, settings=ac.UNIFIED.replace(concha="none"))
    assert np.allclose(none - bump, ac.concha_gain_db(F), atol=1e-9)
    with pytest.raises(ValueError, match="ear_params"):
        ac.insertion_gain_db(filled, canal, F, settings=ac.UNIFIED.replace(concha="tube"))
    with pytest.raises(ValueError, match="concha_fill"):
        ac.insertion_gain_db(left_open, canal, F, ear_params=EAR)             # the tube model cannot leave the concha open
    # the dial door can use the bump model too, and then takes concha_fill
    st = ac.UNIFIED.replace(concha="bump")
    gain = ac.insertion_gain(earpiece(concha_fill=0.0), EAR, DIAL_CANAL, F, settings=st) - ac.insertion_gain(earpiece(), EAR, DIAL_CANAL, F, settings=st)
    assert np.allclose(gain, ac.concha_gain_db(F), atol=1e-9)


def test_canal_diameter_and_tip_conventions():
    design = ac.Design(*golden.exp_horn(51.0), tip_length_mm=9.0)
    # canal diameter override: a 0.7 cc residual is shorter in a wider canal
    narrow = ac.insertion_gain_db(design, [ac.Canal(0.7, 7.5)], F, settings=ac.UNIFIED.replace(canal_diameter_mm=9.0))
    assert np.allclose(narrow, ac.insertion_gain_db(design, [ac.Canal(0.7, 9.0)], F), atol=1e-12)
    # whole-canal convention: sample + 6 mm is the patient's canal, so a 9 mm tip leaves 3 mm less behind it
    whole = ac.UNIFIED.replace(canal_sample_tip_mm=6.0)
    sample = ac.Canal.from_length(15.0)
    got = ac.aided(design, sample, F, settings=whole)
    assert np.allclose(got, ac.aided(design, ac.Canal.from_length(12.0), F), atol=1e-12)
    assert np.allclose(ac.open_ear(sample, F, 9.0, settings=whole), ac.open_ear(ac.Canal.from_length(21.0), F, 0.0), atol=1e-12)
    # the dial door reads its tip from the module constant unless the settings say otherwise
    shifted = ac.insertion_gain(coil(), EAR, {"length_mm": 15.0}, F, settings=ac.UNIFIED.replace(canal_sample_tip_mm=9.0))
    assert np.allclose(shifted, ac.insertion_gain(coil(), EAR, {"length_mm": 18.0}, F), atol=1e-12)


# ---------------------------------------------------------------- vents and dampers

def test_no_vent_one_vent_and_several_vents():
    sealed = ac.insertion_gain(coil(vent_count=0), EAR, DIAL_CANAL, F)
    # zero count, zero diameter and no vent keys at all are the same sealed design (marc-sim returned NaN for the second)
    for same in (coil(vent_count=0, vent_diameter_mm=0.0), coil(vent_diameter_mm=0.0), coil(vent_length_mm=0.0),
                 {k: v for k, v in coil().items() if not k.startswith("vent")}):
        got = ac.insertion_gain(same, EAR, DIAL_CANAL, F)
        assert np.isfinite(got).all() and np.array_equal(got, sealed)
    assert np.isfinite(ac.insertion_gain(coil(vent_count=0, vent_diameter_mm=0.0), EAR, DIAL_CANAL, F, settings=ac.LEGACY_MARC_SIM)).all()
    # two vents of radius a pass what one vent of twice the admittance would: more low-frequency leak than one
    low = F < 300
    one, two, four = (ac.insertion_gain(coil(vent_count=n, vent_diameter_mm=1.5), EAR, DIAL_CANAL, F)[1] for n in (1, 2, 4))
    mid = (F > 300) & (F < 1500)
    assert np.abs(one - sealed[1])[mid].max() > 1.0
    assert np.abs(two)[low].mean() < np.abs(one)[low].mean() and np.abs(four)[low].mean() < np.abs(two)[low].mean()
    # a mixed batch: each row is what it would be alone
    counts = np.array([0.0, 1.0, 2.0])[:, None]
    batch = ac.insertion_gain(coil(vent_count=counts, vent_diameter_mm=1.5), EAR, DIAL_CANAL, F)
    assert np.allclose(batch[:, 1], [ac.insertion_gain(coil(vent_count=0), EAR, DIAL_CANAL, F)[1], one, two], atol=1e-12)
    # the profile door has the same vents
    s, area = golden.exp_horn(51.0)
    profile = [ac.insertion_gain_db(ac.Design(s, area, vent_diameter_mm=1.5, vent_length_mm=12.0, vent_count=n), [ac.Canal(0.7)], F)[0] for n in (0, 1, 2)]
    assert np.array_equal(profile[0], ac.insertion_gain_db(ac.Design(s, area), [ac.Canal(0.7)], F)[0])
    assert np.abs(profile[2])[low].mean() < np.abs(profile[1])[low].mean()
    assert ac.Design.from_design_json({"acoustic": {"s_mm": s.tolist(), "area_mm2": area.tolist(), "vent_diameter_mm": 1.5,
                                                    "vent_length_mm": 12.0, "vent_count": 2}}).vent_count == 2


def test_damper_takes_the_edge_off_a_resonance():
    x = earpiece(throat_mm2=12.0, length_mm=30.0)
    bare = ac.insertion_gain(x, EAR, DIAL_CANAL, WIDE)[1]
    damped = ac.insertion_gain(x | {"damper_pos": 0.0, "damper_ohm": 680.0}, EAR, DIAL_CANAL, WIDE)[1]
    assert np.array_equal(ac.insertion_gain(x | {"damper_pos": 0.3, "damper_ohm": 0.0}, EAR, DIAL_CANAL, WIDE)[1], bare) is False
    assert np.allclose(ac.insertion_gain(x | {"damper_pos": 0.3, "damper_ohm": 0.0}, EAR, DIAL_CANAL, WIDE)[1], bare, atol=0.05)
    assert damped.max() < bare.max() - 1.0                       # the peak comes down
    # at the lowest frequencies the sealed canal is too stiff for any air to move, and the damper does nothing
    slow = [ac.insertion_gain(d, EAR, DIAL_CANAL, [5.0]) for d in (x, x | {"damper_pos": 0.0, "damper_ohm": 680.0})]
    assert np.abs(slow[1] - slow[0]).max() < 0.05
    # 680 cgs ohms is 6.8e7 Pa s/m^3: at the throat it adds to the bore's source impedance
    w = 2 * np.pi * WIDE
    a0, b0, c0, d0 = ac._flare(x, w, ac.UNIFIED)
    a1, b1, c1, d1 = ac._flare(x | {"damper_pos": 0.0, "damper_ohm": 680.0}, w, ac.UNIFIED)
    assert np.allclose(b1, a0 * 680 * ac.OHM_CGS + b0, rtol=1e-9) and np.allclose(a1, a0, rtol=1e-12)


def test_damper_position_is_exact_and_several_dampers_add():
    x = earpiece(throat_mm2=12.0, length_mm=30.0)
    w = 2 * np.pi * WIDE
    fine = ac.UNIFIED.replace(slice_count=384)
    for pos in (0.137, 0.5, 0.86):
        rule = ac._flare(x | {"damper_pos": pos, "damper_ohm": 1500.0}, w, ac.UNIFIED)
        ref = ac._flare(x | {"damper_pos": pos, "damper_ohm": 1500.0}, w, fine)
        assert max(np.abs(m / n - 1).max() for m, n in zip(rule, ref)) < 5e-3, pos     # no snapping to a coarse grid
    # two dampers at one place are one damper of the summed resistance; the list form and the pair form agree
    both = ac.insertion_gain(x | {"dampers": [(0.4, 1000.0), (0.4, 500.0)]}, EAR, DIAL_CANAL, WIDE)
    assert np.allclose(both, ac.insertion_gain(x | {"damper_pos": 0.4, "damper_ohm": 1500.0}, EAR, DIAL_CANAL, WIDE), atol=1e-9)
    two = ac.insertion_gain(x | {"dampers": [(0.8, 1000.0), (0.2, 2200.0)]}, EAR, DIAL_CANAL, WIDE)
    mixed = ac.insertion_gain(x | {"dampers": [(0.2, 2200.0)], "damper_pos": 0.8, "damper_ohm": 1000.0}, EAR, DIAL_CANAL, WIDE)
    assert np.allclose(two, mixed, atol=1e-9) and two.max() < both.max() + 3
    # dampers broadcast over a batch like any other dial
    pos = np.array([0.2, 0.5, 0.8])[:, None]
    batch = ac.insertion_gain(x | {"damper_pos": pos, "damper_ohm": 1500.0}, EAR, DIAL_CANAL, WIDE)
    assert batch.shape == (3, 3, len(WIDE))
    assert np.allclose(batch[1], ac.insertion_gain(x | {"damper_pos": 0.5, "damper_ohm": 1500.0}, EAR, DIAL_CANAL, WIDE), atol=1e-12)
    # the profile door places dampers by position in mm from the mouth, and matches the dial door
    design = ac.Design.from_dials(x | {"dampers": [(0.8, 1000.0), (0.2, 2200.0)]})
    assert sorted(design.dampers) == [(pytest.approx(6.0), 1000.0), (pytest.approx(24.0), 2200.0)]
    canals = [ac.Canal.from_length(whole - x["canal_stem_mm"]) for whole in WHOLE]
    assert np.abs(ac.insertion_gain_db(design, canals, WIDE, ear_params=EAR) - two).max() < 0.1
    p, edges = ac.pressure_along_bore(design, canals[1], F[::8], ear_params=EAR)
    assert p.shape == (len(edges), len(F[::8])) and np.isfinite(p).all()
    assert any(np.isclose(edges, 6.0)) and any(np.isclose(edges, 24.0))       # an edge sits on each damper


# ---------------------------------------------------------------- bad input

def test_dial_door_rejects_bad_input():
    bad = [
        (coil(canal_stem_mm=40.0), "longer than the canal"),
        (coil(mouth_mm2=0.5), "smaller than throat"),
        (coil(length_mm=-1.0), "length_mm must not be negative"),
        (coil(canal_stem_mm=-1.0), "canal_stem_mm must not be negative"),
        (coil(vent_length_mm=-2.0), "vent_length_mm must not be negative"),
        (coil(vent_diameter_mm=-0.8), "vent_diameter_mm must not be negative"),
        (coil(vent_count=-1), "vent_count must not be negative"),
        (coil(throat_mm2=0.0), "throat_mm2 must be positive"),
        (coil(mouth_mm2=-3.0), "mouth_mm2 must be positive"),
        (coil(throat_mm2=float("nan")), "throat_mm2 must be positive"),
        (coil(flare_mid1=-2.0), "radius"),
        (coil(damper_pos=1.5, damper_ohm=100.0), "damper_pos"),
        (coil(damper_pos=0.5, damper_ohm=-100.0), "damper_ohm"),
        ({k: v for k, v in coil().items() if k != "length_mm"}, "missing 'length_mm'"),
    ]
    for x, message in bad:
        with pytest.raises(ValueError, match=message):
            ac.insertion_gain(x, EAR, DIAL_CANAL, F)
    # one bad design in a batch is enough
    with pytest.raises(ValueError, match="longer than the canal"):
        ac.insertion_gain(coil(canal_stem_mm=np.array([5.0, 30.0])[:, None]), EAR, DIAL_CANAL, F)
    with pytest.raises(ValueError, match="frequencies must be positive"):
        ac.insertion_gain(coil(), EAR, DIAL_CANAL, [0.0, 100.0])
    with pytest.raises(ValueError, match="canal_diameter_mm"):
        ac.insertion_gain(coil(), EAR | {"canal_diameter_mm": 0.0}, DIAL_CANAL, F)
    with pytest.raises(ValueError, match="negative length"):
        ac.open_ear_gain(EAR, {"length_mm": -10.0}, F)
    # the edges of the allowed range still work: a straight tube, a stem as long as the canal
    assert np.isfinite(ac.insertion_gain(coil(mouth_mm2=1.0), EAR, DIAL_CANAL, F)).all()
    assert np.isfinite(ac.insertion_gain(coil(canal_stem_mm=WHOLE.min()), EAR, DIAL_CANAL, F)).all()
    assert np.isfinite(ac.insertion_gain(coil(length_mm=0.0), EAR, DIAL_CANAL, F)).all()


def test_profile_door_rejects_bad_input():
    s, area = golden.exp_horn(51.0)
    canal = [ac.Canal(0.7)]
    bad = [
        (ac.Design(s[::-1], area), "negative length"),
        (ac.Design(s, np.where(s > 25, 0.0, area)), "area_mm2 must be positive"),
        (ac.Design(s, -area), "area_mm2 must be positive"),
        (ac.Design(s, area[:-1]), "same length"),
        (ac.Design(s, area, vent_diameter_mm=-1.0, vent_length_mm=10.0), "vent_diameter_mm"),
        (ac.Design(s, area, vent_diameter_mm=1.0, vent_length_mm=-10.0), "vent_length_mm"),
        (ac.Design(s, area, vent_count=-1), "vent_count"),
        (ac.Design(s, area, tip_length_mm=-1.0), "tip_length_mm"),
        (ac.Design(s, area, concha_fill=1.5), "concha_fill"),
        (ac.Design(s, area, dampers=[(80.0, 1000.0)]), "outside the bore"),
        (ac.Design(s, area, dampers=[(20.0, -5.0)]), "damper resistance"),
    ]
    for design, message in bad:
        with pytest.raises(ValueError, match=message):
            ac.insertion_gain_db(design, canal, F)
    with pytest.raises(ValueError, match="volume_cc"):
        ac.insertion_gain_db(ac.Design(s, area), [ac.Canal(-0.1)], F)
    with pytest.raises(ValueError, match="diameter_mm"):
        ac.open_ear(ac.Canal(0.7, 0.0), F)
    with pytest.raises(ValueError, match="longer than the canal"):       # whole-canal convention: a 9 mm tip in a 7 mm canal
        ac.aided(ac.Design(s, area), ac.Canal.from_length(1.0), F, settings=ac.UNIFIED.replace(canal_sample_tip_mm=6.0))
    with pytest.raises(ValueError, match="radius must be positive"):
        ac.tube_abcd(0.0, 0.01, F)
    with pytest.raises(ValueError, match="length must not be negative"):
        ac.tube_abcd(0.001, -0.01, F)
    assert ac.insertion_gain_db(ac.Design(s, area), [], F).shape == (0, len(F))
