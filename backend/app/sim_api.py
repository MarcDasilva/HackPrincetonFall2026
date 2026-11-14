"""API for the frontend's live scene grid (/sim): the patient's ear as a coarse wave grid, and an
earpiece designed from the grid's scenes (hornsim.scene_design).

    GET  /api/sim/patients/{pid}/grid                       ear grid + side + audiogram
    POST /api/sim/patients/{pid}/design                     {audiogram_db_hl, scenes} -> 202
    GET  /api/sim/patients/{pid}/design                     status, log, result
    GET  /api/sim/patients/{pid}/design/files/{did}/{name}  earpiece mesh / print / preview
    POST /api/sim/patients/{pid}/design/wave_check          3D wave sim of the current design -> 202
    GET  /api/sim/patients/{pid}/design/wave_check          status, result (hornsim.aided_wave)

`000000000000` is the average ear (AudioEar's mean, not anyone's ear): created on first use so the
grid works before any photo has been uploaded.
"""
import json
import os
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import jobs

router = APIRouter(prefix="/api/sim")
AVERAGE_ID = "000000000000"
ID_RE = re.compile(r"^[a-f0-9]{12}$")
DESIGN_RE = re.compile(r"^grid\d{1,2}$")
DESIGN_FILES = {"earpiece_in_ear.glb": "model/gltf-binary", "earpiece.glb": "model/gltf-binary",
                "earpiece_print.stl": "model/stl", "preview.png": "image/png"}
EXAMPLE_AUDIOGRAM = {"250": 15, "500": 20, "1000": 30, "2000": 45, "4000": 55, "6000": 55}
N_BANDS = 18

_pool = ThreadPoolExecutor(max_workers=1)      # designs queue behind each other, not behind photo jobs
_lock = threading.Lock()


def _ensure_average():
    """Average-ear patient: mesh, a context.json carrying only the config, and the canal samples."""
    d = jobs.patient_dir(AVERAGE_ID)
    if os.path.exists(os.path.join(d, "context", "canals.json")):
        return
    import numpy as np
    from scipy.stats import qmc
    from earrecon.reconstruct import LANDMARKS_XLSX, mean_ear
    from hornsim.context import load_defaults
    with _lock:
        if os.path.exists(os.path.join(d, "context", "canals.json")):
            return
        os.makedirs(os.path.join(d, "context"), exist_ok=True)
        cfg = load_defaults()
        cfg["patient"].update({"id": AVERAGE_ID, "ear_mesh": mean_ear(os.path.join(d, "ear")), "side": "right"})
        cfg["ear_world"]["landmarks_xlsx"] = LANDMARKS_XLSX
        json.dump({"patient": cfg["patient"], "config": cfg,
                   "notes": ["Average ear (AudioEar mean): NOT anyone's ear. Config only, for the scene grid."]},
                  open(os.path.join(d, "context", "context.json"), "w"), indent=1)
        C, E = cfg["canal"], cfg["ear_world"]      # same Latin hypercube as hornsim.context step 2
        lo, hi = C["residual_volume_cc"]
        u = np.sort(qmc.LatinHypercube(d=1, seed=C["seed"]).random(C["samples"])[:, 0])
        area_cm2 = np.pi * (E["canal_opening_diameter_mm"] / 20) ** 2
        canals = [{"id": i, "volume_cc": round(float(lo + (hi - lo) * x), 4),
                   "length_mm": round(float((lo + (hi - lo) * x) / area_cm2 * 10), 2)} for i, x in enumerate(u)]
        json.dump({"assumed_diameter_mm": E["canal_opening_diameter_mm"], "canals": canals},
                  open(os.path.join(d, "context", "canals.json"), "w"), indent=1)
        jobs.write_job(AVERAGE_ID, {"id": AVERAGE_ID, "status": "done", "average_ear": True, "results": {},
                                    "request": {"side": "right", "audiogram_db_hl": EXAMPLE_AUDIOGRAM,
                                                "audiogram_is_example": True}})


def _patient(pid, ear=None):
    """(ear folder, {side, audiogram_db_hl, audiogram_is_example}). A two-ear patient serves ONE ear per call:
    `ear`, or by default the worse one by mean threshold, the SAME rule agents/horn_study/server.py studies."""
    if pid == AVERAGE_ID:
        _ensure_average()
    if not ID_RE.match(pid) or jobs.read_job(pid) is None:
        raise HTTPException(404, "patient not found")
    job = jobs.read_job(pid)
    req = job.get("request", {})
    if "ears" in job:
        ags = {e: (req.get(e) or {}).get("audiogram_db_hl") or {} for e in jobs.ears(job)}
        ear = ear or max(ags, key=lambda e: sum(ags[e].values()) / max(1, len(ags[e])))
        if ear not in ags:
            raise HTTPException(404, f"this patient has no {ear} ear")
        d, ag = jobs.ear_dir(pid, ear, job), ags[ear]
    else:
        d, ear, ag = jobs.patient_dir(pid), req.get("side", "right"), req.get("audiogram_db_hl")
    if not os.path.exists(os.path.join(d, "context", "context.json")):
        raise HTTPException(409, "this patient has no context yet; wait for the pipeline to finish")
    example = bool(req.get("audiogram_is_example", True)) or not ag
    return d, {"side": ear, "audiogram_db_hl": ag or EXAMPLE_AUDIOGRAM, "audiogram_is_example": example}


@router.get("/patients/{pid}/grid")
def get_grid(pid: str, ear: str | None = None):
    d, info = _patient(pid, ear)
    out = os.path.join(d, "scene_design", "ear_grid.json")
    if not os.path.exists(out):
        from hornsim import sim_grid
        cfg = json.load(open(os.path.join(d, "context", "context.json")))["config"]
        sim_grid.export(out, cfg["patient"]["ear_mesh"], left=info["side"] == "left")
    grid = json.load(open(out))
    grid["patient"] = {"id": pid, "average_ear": pid == AVERAGE_ID, **info}
    if pid == AVERAGE_ID:
        grid["ear"] = "average ear (AudioEar mean)"
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
def start_design(pid: str, body: DesignRequest, ear: str | None = None):
    d, _ = _patient(pid, ear)
    os.makedirs(os.path.join(d, "scene_design"), exist_ok=True)
    p = _status_path(d)
    if os.path.exists(p) and json.load(open(p)).get("status") in ("queued", "running"):
        raise HTTPException(409, "a design is already running for this patient")
    _write_status(d, status="queued", log=[], error=None, result=None)
    _pool.submit(_run_design, d, body.model_dump())
    return {"id": pid, "status_url": f"/api/sim/patients/{pid}/design"}


@router.get("/patients/{pid}/design")
def design_status(pid: str, ear: str | None = None):
    d, _ = _patient(pid, ear)
    p = _status_path(d)
    if not os.path.exists(p):
        return {"status": "none"}
    return json.load(open(p))


@router.get("/patients/{pid}/design/files/{did}/{name}")
def design_file(pid: str, did: str, name: str, ear: str | None = None):
    d, _ = _patient(pid, ear)
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
def start_wave_check(pid: str, body: WaveCheck, ear: str | None = None):
    d, _ = _patient(pid, ear)
    st = json.load(open(_status_path(d))) if os.path.exists(_status_path(d)) else {}
    did = ((st.get("result") or {}).get("design") or {}).get("id")
    if st.get("status") != "done" or not did:
        raise HTTPException(409, "design an earpiece first")
    if any(not (0 <= a <= 180) for a in body.azimuths):
        raise HTTPException(422, "azimuths must be 0-180 (the flat head plane cannot model the far side)")
    if os.path.exists(_wave_path(d)) and json.load(open(_wave_path(d))).get("status") in ("queued", "running"):
        raise HTTPException(409, "a wave check is already running for this patient")
    _write_wave(d, status="queued", design_id=did, log=[], error=None, result=None)
    _pool.submit(_run_wave, d, did, body.azimuths, body.dx_mm)
    return {"id": pid, "status_url": f"/api/sim/patients/{pid}/design/wave_check"}


@router.get("/patients/{pid}/design/wave_check")
def wave_check_status(pid: str, ear: str | None = None):
    d, _ = _patient(pid, ear)
    return json.load(open(_wave_path(d))) if os.path.exists(_wave_path(d)) else {"status": "none"}
