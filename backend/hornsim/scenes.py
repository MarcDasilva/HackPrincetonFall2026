"""Listening scenes for one patient (spec 05): 8 conditions x 3 clips x 4 canals = 96.

    python -m hornsim.scenes <patient_dir>          writes <patient_dir>/scenes/scenes.json

Azimuth: 0 front, 90 aided side, 180 behind, 270 far side. Levels are dB SPL of the talker in the
free field at the head, RMS 1 = level_db (scoring.py's convention).
"""
import json
import os
import sys

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
SPEECH = os.path.join(HERE, "..", "assets", "speech")
# Every condition uses the three clean Harvard sentences; C6/C7 put them over the babble noise. The
# single babble talker clip cannot fill three clip slots.
CLIPS = ["clean_1", "clean_2", "clean_3"]
BABBLE = "babble_1_noise"
CONDITIONS = [  # spec 05's table
    {"condition": "C1", "name": "Soft speech", "level_db": 50, "talker_deg": 0, "noise": None},
    {"condition": "C2", "name": "Conversation", "level_db": 65, "talker_deg": 0, "noise": None},
    {"condition": "C3", "name": "Talker on aided side", "level_db": 65, "talker_deg": 90, "noise": None},
    {"condition": "C4", "name": "Talker on far side", "level_db": 65, "talker_deg": 270, "noise": None},
    {"condition": "C5", "name": "Echoey room", "level_db": 65, "talker_deg": 0,
     "noise": {"type": "reverb", "rt60_s": 0.6, "seed": 0, "synthetic": True}},
    {"condition": "C6", "name": "Restaurant", "level_db": 65, "talker_deg": 0,
     "noise": {"type": "babble", "deg": 0, "snr_db": 5}},
    {"condition": "C7", "name": "Noise on aided side", "level_db": 65, "talker_deg": 0,
     "noise": {"type": "babble", "deg": 90, "snr_db": 5}},
    {"condition": "C8", "name": "Loud speech", "level_db": 80, "talker_deg": 0, "noise": None},
]


def condition_weights(priorities=None):
    """Spec 05's PROPOSED rule, not yet confirmed: equal weights without priorities; otherwise ranks
    1-5 share 90% in proportion 5:4:3:2:1 and the unranked conditions share a 10% floor."""
    ids = [c["condition"] for c in CONDITIONS]
    ranked = [p for p in (priorities or [])[:5] if p in ids]
    if not ranked:
        return {i: 1 / len(ids) for i in ids}
    share = [5 - r for r in range(len(ranked))]
    rest = [i for i in ids if i not in ranked]
    w = {i: 0.9 * s / sum(share) for i, s in zip(ranked, share)}
    return w | {i: 0.1 / len(rest) for i in rest}


def load_request(patient_dir):
    p = os.path.join(patient_dir, "request.json")
    return json.load(open(p)) if os.path.exists(p) else json.load(open(os.path.join(patient_dir, "job.json")))["request"]


def build(patient_dir):
    canals = json.load(open(os.path.join(patient_dir, "context", "canals.json")))["canals"]
    canals = sorted(canals, key=lambda c: c["volume_cc"])
    picks = [canals[(2 * k + 1) * len(canals) // 8] for k in range(4)]   # the middle of each quartile
    w = condition_weights(load_request(patient_dir).get("priorities"))
    per = len(CLIPS) * len(picks)
    return [c | {"id": f"{c['condition']}_{clip}_canal{k['id']:02d}", "clip": clip, "canal": k,
                 "weight": w[c["condition"]] / per}
            for c in CONDITIONS for clip in CLIPS for k in picks]


def clip(name):
    x, _ = sf.read(os.path.join(SPEECH, name + ".wav"))
    return x


def reverb_ir(fs, rt60_s, seed):
    """Synthetic room: Gaussian noise decaying 60 dB over rt60_s, unit energy so the level is unchanged."""
    t = np.arange(int(rt60_s * fs)) / fs
    h = np.random.default_rng(seed).standard_normal(len(t)) * 10 ** (-3 * t / rt60_s)
    return h / np.sqrt(np.sum(h ** 2))


if __name__ == "__main__":
    out = os.path.join(sys.argv[1], "scenes")
    os.makedirs(out, exist_ok=True)
    s = build(sys.argv[1])
    json.dump(s, open(os.path.join(out, "scenes.json"), "w"), indent=1)
    print(f"{len(s)} scenes, weights sum {sum(x['weight'] for x in s):.6f} -> {out}")
