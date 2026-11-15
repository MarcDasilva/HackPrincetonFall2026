"""Scene scoring from band levels: a Python port of frontend app/sim/lib/hearing.ts, so the backend can
optimise earpieces against the same numbers the scene grid shows. Kept term for term with the TS;
test_scene_score.py checks a few cases against values computed by it.

Per scene and ear: each TARGET source (speech, music, an alarm...) against the MASKERS (everything
else), as band spectrum levels shifted by that source's direction filter (eardrum response over the
open frontal one). Speech targets: ANSI S3.5 SII terms and importance. Other targets: the same
audibility terms, importance = square root of the sound's own band energy share (an audibility index).
"""
import numpy as np

from .scoring import SII_FREQS, SII_IMPORTANCE, SII_U, SII_X

NB = len(SII_FREQS)
BW = SII_FREQS * (2 ** (1 / 6) - 2 ** (-1 / 6))
U_OVERALL = 10 * np.log10(np.sum(10 ** (SII_U / 10) * BW))
SPEECH = {"talker", "babble"}
TARGET_DEFAULT = {"talker": True, "babble": False, "music": False, "traffic": False, "alarm": True, "birds": True}
_F = SII_FREQS.astype(float)
SHAPES = {
    "music": -4.5 * np.log2(_F / 160) + np.where(_F <= 160, 4, np.where(_F <= 200, 2, np.where(_F <= 250, 1, 0))),
    "traffic": np.where(_F < 315, 0, -6 * np.log2(_F / 315)) + np.where((_F >= 800) & (_F <= 1250), 3, 0),
    "alarm": np.where(_F == 3150, 0, np.where(_F == 6300, -12, np.where((_F == 2500) | (_F == 4000), -18, -45))).astype(float),
    "birds": -10 * np.log2(_F / 4500) ** 2,
}


def hearing_level(ag, freqs=SII_FREQS):
    """dB HL at freqs from {Hz: dB HL}, linear in log f, flat beyond the ends (lib/hearing.ts)."""
    f = np.array(sorted(float(k) for k in ag))
    v = np.array([float(ag[k] if k in ag else ag[str(int(k))] if str(int(k)) in ag else ag[int(k)]) for k in f])
    return np.interp(np.log(np.asarray(freqs, float)), np.log(f), v)


def source_bands(role, level_db, gain_db):
    if role in SPEECH:
        return SII_U + level_db - U_OVERALL + gain_db
    shape = SHAPES[role]
    overall = 10 * np.log10(np.sum(10 ** (shape / 10) * BW))
    return shape + level_db - overall + gain_db


def power_sum(levels):
    return 10 * np.log10(np.sum(10 ** (np.asarray(levels) / 10), axis=0))


def sii_terms(E, N, hl):
    Nn = np.full(NB, -np.inf) if N is None else N
    B = np.maximum(Nn, E - 24)
    Cs = -80 + 0.6 * (B + 10 * np.log10(SII_FREQS) - 6.353)
    Z = B.copy()
    for i in range(1, NB):
        s = 10 ** (0.1 * Nn[i]) if np.isfinite(Nn[i]) else 0.0
        for k in range(i):
            s += 10 ** (0.1 * (B[k] + 3.32 * Cs[k] * np.log10(0.89 * SII_FREQS[i] / SII_FREQS[k])))
        Z[i] = 10 * np.log10(s)
    D = np.maximum(Z, SII_X + hl)
    L = np.clip(1 - (E - SII_U - 10) / 160, 0, 1)
    aud = np.clip(E - D, -15, 15)
    return aud, L


def importance_for(role, bands):
    if role in SPEECH:
        return SII_IMPORTANCE
    share = np.sqrt(10 ** (bands / 10) * BW)
    return share / (share.sum() or 1)


def aud_index(E, N, hl, imp, speech):
    aud, L = sii_terms(E, N, hl)
    return float(np.sum(imp * (L if speech else 1) * (aud + 15) / 30))


def is_target(src):
    return src.get("target", TARGET_DEFAULT[src["role"]])


def scene_index(sources, gains, ag):
    """Mean index over the scene's targets for this ear. sources: [{role, level_db, target}], gains: per
    source the band gain (dB) of its direction for this ear. None if the scene has no target."""
    hl = hearing_level(ag)
    tg = [i for i, s in enumerate(sources) if is_target(s)]
    mk = [i for i, s in enumerate(sources) if not is_target(s)]
    if not tg:
        return None
    N = power_sum([source_bands(sources[i]["role"], sources[i]["level_db"], gains[i]) for i in mk]) if mk else None
    vals = []
    for i in tg:
        E = source_bands(sources[i]["role"], sources[i]["level_db"], gains[i])
        vals.append(aud_index(E, N, hl, importance_for(sources[i]["role"], E), sources[i]["role"] in SPEECH))
    return float(np.mean(vals))
