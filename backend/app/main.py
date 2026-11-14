"""HTTP API for the horn-aid pipeline.

    uvicorn app.main:app --host 0.0.0.0 --port 8000      (run from backend/)

POST /api/patients            photo + box + side + ear height + audiogram -> starts the pipeline
GET  /api/patients/{id}       status, step, log and results
POST /api/patients/{id}/aid   rebuild the aid with new design numbers
GET  /api/patients/{id}/files/{name}   generated files (meshes, images, STL, JSON)
GET  /api/health
The static frontend (../frontend) is served at / when present.
"""
import io
import json
import os
import re
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from . import jobs
from .settings import settings

app = FastAPI(title="Horn aid API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

ID_RE = re.compile(r"^[a-f0-9]{12}$")
FILES = {
    "ear.glb": "ear/ear.glb", "ear.obj": "ear/ear.obj", "mask.png": "ear/mask.png",
    "overlay.jpg": "ear/overlay.jpg", "input.jpg": "ear/input.jpg",
    "ear_world.glb": "context/ear_world.glb", "summary.png": "context/summary.png",
    "references.json": "context/references.json", "canals.json": "context/canals.json",
    "aid.glb": "aid/aid.glb", "aid_in_ear.glb": "aid/aid_in_ear.glb",
    "aid_print.stl": "aid/aid_print.stl", "design.json": "aid/design.json",
}
DEFAULT_AUDIOGRAM = {250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 6000: 55}


def _check_id(pid):
    if not ID_RE.match(pid) or jobs.read_job(pid) is None:
        raise HTTPException(404, "patient not found")


@app.get("/api/health")
def health():
    from earrecon.reconstruct import WEIGHTS_DIR, AUDIOEAR_DIR
    need = ["encoder.pt", "frcn.pt", "sam2.1_b.pt"]
    return {"ok": True, "weights": {w: os.path.exists(os.path.join(WEIGHTS_DIR, w)) for w in need},
            "audioear_present": os.path.exists(os.path.join(AUDIOEAR_DIR, "FCRN.py"))}


@app.post("/api/patients", status_code=202)
async def create_patient(
    photo: UploadFile = File(..., description="side-on photo of the ear (JPEG, PNG or HEIC)"),
    box: str = Form(..., description="x0,y0,x1,y1 around the ear, in the photo's pixels (after EXIF rotation)"),
    side: str = Form("right"),
    ear_height_mm: float = Form(62.0),
    audiogram: str = Form("", description='JSON {"250": 15, ...} dB HL; blank = example audiogram'),
):
    if side not in ("right", "left"):
        raise HTTPException(422, "side must be right or left")
    if not 40 <= ear_height_mm <= 90:
        raise HTTPException(422, "ear height should be 40-90 mm")
    try:
        b = [int(float(v)) for v in box.split(",")]
        assert len(b) == 4
    except Exception:
        raise HTTPException(422, "box must be x0,y0,x1,y1")
    try:
        ag = {int(k): float(v) for k, v in (json.loads(audiogram) if audiogram.strip() else DEFAULT_AUDIOGRAM).items()}
        assert len(ag) >= 3 and all(-10 <= v <= 120 for v in ag.values())
    except Exception:
        raise HTTPException(422, "audiogram must be JSON like {\"250\": 15, \"500\": 20, ...} in dB HL")

    raw = await photo.read()
    if len(raw) > settings.max_upload_mb * 1e6:
        raise HTTPException(413, f"photo is larger than {settings.max_upload_mb:.0f} MB")
    try:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception:
        raise HTTPException(422, "could not read the photo; use JPEG, PNG or HEIC")

    pid = uuid.uuid4().hex[:12]
    d = jobs.patient_dir(pid)
    os.makedirs(d)
    img.save(os.path.join(d, "photo.jpg"), quality=95)
    request = {"box": b, "side": side, "ear_height_mm": ear_height_mm, "audiogram_db_hl": ag,
               "audiogram_is_example": not audiogram.strip()}
    jobs.write_job(pid, {"id": pid, "status": "queued", "step": None, "created_at": time.time(),
                         "request": request, "results": {}, "log": []})
    jobs.submit(jobs.run_full, pid, request)
    return {"id": pid, "status_url": f"/api/patients/{pid}"}


@app.get("/api/patients/{pid}")
def get_patient(pid: str):
    _check_id(pid)
    job = jobs.read_job(pid)
    d = jobs.patient_dir(pid)
    job["files"] = {k: f"/api/patients/{pid}/files/{k}" for k, v in FILES.items() if os.path.exists(os.path.join(d, v))}
    if os.path.exists(os.path.join(d, "waves", "runs.json")):
        job["files"]["waves"] = f"/api/patients/{pid}/waves/index.html"
    return job


WAVE_FILE_RE = re.compile(r"^[A-Za-z0-9_.+-]+\.(html|json|png|wav)$")


@app.post("/api/patients/{pid}/waves", status_code=202)
def rerun_waves(pid: str):
    _check_id(pid)
    if jobs.read_job(pid)["status"] in ("queued", "running"):
        raise HTTPException(409, "this patient is still being processed")
    jobs.submit(jobs.run_waves, pid)
    return {"id": pid, "status_url": f"/api/patients/{pid}"}


@app.get("/api/patients/{pid}/waves/{name}")
def get_wave_file(pid: str, name: str):
    """The wave viewer and its frames. Names are flat and pattern-checked, so a request can NEVER
    leave the patient's waves folder."""
    _check_id(pid)
    if not WAVE_FILE_RE.match(name):
        raise HTTPException(404, "unknown file")
    p = os.path.join(jobs.patient_dir(pid), "waves", name)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not ready")
    return FileResponse(p)


class AidDesign(BaseModel):
    throat_mm2: float = Field(1.0, ge=0.3, le=10)
    mouth_mm2: float = Field(22.2, ge=2, le=60)
    vent_diameter_mm: float = Field(0.8, ge=0, le=2.5)
    min_wall_mm: float = Field(0.6, ge=0.4, le=2)
    max_path_mm: float = Field(130, ge=20, le=300)


@app.post("/api/patients/{pid}/aid", status_code=202)
def rebuild_aid(pid: str, design: AidDesign):
    _check_id(pid)
    job = jobs.read_job(pid)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "this patient is still being processed")
    if "context" not in job.get("results", {}):
        raise HTTPException(409, "patient context is missing; create the patient again")
    if design.mouth_mm2 <= design.throat_mm2:
        raise HTTPException(422, "mouth area must be larger than throat area")
    jobs.submit(jobs.run_aid, pid, design.model_dump())
    return {"id": pid, "status_url": f"/api/patients/{pid}"}


@app.get("/api/patients/{pid}/files/{name}")
def get_file(pid: str, name: str):
    _check_id(pid)
    if name not in FILES:
        raise HTTPException(404, "unknown file")
    p = os.path.join(jobs.patient_dir(pid), FILES[name])
    if not os.path.exists(p):
        raise HTTPException(404, "file not ready")
    media = {"glb": "model/gltf-binary", "stl": "model/stl", "json": "application/json"}.get(name.rsplit(".", 1)[-1])
    return FileResponse(p, media_type=media, filename=name if name.endswith(".stl") else None)


if os.path.isdir(settings.frontend_dir):
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
