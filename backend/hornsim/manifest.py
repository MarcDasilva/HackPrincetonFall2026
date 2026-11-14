"""Manifest v2 (spec 12): ONE file, `results/results.json`, holds everything the demo screen shows.

    python -m hornsim.manifest <patient_dir>

`write()` copies every asset the screen loads into `results/` next to the manifest, so the folder is
self-contained and can be served statically with the backend off. Paths in the manifest are relative
to `results/`. A section whose stage output does not exist yet is LEFT OUT, never filled with
placeholders — the frontend (`frontend/app/demo/`) treats an absent section as "not run yet".

The hand-written fake that the frontend is built against is `frontend/public/demo/results.fake.json`.
"""
import glob
import json
import os
import shutil
import sys

VERSION = 2

# Shape of the manifest. Values are type/unit descriptions, not data. `?` marks optional keys.
SCHEMA = {
    "version": "int, always 2",
    "fake?": "bool; true ONLY on hand-written fake manifests — the screen labels them",
    "patient": {"id": "str", "side": "left | right", "scale_source": "coin | default",
                "is_average_ear": "bool — the screen labels the average ear", "audiogram_is_example": "bool"},
    "ear": {"mesh": "path to ear.glb", "audiogram": "[[freq_hz, threshold_db_hl]]",
            "params": "ear_params dict (spec 02), mm / mm² / cc",
            "canal_band": {"volume_cc": "[lo, hi]", "samples": "int", "diameter_mm": "float, assumed"}},
    "waves": {"viewer": "path or absolute URL of the wave viewer page (spec 03)", "ear": "waves/ear.json",
              "runs": "waves/runs.json", "directions": "[{az, el, eardrum_peak_hz}]",
              "open_ear?": {"az": "deg", "freqs_hz": "[]", "gain_db": "[] eardrum re free field"}},
    "scenes": [{"id": "int", "condition": "C1..C8", "clip": "str", "level_db": "dB SPL", "talker_deg": "deg",
                "noise": "{type, deg, snr_db} | null", "canal": "int (quartile canal id)", "weight": "0..1, sums to 1",
                "deficit_db?": "[18] per SII band, importance-weighted audibility gap",
                "sii?": "{unaided, healthy?, pick?} 0..1", "haspi?": "{unaided, healthy?, pick?} 0..1",
                "harm?": "bool, pick scores below unaided",
                "neurograms?": "{healthy?, unaided?, aided?} png paths (showcase scenes only)",
                "audio?": "{healthy?, unaided?, aided?} wav paths (showcase scenes only)"}],
    "neurogram_axes?": {"cf_hz": "[lo, hi] characteristic frequency, log", "t_s": "[start, end]"},
    "baseline_timeline": "[{scene: id, t_ms: finish time from launch}], one per finished scene",
    "target": {"freqs_hz": "[18]", "gain_db": "[18] T(f)", "reach_db": "[18] what a horn that fits can reach",
               "ratio?": "[18]", "triage": "passive-suitable | partial | powered aid recommended"},
    "designs": [{"id": "int | str", "params": "design x (spec 07 keys)", "mesh": "aid_in_ear glb path",
                 "point?": "[boom_250hz_db, net_gain_db], where it sits in tradeoff.cloud",
                 "gain_curves?": {"freqs_hz": "[]", "mean": "[] insertion gain dB", "canals": "[32][] dB"},
                 "harm_rate?": "0..1", "gap_closed?": "0..1", "score?": "float"}],
    "tradeoff": {"cloud": "[[boom_250hz_db, net_gain_db]] every evaluated design",
                 "front": "[[boom_250hz_db, net_gain_db]] non-dominated, sorted by boom"},
    "agent": "[{round: int, line: str}]",
    "pick": "design id",
    "card": {"triage": "str", "target_band_hz": "[lo, hi]",
             "net_gain_db?": "{peak, peak_hz, canal_worst}",
             "bore?": "{throat_mm2, mouth_mm2, length_mm, turns, flare}",
             "vent?": "{count, diameter_mm, boom_250hz_db, cost_500hz_db}",
             "print_tolerance?": "{throat_mm, gain_db}", "personalized?": "[param]", "standard?": "[param]",
             "harm?": "{scenes, of}", "gap_closed?": "{mean, worst}"},
}


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _by_id(rows, *keys):
    """Stage files store per-scene rows as a list or as a dict keyed by id; index both the SAME way."""
    if isinstance(rows, dict):
        return {str(k): v for k, v in rows.items()}
    for k in keys:
        if rows and k in rows[0]:
            return {str(r[k]): r for r in rows}
    return {}


class _Assets:
    """Copies a file into results/ once and returns its manifest path — a path pointing outside results/
    would break the static, backend-free demo."""

    def __init__(self, pdir, out):
        self.pdir, self.out = pdir, out

    def __call__(self, rel):
        src = os.path.join(self.pdir, rel)
        if not os.path.exists(src):
            return None
        dst = os.path.join(self.out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        return rel


def _patient(pdir):
    req = _load(os.path.join(pdir, "request.json")) or (_load(os.path.join(pdir, "job.json")) or {}).get("request")
    if not req:
        return None, None
    patient = {"id": os.path.basename(os.path.normpath(pdir)), "side": req.get("side"),
               "scale_source": req.get("scale_source", "default"),
               "is_average_ear": bool(req.get("is_average_ear", False)),
               "audiogram_is_example": bool(req.get("audiogram_is_example", False))}
    ag = sorted([float(f), float(db)] for f, db in (req.get("audiogram_db_hl") or {}).items())
    return patient, ag


def _waves(pdir, out):
    src = os.path.join(pdir, "waves")
    runs = _load(os.path.join(src, "runs.json"))
    if runs is None:
        return None
    shutil.copytree(src, os.path.join(out, "waves"), dirs_exist_ok=True)
    w = {"viewer": "waves/index.html", "ear": "waves/ear.json", "runs": "waves/runs.json",
         "directions": [{k: r.get(k) for k in ("az", "el", "eardrum_peak_hz")} for r in runs]}
    front = next((r for r in runs if r.get("az") == 0 and r.get("el") == 0), None)
    if front and "transfer" in front:
        w["open_ear"] = {"az": 0, "freqs_hz": front["transfer"]["freqs_hz"], "gain_db": front["transfer"]["eardrum_db"]}
    return w


def _scenes(pdir, copy):
    scenes = _load(os.path.join(pdir, "scenes", "scenes.json"))
    if not scenes:
        return None
    base = _by_id(_load(os.path.join(pdir, "scenes", "baseline.json")) or [], "id", "scene")
    check = _load(os.path.join(pdir, "check", "check.json")) or {}
    pick = (check.get("designs") or {}).get(str(check.get("pick")), {})
    aided = _by_id(pick.get("scenes") or [], "id", "scene")
    rows = []
    for s in scenes:
        sid = str(s["id"])
        row = {k: s.get(k) for k in ("id", "condition", "clip", "level_db", "talker_deg", "noise", "canal", "weight")}
        b, a = base.get(sid, {}), aided.get(sid, {})
        if "deficit_db" in b:
            row["deficit_db"] = b["deficit_db"]
        for m in ("sii", "haspi"):
            v = {k: x for k, x in (("unaided", b.get(f"{m}_unaided")), ("healthy", b.get(f"{m}_healthy")),
                                   ("pick", a.get(m))) if x is not None}
            if v:
                row[m] = v
        if "harm" in a:
            row["harm"] = bool(a["harm"])
        # Baseline renders healthy/impaired pairs; the hearing check renders healthy/unaided/aided triplets. The check wins.
        ng = {"healthy": copy(f"scenes/neurograms/{sid}_healthy.png"), "unaided": copy(f"scenes/neurograms/{sid}_impaired.png")}
        for k in ("healthy", "unaided", "aided"):
            ng[k] = copy(f"check/neurograms/{sid}_{k}.png") or ng.get(k)
        audio = {k: copy(f"check/audio/{sid}_{k}.wav") for k in ("healthy", "unaided", "aided")}
        for key, d in (("neurograms", ng), ("audio", audio)):
            d = {k: v for k, v in d.items() if v}
            if d:
                row[key] = d
        rows.append(row)
    return rows


def _timeline(pdir):
    path = os.path.join(pdir, "scenes", "progress.jsonl")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        lines = [json.loads(line) for line in f if line.strip()]
    return sorted(({"scene": r["scene"], "t_ms": r["t_ms"]} for r in lines), key=lambda r: r["t_ms"])


def _designs(pdir, copy):
    cands = _by_id(_load(os.path.join(pdir, "design", "candidates.json")) or [], "id")
    check = (_load(os.path.join(pdir, "check", "check.json")) or {}).get("designs") or {}
    designs = []
    for dj in sorted(glob.glob(os.path.join(pdir, "aid", "**", "design.json"), recursive=True)):
        folder = os.path.dirname(dj)
        built = _load(dj)
        # Flat aid/ is the pre-spec-09 single design; aid/<id>/ is one per candidate.
        did = built.get("design_id") or ("0" if folder.endswith(os.sep + "aid") else os.path.basename(folder))
        mesh = next(iter(sorted(glob.glob(os.path.join(folder, "*_in_ear.glb")))), None)
        cand, chk = cands.get(str(did), {}), check.get(str(did), {})
        d = {"id": did, "params": cand.get("params") or built.get("params") or built,
             "mesh": copy(os.path.relpath(mesh, pdir)) if mesh else None}
        for k in ("gain_curves", "point", "score"):
            if k in cand:
                d[k] = cand[k]
        for k in ("harm_rate", "gap_closed", "score"):
            if k in chk:
                d[k] = chk[k]
        designs.append({k: v for k, v in d.items() if v is not None})
    return designs or None


def _card(target, design, check):
    if check and check.get("card"):
        return check["card"]
    card = {}
    if target:
        card["triage"] = target.get("triage")
        band = [f for f, g in zip(target.get("freqs_hz", []), target.get("gain_db", [])) if g > 0]
        if band:
            card["target_band_hz"] = [band[0], band[-1]]
    if design:
        p = design.get("params", {})
        bore = {"throat_mm2": p.get("throat_mm2"), "mouth_mm2": p.get("mouth_mm2"),
                "length_mm": p.get("length_mm", p.get("bore_length_mm")),
                "turns": (p.get("spiral") or {}).get("turns", p.get("turns")), "flare": p.get("flare")}
        bore = {k: v for k, v in bore.items() if v is not None}
        if bore:
            card["bore"] = bore
        for k in ("harm_rate", "gap_closed"):
            if k in design:
                card[k] = design[k]
    return {k: v for k, v in card.items() if v is not None} or None


def write(patient_dir):
    """Assemble `<patient_dir>/results/results.json` from whatever stage outputs exist; returns the manifest."""
    out = os.path.join(patient_dir, "results")
    os.makedirs(out, exist_ok=True)
    copy = _Assets(patient_dir, out)
    m = {"version": VERSION}
    patient, audiogram = _patient(patient_dir)
    if patient:
        m["patient"] = patient
    skin = "ear/ear_skin.glb" if os.path.exists(os.path.join(patient_dir, "ear", "ear_skin.glb")) else "ear/ear.glb"
    ear = {"mesh": copy(skin), "audiogram": audiogram or None}
    ctx = _load(os.path.join(patient_dir, "context", "context.json")) or {}
    if ctx.get("ear_params"):
        ear["params"] = ctx["ear_params"]
    canals = _load(os.path.join(patient_dir, "context", "canals.json"))
    if canals:
        vols = [c["volume_cc"] for c in canals["canals"]]
        ear["canal_band"] = {"volume_cc": [min(vols), max(vols)], "samples": len(vols),
                             "diameter_mm": canals.get("assumed_diameter_mm")}
    ear = {k: v for k, v in ear.items() if v}
    if ear:
        m["ear"] = ear
    check = _load(os.path.join(patient_dir, "check", "check.json"))
    target = _load(os.path.join(patient_dir, "target", "target.json"))
    tradeoff = _load(os.path.join(patient_dir, "design", "tradeoff.json"))
    rounds = _load(os.path.join(patient_dir, "agent", "rounds.json"))
    designs = _designs(patient_dir, copy)
    pick = (check or {}).get("pick", designs[0]["id"] if designs and len(designs) == 1 else None)
    sections = {
        "waves": _waves(patient_dir, out),
        "scenes": _scenes(patient_dir, copy),
        "baseline_timeline": _timeline(patient_dir),
        "target": target,
        "designs": designs,
        "tradeoff": tradeoff and {"cloud": tradeoff.get("cloud", []), "front": tradeoff.get("front", [])},
        "agent": rounds and [{"round": r.get("round", i + 1), "line": r.get("line") or r.get("explanation", "")}
                             for i, r in enumerate(rounds)],
        "pick": pick,
        "card": _card(target, next((d for d in designs or [] if d["id"] == pick), None), check),
    }
    m.update({k: v for k, v in sections.items() if v is not None})
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(m, f, indent=1)
    return m


if __name__ == "__main__":
    print(json.dumps({k: (v if not isinstance(v, list) else f"[{len(v)}]") for k, v in write(sys.argv[1]).items()}, indent=1))
