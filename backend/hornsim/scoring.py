"""Hearing model: SII (ANSI S3.5-1997), HASPI v2 and HASQI v2 (Kates & Arehart, pyclarity), and a
display-only auditory-nerve neurogram (Zilany, Bruce & Carney 2014, via the `cochlea` package).

Level convention, ONE for every score: a signal with RMS 1 is `level_db` dB SPL in the free field at
the listener's head position, talker in front. pyclarity documents HASPI/HASQI `level1` as exactly
this scale ("level in dB SPL that corresponds to a signal RMS = 1", haspi.py / hasqi.py / eb.py);
Kates' ear model then applies only a middle-ear filter (2-pole HP 350 Hz, 1-pole LP 5 kHz, "a rough
approximation to the equal-loudness contour at threshold") and NO ear-canal or concha gain. SII's
speech and noise levels are free-field levels with the listener absent (ANSI S3.5). So dB HL already
contains the normal open ear's boost — apply ONLY insertion gain or a direction filter normalised to
frontal incidence before scoring, never the raw eardrum pressure (spec 04). Gains go on the
processed signal (the clip or the noisy mixture), never on the HASPI/HASQI reference.

Calibration check (test_hearing.py, Kates ear model, 1 kHz tone, 0 dB SL = threshold):
    healthy ear, tone at 2.4 dB SPL (ISO 389-7 free-field threshold)   -> +5.1 dB SL
    impaired ear (30 dB HL), tone at 32.4 dB SPL                       -> +5.3 dB SL
The hearing loss maps 1:1 onto the model; its absolute threshold is ~0 dB SPL at every frequency
(eb.env_compress_basilar_membrane assumes it), so against ISO 389-7 it is 5-6 dB too sensitive at
0.5-1 kHz, right at 2 kHz, and 5.6-6.6 dB too deaf at 3.15-4 kHz. Reading `level1` as eardrum
pressure instead would make it 7-12 dB too sensitive across 1-4 kHz, so free field is the
better-fitting convention. Both ears share the offset: rankings hold, absolute audibility of
soft high-frequency sound is off by up to ~6 dB.
"""
import os

import numpy as np
from clarity.evaluator.haspi import haspi_v2
from clarity.evaluator.hasqi import hasqi_v2
from clarity.utils.audiogram import Audiogram
from scipy.interpolate import interp1d
from scipy.signal import resample_poly

from .audio import apply_gain

HASPI_FREQS = np.array([250, 500, 1000, 2000, 4000, 6000])

# ANSI S3.5-1997 Table 3, one-third-octave band procedure: band centres, band importance (the
# standard's "average speech" SII function), reference internal noise spectrum level X_i, and the
# standard speech spectrum level at normal vocal effort U_i. Cross-checked value by value against
# the R `SII` package's `onethird` table (CRAN SII, data/onethird.rda).
SII_FREQS = np.array([160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000,
                      5000, 6300, 8000], float)
SII_IMPORTANCE = np.array([0.0083, 0.0095, 0.0150, 0.0289, 0.0440, 0.0578, 0.0653, 0.0711, 0.0818, 0.0844,
                           0.0882, 0.0898, 0.0868, 0.0844, 0.0771, 0.0527, 0.0364, 0.0185])
SII_X = np.array([0.6, -1.7, -3.9, -6.1, -8.2, -9.7, -10.8, -11.9, -12.5, -13.5, -15.4, -17.7, -21.2, -24.2,
                  -25.9, -23.6, -15.8, -7.1])
SII_U = np.array([32.41, 34.48, 34.75, 33.98, 34.59, 34.27, 32.06, 28.30, 25.01, 23.00, 20.15, 17.32, 13.18,
                  11.55, 9.33, 5.31, 2.59, 1.13])
_EDGES = SII_FREQS[:, None] * 2.0 ** np.array([-1 / 6, 1 / 6])

# Zilany/Bruce model thresholds vs hair-cell factors, human BM tuning of Shera et al. (2002): the table
# fitaudiogram2.m loads (THRESHOLD_ALL_HM_Shera.mat, BEZ2018a release, ece.mcmaster.ca/~ibruce/zbcANmodel).
ZILANY_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zilany_thresholds_hm_shera.npz")
# Fibres per CF in a healthy nerve, low/medium/high spontaneous rate (generate_neurogram_BEZ2018a.m).
FIBRES = {"lsr": 10, "msr": 10, "hsr": 30}


def audiogram(levels_by_freq: dict) -> Audiogram:
    f = np.array(sorted(levels_by_freq), float)
    return Audiogram(levels=np.array([levels_by_freq[k] for k in sorted(levels_by_freq)], float), frequencies=f)


def haspi(reference, processed, fs, ag: Audiogram, level_db, seed=0):
    np.random.seed(seed)  # HASPI adds random noise internally; fix it so scores repeat
    score, _ = haspi_v2(reference, fs, processed, fs, ag, level1=level_db)
    return float(score)


def hasqi(reference, processed, fs, ag: Audiogram, level_db, seed=0):
    np.random.seed(seed)  # SAME reason as haspi()
    score, _, _, _ = hasqi_v2(reference, fs, processed, fs, ag, level1=level_db)
    return float(score)


def _band_spectrum_levels(x, fs, level_db):
    """One-third-octave band spectrum levels (dB SPL per Hz) of x, with RMS 1 = level_db."""
    p = np.abs(np.fft.rfft(x)) ** 2 * (2 / len(x) ** 2)        # one-sided: sums to mean(x**2)
    f = np.fft.rfftfreq(len(x), 1 / fs)
    band = np.array([p[(f >= a) & (f < b)].sum() for a, b in _EDGES])
    with np.errstate(divide="ignore"):
        return level_db + 10 * np.log10(band) - 10 * np.log10(_EDGES[:, 1] - _EDGES[:, 0])


def _sii_terms(speech, noise, fs, ag, level_db):
    """ANSI S3.5-1997 one-third-octave procedure (sections 4.3-4.8). Returns (E'-D clipped to the
    standard's 30 dB range, level distortion factor L)."""
    E = _band_spectrum_levels(speech, fs, level_db)
    N = np.full(len(E), -np.inf) if noise is None else _band_spectrum_levels(noise, fs, level_db)
    B = np.maximum(N, E - 24)                                    # self-speech masking V = E' - 24
    C = -80 + 0.6 * (B + 10 * np.log10(SII_FREQS) - 6.353)       # upward-spread slope per octave
    Z = B.copy()
    with np.errstate(divide="ignore"):
        for i in range(1, len(E)):
            spread = B[:i] + 3.32 * C[:i] * np.log10(0.89 * SII_FREQS[i] / SII_FREQS[:i])
            Z[i] = 10 * np.log10(10 ** (0.1 * N[i]) + np.sum(10 ** (0.1 * spread)))
    D = np.maximum(Z, SII_X + hearing_level(ag, SII_FREQS))
    L = np.clip(1 - (E - SII_U - 10) / 160, 0, 1)
    return np.clip(E - D, -15, 15), L


def hearing_level(ag: Audiogram, freqs):
    """dB HL at freqs, linear on log frequency, held flat beyond the audiogram's ends."""
    return np.interp(np.log(freqs), np.log(ag.frequencies), ag.levels)


def band_audibility(speech, noise, fs, ag: Audiogram, level_db):
    """Speech above the masking/threshold floor per SII band, dB, in SII's range -15 (nothing
    audible) to +15 (fully audible). Speech and noise share ONE level scale (RMS 1 = level_db)."""
    return _sii_terms(speech, noise, fs, ag, level_db)[0]


def sii(speech, noise, fs, ag: Audiogram, level_db):
    aud, L = _sii_terms(speech, noise, fs, ag, level_db)
    return float(np.sum(SII_IMPORTANCE * L * (aud + 15) / 30))


def hair_cells(ag: Audiogram, cfs_hz):
    """(cohc, cihc) per CF for the Zilany 2014 model: a port of fitaudiogram2.m (Zilany & Bruce, 2013).
    2/3 of each threshold shift goes to the outer hair cells, the rest to the inner hair cells
    (Bruce et al. 2003; Zilany & Bruce 2007; Plack et al. 2004)."""
    t = np.load(ZILANY_TABLE)
    CF, CIHC, COHC = t["cf_hz"], t["cihc"], t["cohc"]
    shift = t["thr_db_spl"] - t["thr_db_spl"][:, :1, :1]         # (CF, CIHC, COHC)
    # generate_neurogram_BEZ2018a.m interpolates the audiogram linearly in Hz and extrapolates
    loss = np.maximum(interp1d(ag.frequencies, ag.levels, fill_value="extrapolate")(cfs_hz), 0)
    cohc, cihc = np.zeros(len(loss)), np.zeros(len(loss))
    for m, (f, db) in enumerate(zip(cfs_hz, loss)):
        n = np.argmin(np.abs(CF - f))
        ohc = shift[n, 0, :]
        j = len(COHC) - 1 if 2 / 3 * db > ohc[-1] else np.argmin(np.abs(ohc - 2 / 3 * db))
        cohc[m] = COHC[j]
        ihc = shift[n, :, j]
        cihc[m] = 0.0 if db > ihc[-1] else CIHC[np.argmin(np.abs(ihc - db))]
    return cohc, cihc


def neurogram(x, fs, cohc, cihc, level_db, cfs_hz):
    """Mean-rate neurogram (CF, time), spikes/s per fibre, 6.4 ms frames. DISPLAY ONLY: tens of seconds
    per clip. Expected rates (no spike draws), so it repeats exactly; smoothing follows
    generate_neurogram_BEZ2018a.m (100 us bins, 128-bin Hamming window, 50% overlap)."""
    import cochlea  # optional: needs a patched build on macOS (see runner.py), absent on most servers
    fs_an = 100_000
    p = resample_poly(x, fs_an, int(fs)) * 20e-6 * 10 ** (level_db / 20)   # Pa, RMS 1 = level_db
    win = np.hamming(128)
    rows = []
    for cf, co, ci in zip(cfs_hz, cohc, cihc):
        r = cochlea.run_zilany2014_rate(p, fs_an, anf_types=list(FIBRES), cf=float(cf), species="human",
                                        cohc=float(co), cihc=float(ci))
        rate = sum(n * r[(k, float(cf))].to_numpy() for k, n in FIBRES.items()) / sum(FIBRES.values())
        rate = rate[: len(rate) // 10 * 10].reshape(-1, 10).mean(1)          # 100 us bins
        rows.append(np.convolve(rate, win / win.sum(), "same")[::64])
    return np.array(rows)


def prescription_gain(name, ag: Audiogram):
    """Linear prescriptions used as the 'ideal linear aid' ceiling. Returns (freqs, gain_db)."""
    hl = ag.resample(HASPI_FREQS).levels
    if name == "nal_r":  # Byrne & Dillon (1986), same formula as pyclarity's NALR
        bias = np.array([-17, -8, 1, -1, -2, -2])
        crit = hl[1] + hl[2] + hl[3]
        x = 0.05 * crit if crit <= 180 else 9.0 + 0.116 * (crit - 180)
        g = np.clip(x + 0.31 * hl + bias, 0, None)
    elif name == "half_gain":
        g = 0.5 * hl
    elif name == "full_gain":
        g = hl.astype(float)
    else:
        raise ValueError(name)
    return HASPI_FREQS.astype(float), g


def score_gain(clip, fs, ag, level_db, freqs, gain_db, seed=0):
    """HASPI for one clip with a given frequency response applied (unaided = 0 dB)."""
    processed = apply_gain(clip["input"], fs, freqs, gain_db)
    return haspi(clip["reference"], processed, fs, ag, level_db, seed)
