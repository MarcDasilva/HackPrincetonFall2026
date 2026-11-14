"""Intelligibility scoring with HASPI v2 (Kates & Arehart 2021) from pyclarity.

Convention: the clean reference is normalised to RMS 1 and always stands for 65 dB SPL, the
level HASPI's ear model expects its normal-hearing reference at (pyclarity `ear_model`:
"reference signal: should be adjusted to 65 dB SPL"). The presentation level moves only
what the listener hears: it is scaled by (L - 65) dB. Presenting the reference at L as well
hides the audibility loss at soft levels: unaided HASPI then stays flat or even rises as
speech gets quieter. Gains are applied to the reference (or the noisy mixture), never to
the HASPI reference itself.
"""
import numpy as np
from clarity.evaluator.haspi import haspi_v2
from clarity.utils.audiogram import Audiogram

from .audio import apply_gain

HASPI_FREQS = np.array([250, 500, 1000, 2000, 4000, 6000])
REFERENCE_DB_SPL = 65.0     # what RMS 1 means to HASPI


def audiogram(levels_by_freq: dict) -> Audiogram:
    pairs = sorted((float(k), float(v)) for k, v in levels_by_freq.items())   # JSON keys arrive as strings
    return Audiogram(levels=np.array([v for _, v in pairs]), frequencies=np.array([k for k, _ in pairs]))


def haspi(reference, processed, fs, ag: Audiogram, level_db, seed=0):
    np.random.seed(seed)  # HASPI adds random noise internally; fix it so scores repeat
    heard = np.asarray(processed) * 10 ** ((level_db - REFERENCE_DB_SPL) / 20)
    score, _ = haspi_v2(reference, fs, heard, fs, ag, level1=REFERENCE_DB_SPL)
    return float(score)


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
