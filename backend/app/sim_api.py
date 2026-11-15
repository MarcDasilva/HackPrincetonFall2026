"""API for the frontend's live scene grid (/sim): BOTH of the patient's ears on a dummy head as one
coarse wave grid (hornsim.head_grid), and per ear an earpiece designed from the grid's scenes
(hornsim.scene_design). Each ear is its own patient record (one photo, one side, one audiogram).

    POST /api/sim/head_shapes                               face landmarks of a front photo -> fitted head shape
    GET  /api/sim/head?left={pid}&right={pid}[&shape={sid}] head grid + both patients' side and audiogram
    GET  /api/sim/clips/{name}.wav                          speech / babble clips for listening to a scene
    GET  /api/sim/scene_vocabulary                          sounds, limits and scene format (for the research step)
    POST /api/sim/scene_sets                                {source, scenes} -> validated, stored -> id
    POST /api/sim/scene_sets/suggest                        a needs profile -> suggested scene set (stored)
    GET  /api/sim/scene_sets/{sid}                          a stored scene set (/sim?scenes=<sid>)
    POST /api/sim/hrtf?left&right[&shape][&aided=1]         start each ear's direction table (hornsim.hrtf_table)
    GET  /api/sim/hrtf?left&right[&shape][&aided=1]         status, and the table when done
    POST /api/sim/optimize                                  optimise both earpieces in 3D for the scenes (hornsim.optimize_earpiece)
    GET  /api/sim/optimize?left&right[&shape]               progress and result
    POST /api/sim/patients/{pid}/design                     {audiogram_db_hl, scenes} -> 202
    GET  /api/sim/patients/{pid}/design                     status, log, result
    GET  /api/sim/patients/{pid}/design/files/{did}/{name}  earpiece mesh / print / preview
    POST /api/sim/patients/{pid}/design/wave_check          3D wave sim of the current design -> 202
    GET  /api/sim/patients/{pid}/design/wave_check          status, result (hornsim.aided_wave)

`000000000000` / `000000000001` are the average ear (AudioEar's mean, not anyone's ear) as a right
and as a mirrored left ear: created on first use so the grid works before any photo is uploaded.
"""
import json
import os
import re
import secrets
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import jobs
from .settings import settings

router = APIRouter(prefix="/api/sim")
AVERAGE_IDS = {"right": "000000000000", "left": "000000000001"}
AVERAGE_SIDE = {v: k for k, v in AVERAGE_IDS.items()}
ID_RE = re.compile(r"^[a-f0-9]{12}$")
DESIGN_RE = re.compile(r"^(grid\d{1,2}|opt\d{1,3})$")
DESIGN_FILES = {"earpiece_in_ear.glb": "model/gltf-binary", "earpiece.glb": "model/gltf-binary",
                "earpiece_print.stl": "model/stl", "preview.png": "image/png"}
EXAMPLE_AUDIOGRAM = {"250": 15, "500": 20, "1000": 30, "2000": 45, "4000": 55, "6000": 55}
N_BANDS = 18

_pool = ThreadPoolExecutor(max_workers=1)      # designs queue behind each other, not behind photo jobs
_lock = threading.Lock()


def _ensure_average(pid):
    """Average-ear patient for one side: mesh (mirrored for the left, as earrecon mirrors a left
    reconstruction), a context.json carrying only the config, and the canal samples."""
    d = jobs.patient_dir(pid)
    if os.path.exists(os.path.join(d, "context", "canals.json")):
        return
    import numpy as np
    from scipy.stats import qmc
    from earrecon.reconstruct import LANDMARKS_XLSX, mean_ear
    from hornsim.context import load_defaults
    from hornsim.head_grid import mirrored_mean_ear
    side = AVERAGE_SIDE[pid]
    with _lock:
        if os.path.exists(os.path.join(d, "context", "canals.json")):
            return
        os.makedirs(os.path.join(d, "context"), exist_ok=True)
        cfg = load_defaults()
        mesh = mean_ear(os.path.join(d, "ear")) if side == "right" else mirrored_mean_ear(os.path.join(d, "ear"))
        cfg["patient"].update({"id": pid, "ear_mesh": mesh, "side": side})
        cfg["ear_world"]["landmarks_xlsx"] = LANDMARKS_XLSX
        json.dump({"patient": cfg["patient"], "config": cfg,
                   "notes": [f"Average ear (AudioEar mean) as a {side} ear: NOT anyone's ear. Config only, for the scene grid."]},
                  open(os.path.join(d, "context", "context.json"), "w"), indent=1)
        C, E = cfg["canal"], cfg["ear_world"]      # same Latin hypercube as hornsim.context step 2
        lo, hi = C["residual_volume_cc"]
        u = np.sort(qmc.LatinHypercube(d=1, seed=C["seed"]).random(C["samples"])[:, 0])
        area_cm2 = np.pi * (E["canal_opening_diameter_mm"] / 20) ** 2
        canals = [{"id": i, "volume_cc": round(float(lo + (hi - lo) * x), 4),
                   "length_mm": round(float((lo + (hi - lo) * x) / area_cm2 * 10), 2)} for i, x in enumerate(u)]
        json.dump({"assumed_diameter_mm": E["canal_opening_diameter_mm"], "canals": canals},
                  open(os.path.join(d, "context", "canals.json"), "w"), indent=1)
        jobs.write_job(pid, {"id": pid, "status": "done", "average_ear": True, "results": {},
                             "request": {"side": side, "audiogram_db_hl": EXAMPLE_AUDIOGRAM,
                                         "audiogram_is_example": True}})


def _patient(pid):
    if pid in AVERAGE_SIDE:
        _ensure_average(pid)
    if not ID_RE.match(pid) or jobs.read_job(pid) is None:
        raise HTTPException(404, "patient not found")
    d = jobs.patient_dir(pid)
    if not os.path.exists(os.path.join(d, "context", "context.json")):
        raise HTTPException(409, "this patient has no context yet; wait for the pipeline to finish")
    return d, jobs.read_job(pid)


def _patient_info(pid, job):
    req = job.get("request", {})
    return {"id": pid, "average_ear": pid in AVERAGE_SIDE, "side": req.get("side", "right"),
            "audiogram_db_hl": req.get("audiogram_db_hl", EXAMPLE_AUDIOGRAM),
            "audiogram_is_example": bool(req.get("audiogram_is_example", True))}


# ---------------------------------------------------------------- direction tables (hornsim.hrtf_table)
# Each ear's response to every direction, by reciprocity: two GPU runs per head at HRTF_DX instead of
# one browser run per talker direction. aided=1 voxelizes both designed earpieces into the head, so
# "with earpieces" is simulated, not a gain added from the 1D model.
HRTF_DX = float(os.environ.get("HRTF_DX", "1.5"))
_hrtf_pool = ThreadPoolExecutor(max_workers=1)


def _hrtf_key(left, right, shape, aided):
    from hornsim import hrtf_table
    pieces = None
    if aided:
        pieces = {}
        for side, pid in (("left", left), ("right", right)):
            d, _ = _patient(pid)
            st = json.load(open(_status_path(d))) if os.path.exists(_status_path(d)) else {}
            did = ((st.get("result") or {}).get("design") or {}).get("id")
            stl = os.path.join(d, "aid", did or "-", "earpiece_print.stl")
            if st.get("status") != "done" or not did or not os.path.exists(stl):
                raise HTTPException(409, f"design the {side} earpiece first")
            pieces[side] = stl
    tag = "open" if not aided else f"aided_{os.path.basename(os.path.dirname(pieces['left']))}_{os.path.basename(os.path.dirname(pieces['right']))}"
    base = os.path.join(settings.data_dir, "heads", f"{left}_{right}_{shape or 'average'}", f"hrtf_{tag}_dx{HRTF_DX:g}_r{hrtf_table.RUN_S * 1e3:g}ms")
    return base, pieces


def _run_hrtf(base, ears, head, pieces):
    from hornsim import head_grid, hrtf_table
    st = base + ".status.json"
    try:
        json.dump({"status": "running", "started_at": time.time()}, open(st, "w"))
        t0 = time.time()
        grid = head_grid.export(None, ears, dx=HRTF_DX, head=head, pieces=pieces)
        table = hrtf_table.compute(grid, log=lambda m: None)
        out = {**hrtf_table.to_json(table), "dx_mm": HRTF_DX, "aided": bool(pieces),
               "piece_cells": {s: grid["ears"][s].get("piece_cells", 0) for s in ("left", "right")},
               "elapsed_s": round(time.time() - t0, 1)}
        json.dump(out, open(base + ".json.tmp", "w"))
        os.replace(base + ".json.tmp", base + ".json")
        json.dump({"status": "done", "elapsed_s": out["elapsed_s"]}, open(st, "w"))
    except Exception as e:
        json.dump({"status": "error", "error": str(e), "trace": traceback.format_exc(limit=3)}, open(st, "w"))


def _hrtf_inputs(left, right, shape):
    ears = {}
    for side, pid in (("left", left), ("right", right)):
        d, job = _patient(pid)
        if _patient_info(pid, job)["side"] != side:
            raise HTTPException(422, f"patient {pid} is not a {side} ear scan")
        ears[side] = json.load(open(os.path.join(d, "context", "context.json")))["config"]["patient"]["ear_mesh"]
    return ears, _load_shape(shape)


@router.post("/hrtf", status_code=202)
def start_hrtf(left: str, right: str, shape: str | None = None, aided: bool = False):
    ears, head = _hrtf_inputs(left, right, shape)
    base, pieces = _hrtf_key(left, right, shape, aided)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    st = base + ".status.json"
    if os.path.exists(base + ".json") or (os.path.exists(st) and json.load(open(st)).get("status") in ("queued", "running")):
        return {"status": "exists"}
    json.dump({"status": "queued"}, open(st, "w"))
    _hrtf_pool.submit(_run_hrtf, base, ears, head, pieces)
    return {"status": "queued"}


@router.get("/hrtf")
def get_hrtf(left: str, right: str, shape: str | None = None, aided: bool = False):
    _hrtf_inputs(left, right, shape)
    base, _ = _hrtf_key(left, right, shape, aided)
    if os.path.exists(base + ".json"):
        return {"status": "done", "table": json.load(open(base + ".json"))}
    st = base + ".status.json"
    return json.load(open(st)) if os.path.exists(st) else {"status": "none"}


# ---------------------------------------------------------------- 3D earpiece optimisation (hornsim.optimize_earpiece)

class OptSource(BaseModel):
    role: str
    az: float
    el: float = 0.0
    level_db: float = Field(ge=30, le=110)
    target: bool | None = None


class OptScene(BaseModel):
    name: str = Field("", max_length=80)
    weight: float = Field(1.0, ge=0, le=10)
    sources: list[OptSource] = Field(min_length=1, max_length=8)


class OptimizeRequest(BaseModel):
    left: str
    right: str
    shape: str | None = None
    audiogram: dict[str, dict[str, float]]           # {"left": {"250": 15, ...}, "right": {...}}
    scenes: list[OptScene] = Field(min_length=1, max_length=16)
    budget: int = Field(30, ge=6, le=120)


def _opt_path(left, right, shape):
    return os.path.join(settings.data_dir, "heads", f"{left}_{right}_{shape or 'average'}", "optimize.json")


def _opt_result(pid, d, r, prev):
    """The winner as this patient's scene_design result, in the shape the scene grid reads."""
    b = r["best"]
    gm, gw = np.array(b["insertion_front_db"]), np.array(b["insertion_worst_db"])
    T = np.array(prev.get("target_db") or [0.0] * len(gm))
    files = {k: f"aid/{b['design_id']}/{k}" for k in ("earpiece_in_ear.glb", "earpiece.glb", "earpiece_print.stl", "preview.png")
             if os.path.exists(os.path.join(d, "aid", b["design_id"], k))}
    pairs = [(n, round(u, 3), round(a, 3)) for n, u, a in zip(r["scene_names"], r["unaided"], b["aided"]) if u is not None]
    return {**{k: prev[k] for k in ("freqs_hz", "target_db", "share", "key_bands_hz", "guard_bands_hz", "triage", "why") if k in prev},
            "version": 2, "freqs_hz": r["freqs_hz"], "target_db": T.tolist(), "reach_db": gm.tolist(),
            "share": prev.get("share") or [1 / len(gm)] * len(gm), "key_bands_hz": prev.get("key_bands_hz", []),
            "guard_bands_hz": prev.get("guard_bands_hz", []), "triage": prev.get("triage", "passive-suitable"),
            "why": prev.get("why", "optimised in 3D for the scenes"),
            "design": {"id": b["design_id"], "params": b["params"], "objective": round(b["benefit"], 4),
                       "gain_mean_db": gm.tolist(), "gain_worst_db": gw.tolist(),
                       "key_met": "", "met": ((T < 1.0) | (gm >= T - 1.0)).tolist(),
                       "geometry": b.get("geometry", {}), "files": files},
            "attempts": [{"design_id": h["design_id"], "objective": round(h.get("benefit", float("nan")), 4) if h["ok"] else None,
                          "ok": h["ok"], "reasons": h.get("reasons", [])} for h in r["history"]],
            "swept": len(r["history"]), "elapsed_s": r["elapsed_s"],
            "optimizer": {"method": "Bayesian optimisation on the 3D head simulation", "dx_mm": r["dx_mm"],
                          "benefit": round(b["benefit"], 4), "scenes": [{"name": n, "without": u, "with": a} for n, u, a in pairs]},
            "notes": [f"Optimised against the 3D head simulation ({r['dx_mm']} mm, reciprocity) for the scene grid's scenes: "
                      "the objective is the scene-weighted gain in SII/audibility over wearing nothing.",
                      "gain_mean_db is the simulated insertion gain for a talker in front; gain_worst_db the lowest over the scenes' directions."]}


def _run_optimize(req, ears, head, path):
    from hornsim import optimize_earpiece as oe
    state = {"status": "running", "started_at": time.time(), "progress": {}, "log": []}

    def save():
        json.dump(state, open(path + ".tmp", "w"), default=float)
        os.replace(path + ".tmp", path)

    try:
        save()
        scenes = [{"name": s["name"], "weight": s["weight"], "sources": [{k: v for k, v in x.items() if v is not None} for x in s["sources"]]}
                  for s in req["scenes"]]
        for side in ("left", "right"):
            pid = req[side]
            d, _ = _patient(pid)
            ag = {float(k): float(v) for k, v in req["audiogram"][side].items()}

            def prog(pg, side=side):
                state["progress"][side] = pg
                save()
            r = oe.optimize(d, side, ears, head, scenes, ag, budget=req["budget"],
                            log=lambda m: state["log"].append(f"{time.strftime('%H:%M:%S')} {m}"), progress=prog)
            if not r["best"]:
                raise ValueError(f"no {side} earpiece passed the geometry checks")
            prev = (json.load(open(_status_path(d))).get("result") or {}) if os.path.exists(_status_path(d)) else {}
            _write_status(d, status="done", result=_opt_result(pid, d, r, prev), finished_at=time.time(), log=state["log"][-20:])
            state.setdefault("results", {})[side] = {"design_id": r["best"]["design_id"], "benefit": r["best"]["benefit"]}
        state["status"] = "done"
        save()
    except Exception as e:
        state.update(status="error", error=str(e), trace=traceback.format_exc(limit=3))
        save()


@router.post("/optimize", status_code=202)
def start_optimize(body: OptimizeRequest):
    from hornsim import scene_spec
    for s in body.scenes:
        for x in s.sources:
            if x.role not in scene_spec.SOUNDS:
                raise HTTPException(422, f"unknown sound {x.role!r}")
    ears, head = _hrtf_inputs(body.left, body.right, body.shape)
    path = _opt_path(body.left, body.right, body.shape)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and json.load(open(path)).get("status") == "running":
        raise HTTPException(409, "an optimisation is already running for these ears")
    json.dump({"status": "queued"}, open(path, "w"))
    _hrtf_pool.submit(_run_optimize, body.model_dump(), ears, head, path)
    return {"status": "queued"}


@router.get("/optimize")
def optimize_status(left: str, right: str, shape: str | None = None):
    path = _opt_path(left, right, shape)
    return json.load(open(path)) if os.path.exists(path) else {"status": "none"}


# ---------------------------------------------------------------- scene sets (hornsim.scene_spec)

def _scene_set_path(sid):
    return os.path.join(settings.data_dir, "scene_sets", f"{sid}.json")


def _store_scene_set(s):
    sid = secrets.token_hex(6)
    os.makedirs(os.path.dirname(_scene_set_path(sid)), exist_ok=True)
    json.dump({**s, "id": sid, "created_at": time.time()}, open(_scene_set_path(sid), "w"), indent=1)
    return {"id": sid, **s}


@router.get("/scene_vocabulary")
def scene_vocabulary():
    from hornsim import scene_spec
    return scene_spec.vocabulary()


@router.post("/scene_sets", status_code=201)
def create_scene_set(body: dict):
    """A scene set built by the research step (or anyone): validated against the vocabulary, stored."""
    from hornsim import scene_spec
    try:
        s = scene_spec.validate_scene_set(body)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**_store_scene_set(s), "scenarios": scene_spec.as_scenarios(s)}


class NeedsBody(BaseModel):
    activities: list[str] = Field(default_factory=list, max_length=40)
    goals: list[str] = Field(default_factory=list, max_length=40)
    priorities: list[str] = Field(default_factory=list, max_length=40)
    requirements: list[str] = Field(default_factory=list, max_length=40)
    free_text: str = Field("", max_length=4000)
    max_scenes: int = Field(9, ge=1, le=16)


@router.post("/scene_sets/suggest", status_code=201)
def suggest_scene_set(body: NeedsBody):
    """A first scene set from a needs profile (the agents' NeedsProfile fields), stored like any other."""
    from hornsim import scene_spec
    s = scene_spec.suggest_scenes(body.model_dump(exclude={"max_scenes"}), body.max_scenes)
    return {**_store_scene_set(s), "scenarios": scene_spec.as_scenarios(s)}


@router.get("/scene_sets/{sid}")
def get_scene_set(sid: str):
    if not ID_RE.match(sid) or not os.path.exists(_scene_set_path(sid)):
        raise HTTPException(404, "scene set not found")
    return json.load(open(_scene_set_path(sid)))


CLIP_RE = re.compile(r"^(clean_[1-3]|babble_[1-4]_noise)\.wav$")
CLIP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "speech")


@router.get("/clips/{name}")
def get_clip(name: str):
    """The cached test-speech clips (macOS `say`, hornsim.context) for the scene grid's listen mode."""
    p = os.path.join(CLIP_DIR, name)
    if not CLIP_RE.match(name) or not os.path.isfile(p):
        raise HTTPException(404, "unknown clip")
    return FileResponse(p, media_type="audio/wav")


class HeadShapeRequest(BaseModel):
    """MediaPipe face-landmarker output for one front photo. The photo stays in the browser."""
    landmarks: list[list[float]] = Field(min_length=478, max_length=478)
    image_w: int = Field(gt=0, le=20000)
    image_h: int = Field(gt=0, le=20000)
    yaw_deg: float | None = Field(None, ge=-90, le=90)
    head_rows: list[list[float]] | None = Field(None, max_length=4000, description="[[y, x_left, x_right], ...] px: hair + face silhouette per row")


def _shape_path(sid):
    return os.path.join(settings.data_dir, "head_shapes", f"{sid}.json")


@router.post("/head_shapes", status_code=201)
def create_head_shape(body: HeadShapeRequest):
    """Fit the head's shape from a front photo's face landmarks (hornsim.head_shape). Only the fitted
    shape is stored, not the landmarks."""
    from hornsim import head_shape
    if any(len(p) < 2 for p in body.landmarks):
        raise HTTPException(422, "each landmark needs x and y")
    try:
        if body.head_rows and any(len(r) != 3 for r in body.head_rows):
            raise ValueError("each head row is [y, x_left, x_right]")
        shape, report = head_shape.fit(body.landmarks, body.image_w, body.image_h, body.yaw_deg, body.head_rows)
    except ValueError as e:
        raise HTTPException(422, str(e))
    sid = secrets.token_hex(6)
    os.makedirs(os.path.dirname(_shape_path(sid)), exist_ok=True)
    json.dump({"id": sid, "shape": shape.to_json(), "warnings": report["warnings"], "created_at": time.time()},
              open(_shape_path(sid), "w"))
    return {"id": sid, "meta": report["meta"], "warnings": report["warnings"], "overlay": report["overlay"]}


def _load_shape(sid):
    from hornsim import head_shape
    if not sid:
        return None
    if not ID_RE.match(sid) or not os.path.exists(_shape_path(sid)):
        raise HTTPException(404, "head shape not found; take the front photo again")
    return head_shape.HeadShape.from_json(json.load(open(_shape_path(sid)))["shape"])


@router.get("/head")
def get_head(left: str = Query(..., description="patient id of the LEFT ear scan"),
             right: str = Query(..., description="patient id of the RIGHT ear scan"),
             shape: str | None = Query(None, description="head shape id from POST /head_shapes; none = the average head")):
    """Both ears on the dummy head. Each id must be a patient whose photo was taken of that side."""
    from hornsim import head_grid
    head = _load_shape(shape)
    ears, info = {}, {}
    for side, pid in (("left", left), ("right", right)):
        d, job = _patient(pid)
        info[side] = _patient_info(pid, job)
        if info[side]["side"] != side:
            raise HTTPException(422, f"patient {pid} is a {info[side]['side']} ear scan, not a {side} ear")
        ears[side] = json.load(open(os.path.join(d, "context", "context.json")))["config"]["patient"]["ear_mesh"]
    out = os.path.join(settings.data_dir, "heads", f"{left}_{right}_{shape or 'average'}", f"head_grid_v{head_grid.VERSION}.json")
    sources = list(ears.values()) + ([_shape_path(shape)] if shape else [])
    stale = not os.path.exists(out) or any(os.path.getmtime(m) > os.path.getmtime(out) for m in sources)
    if stale:
        with _lock:
            head_grid.export(out, ears, head=head)
    grid = json.load(open(out))
    grid["patients"] = info
    return grid


class GridScene(BaseModel):
    id: str = Field(max_length=64)
    name: str = Field("", max_length=80)
    weight: float = Field(ge=0, le=100)
    deficit_db: list[float] = Field(min_length=N_BANDS, max_length=N_BANDS)
    deficit_weighted: list[float] | None = Field(None, min_length=N_BANDS, max_length=N_BANDS)


class DesignRequest(BaseModel):
    audiogram_db_hl: dict[str, float]
    scenes: list[GridScene] = Field(min_length=1, max_length=64)


def _status_path(d):
    return os.path.join(d, "scene_design", "status.json")


def _write_status(d, **kw):
    p = _status_path(d)
    s = json.load(open(p)) if os.path.exists(p) else {}
    s.update(kw, updated_at=time.time())
    tmp = p + ".tmp"
    json.dump(s, open(tmp, "w"), indent=1, default=float)
    os.replace(tmp, p)
    return s


def _run_design(d, request):
    from hornsim import scene_design
    logs = []

    def log(m):
        logs.append(f"{time.strftime('%H:%M:%S')} {m}")
        _write_status(d, log=logs)
    try:
        _write_status(d, status="running", log=logs, error=None, result=None, started_at=time.time())
        result = scene_design.run(d, request, log=log)
        _write_status(d, status="done", result=result, finished_at=time.time())
    except Exception as e:      # report to the client; keep the trace in the log
        logs.append(traceback.format_exc(limit=3))
        _write_status(d, status="error", error=str(e), log=logs)


@router.post("/patients/{pid}/design", status_code=202)
def start_design(pid: str, body: DesignRequest):
    d, _ = _patient(pid)
    os.makedirs(os.path.join(d, "scene_design"), exist_ok=True)
    p = _status_path(d)
    if os.path.exists(p) and json.load(open(p)).get("status") in ("queued", "running"):
        raise HTTPException(409, "a design is already running for this patient")
    _write_status(d, status="queued", log=[], error=None, result=None)
    _pool.submit(_run_design, d, body.model_dump())
    return {"id": pid, "status_url": f"/api/sim/patients/{pid}/design"}


@router.get("/patients/{pid}/design")
def design_status(pid: str):
    d, _ = _patient(pid)
    p = _status_path(d)
    if not os.path.exists(p):
        return {"status": "none"}
    return json.load(open(p))


@router.get("/patients/{pid}/design/files/{did}/{name}")
def design_file(pid: str, did: str, name: str):
    d, _ = _patient(pid)
    if not DESIGN_RE.match(did) or name not in DESIGN_FILES:
        raise HTTPException(404, "unknown file")
    p = os.path.join(d, "aid", did, name)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not ready")
    return FileResponse(p, media_type=DESIGN_FILES[name], filename=name if name.endswith(".stl") else None)


# ---------------------------------------------------------------- 3D wave check of the current design

def _wave_path(d):
    return os.path.join(d, "scene_design", "wave_status.json")


def _write_wave(d, **kw):
    p = _wave_path(d)
    s = json.load(open(p)) if os.path.exists(p) else {}
    s.update(kw, updated_at=time.time())
    tmp = p + ".tmp"
    json.dump(s, open(tmp, "w"), indent=1, default=float)
    os.replace(tmp, p)


def _run_wave(d, did, azimuths, dx):
    from hornsim import aided_wave
    logs = []

    def log(m):
        logs.append(f"{time.strftime('%H:%M:%S')} {m}")
        _write_wave(d, log=logs)
    try:
        _write_wave(d, status="running", design_id=did, log=logs, error=None, result=None)
        log(f"voxelizing the earpiece into the wave grid at {dx} mm")
        r = aided_wave.measure(d, did, azimuths, dx=dx, log=log)
        _write_wave(d, status="done", result=r)
    except Exception as e:
        logs.append(traceback.format_exc(limit=3))
        _write_wave(d, status="error", error=str(e), log=logs)


class WaveCheck(BaseModel):
    azimuths: list[float] = Field(default_factory=lambda: [0.0, 90.0], min_length=1, max_length=4)
    dx_mm: float = Field(1.0, ge=0.75, le=2.5)


@router.post("/patients/{pid}/design/wave_check", status_code=202)
def start_wave_check(pid: str, body: WaveCheck):
    d, _ = _patient(pid)
    st = json.load(open(_status_path(d))) if os.path.exists(_status_path(d)) else {}
    did = ((st.get("result") or {}).get("design") or {}).get("id")
    if st.get("status") != "done" or not did:
        raise HTTPException(409, "design an earpiece first")
    if any(not (0 <= a <= 180) for a in body.azimuths):
        raise HTTPException(422, "azimuths must be 0-180 relative to this ear (the 3D check's flat head plane cannot model the far side)")
    if os.path.exists(_wave_path(d)) and json.load(open(_wave_path(d))).get("status") in ("queued", "running"):
        raise HTTPException(409, "a wave check is already running for this patient")
    _write_wave(d, status="queued", design_id=did, log=[], error=None, result=None)
    _pool.submit(_run_wave, d, did, body.azimuths, body.dx_mm)
    return {"id": pid, "status_url": f"/api/sim/patients/{pid}/design/wave_check"}


@router.get("/patients/{pid}/design/wave_check")
def wave_check_status(pid: str):
    d, _ = _patient(pid)
    return json.load(open(_wave_path(d))) if os.path.exists(_wave_path(d)) else {"status": "none"}
