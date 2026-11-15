"""HTTP API for the horn-aid pipeline.

    uvicorn app.main:app --host 0.0.0.0 --port 8000      (run from backend/)

POST /api/patients            left + right photos, boxes, ear height, audiogram, optional selfie -> starts the pipeline
GET  /api/patients/{id}       status, step, log, results and files, per ear (+ files.head)
POST /api/patients/{id}/aid   rebuild every ear's aid with new design numbers
POST /api/patients/{id}/head  rebuild the head (optional new selfie)
GET  /api/patients/{id}/files/head/{name}    head files; also at /head/{name} beside /head/viewer.html
GET  /api/patients/{id}/files/{ear}/{name}   generated files (meshes, images, STL, JSON)
GET  /api/patients/{id}/waves/{ear}/{name}   wave viewer and its data
GET  /api/health
The static frontend (../frontend) is served at / when present.
"""
import io
import json
import logging
import os
import re
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from earrecon.detect import DetectError, detect_ear

from . import jobs, sim_api
from .settings import settings

app = FastAPI(title="Horn aid API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(sim_api.router)


@app.on_event("startup")
def _warm():
    # recover() ONLY when a server actually starts. At import time it ran in every process that imported this module —
    # a pytest run (before its fixtures point DATA_DIR at a temp dir) failed every LIVE job of the running server.
    jobs.recover()
    jobs.warm()

log = logging.getLogger(__name__)
ID_RE = re.compile(r"^[a-f0-9]{12}$")
FILES = {
    "ear.glb": "ear/ear.glb", "ear_skin.glb": "ear/ear_skin.glb", "ear.obj": "ear/ear.obj", "mask.png": "ear/mask.png", "depth.png": "ear/depth.png",
    "overlay.jpg": "ear/overlay.jpg", "input.jpg": "ear/input.jpg",
    "ear_world.glb": "context/ear_world.glb", "summary.png": "context/summary.png",
    "references.json": "context/references.json", "canals.json": "context/canals.json",
    "aid.glb": "aid/aid.glb", "aid_in_ear.glb": "aid/aid_in_ear.glb",
    "aid_print.stl": "aid/aid_print.stl", "design.json": "aid/design.json",
    "acoustics.json": "aid/acoustics.json", "insertion_gain.png": "aid/insertion_gain.png", "score.json": "aid/score.json",
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


def _read_photo(raw):
    if len(raw) > settings.max_upload_mb * 1e6:
        raise HTTPException(413, f"photo is larger than {settings.max_upload_mb:.0f} MB")
    try:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        return ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception:
        raise HTTPException(422, "could not read the photo; use JPEG, PNG or HEIC")


def _parse_box(box):
    if not box.strip():
        return None
    try:
        b = [int(float(v)) for v in box.split(",")]
        assert len(b) == 4
        return b
    except Exception:
        raise HTTPException(422, "box must be x0,y0,x1,y1")


def _parse_audiogram(ag_raw):
    try:
        ag = {int(k): float(v) for k, v in ag_raw.items()}
        assert len(ag) >= 3 and all(-10 <= v <= 120 for v in ag.values())
        return ag
    except Exception:
        raise HTTPException(422, "audiogram must be JSON like {\"250\": 15, \"500\": 20, ...} in dB HL")


@app.post("/api/patients", status_code=202)
async def create_patient(
    photo_left: UploadFile = File(..., description="side-on photo of the person's LEFT ear (JPEG, PNG or HEIC)"),
    photo_right: UploadFile = File(..., description="side-on photo of the person's RIGHT ear"),
    box_left: str = Form("", description="x0,y0,x1,y1 around the ear in photo_left's pixels (after EXIF rotation); blank = detected by Claude"),
    box_right: str = Form("", description="same, for photo_right"),
    ear_height_mm: float = Form(62.0),
    audiogram: str = Form("", description='JSON {"left": {"250": 15, ...}, "right": {...}} dB HL, or one {"250": 15, ...} for both ears; blank = example audiogram'),
    photo_selfie: UploadFile | None = File(None, description="optional frontal selfie for the head model; absent = average adult head"),
):
    if not 40 <= ear_height_mm <= 90:
        raise HTTPException(422, "ear height should be 40-90 mm")
    boxes = {"left": _parse_box(box_left), "right": _parse_box(box_right)}
    try:
        ag_raw = json.loads(audiogram) if audiogram.strip() else DEFAULT_AUDIOGRAM
        assert isinstance(ag_raw, dict)
    except Exception:
        raise HTTPException(422, "audiogram must be JSON like {\"250\": 15, \"500\": 20, ...} in dB HL")
    per_ear = "left" in ag_raw or "right" in ag_raw
    ags = {e: _parse_audiogram((ag_raw.get(e) or {}) if per_ear else ag_raw) for e in jobs.EARS}

    imgs = {"left": _read_photo(await photo_left.read()), "right": _read_photo(await photo_right.read())}
    selfie = await _read_selfie(photo_selfie)
    for ear, img in imgs.items():
        # The side comes from the upload field, NEVER from Claude: a blank box is the ONLY reason a photo goes to earrecon/detect.py.
        if boxes[ear] is None:
            try:
                found = await run_in_threadpool(detect_ear, img)
            except DetectError as e:
                raise HTTPException(e.status, f"{ear} ear: {e}")
            if found.get("side") != ear:
                log.warning("photo_%s: detect_ear called it a %s ear; keeping %s", ear, found.get("side"), ear)
            boxes[ear] = found["box"]

    pid = uuid.uuid4().hex[:12]
    d = jobs.patient_dir(pid)
    for ear, img in imgs.items():
        os.makedirs(os.path.join(d, ear))
        img.save(os.path.join(d, ear, "photo.jpg"), quality=95)
    _save_selfie(pid, selfie)
    request = {"ear_height_mm": ear_height_mm, "audiogram_is_example": not audiogram.strip(),
               **{e: {"box": boxes[e], "audiogram_db_hl": ags[e]} for e in jobs.EARS}}
    jobs.write_job(pid, {"id": pid, "status": "queued", "step": None, "created_at": time.time(), "ears": list(jobs.EARS),
                         "request": request, "results": {}, "log": []})
    jobs.submit(jobs.run_full, pid, request)
    return {"id": pid, "status_url": f"/api/patients/{pid}"}


@app.get("/api/patients/{pid}")
def get_patient(pid: str):
    _check_id(pid)
    job = jobs.read_job(pid)
    files = {}
    for ear in jobs.ears(job):
        d = jobs.ear_dir(pid, ear, job)
        f = {k: f"/api/patients/{pid}/files/{ear}/{k}" for k, v in FILES.items() if os.path.exists(os.path.join(d, v))}
        if os.path.exists(os.path.join(d, "waves", "runs.json")):
            f["waves"] = f"/api/patients/{pid}/waves/{ear}/index.html"
        files[ear] = f
    head = _head_files(pid, job)
    if head:
        files["head"] = head
    # Set AFTER the lookups: ear_dir reads the presence of `ears` as the two-ear folder layout.
    return {**job, "ears": jobs.ears(job), "files": files}


# ---------------------------------------------------------------- head (headrecon/head.py)

HEAD_FILES = ("head.glb", "head_ears.glb", "head.json", "landmarks.jpg", "selfie.jpg")
HEAD_VIEWER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hornsim", "head_viewer.html")


async def _read_selfie(upload):
    """The optional selfie, read like the ear photos. An empty file field counts as NO selfie."""
    if upload is None:
        return None
    raw = await upload.read()
    return _read_photo(raw) if raw else None


def _save_selfie(pid, img):
    if img is not None:
        os.makedirs(jobs.head_dir(pid), exist_ok=True)
        img.save(os.path.join(jobs.head_dir(pid), "selfie.jpg"), quality=95)


def _head_files(pid, job):
    """Only files that exist; "viewer" ONLY once head.json does — the viewer has nothing to load before.
    Legacy single-ear patients have no head."""
    if "ears" not in job:
        return {}
    d = jobs.head_dir(pid)
    f = {k: f"/api/patients/{pid}/files/head/{k}" for k in HEAD_FILES if os.path.isfile(os.path.join(d, k))}
    if "head.json" in f:
        f["viewer"] = f"/api/patients/{pid}/head/viewer.html"
    return f


def _head_file(pid, name):
    """A fixed list of names, so a request can NEVER leave head/."""
    _check_id(pid)
    if name not in HEAD_FILES or "ears" not in jobs.read_job(pid):
        raise HTTPException(404, "unknown file")
    p = os.path.join(jobs.head_dir(pid), name)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not ready")
    return FileResponse(p, media_type={"glb": "model/gltf-binary", "json": "application/json"}.get(name.rsplit(".", 1)[-1]))


@app.get("/api/patients/{pid}/files/head/{name}")
def get_head_file(pid: str, name: str):
    """Registered BEFORE /files/{ear}/{name}, which would otherwise take "head" for an ear and 404."""
    return _head_file(pid, name)


@app.get("/api/patients/{pid}/head/viewer.html")
def get_head_viewer(pid: str):
    """The CURRENT hornsim/head_viewer.html. It fetches head.json and head_ears.glb relative to this URL
    (the route below) and each ear's waves as ../waves/<ear>/ — so it MUST stay under /head/."""
    _check_id(pid)
    if not os.path.isfile(HEAD_VIEWER):
        raise HTTPException(404, "head viewer not available")
    return FileResponse(HEAD_VIEWER, media_type="text/html")


@app.get("/api/patients/{pid}/head/{name}")
def get_head_relative(pid: str, name: str):
    return _head_file(pid, name)


@app.post("/api/patients/{pid}/head", status_code=202)
async def rerun_head(pid: str, photo_selfie: UploadFile | None = File(None)):
    """Rebuild only the head, e.g. to give an existing patient one. A new selfie replaces the old one;
    without one the stored selfie, if any, is reused."""
    _check_id(pid)
    job = jobs.read_job(pid)
    if "ears" not in job:
        raise HTTPException(409, "single-ear patients have no head; create the patient again")
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "this patient is still being processed")
    _save_selfie(pid, await _read_selfie(photo_selfie))
    jobs._update(pid, status="queued", step="head")   # so a poll right after this sees it pending
    jobs.submit(jobs.run_head, pid, job["status"])
    return {"id": pid, "status_url": f"/api/patients/{pid}"}


WAVE_FILE_RE = re.compile(r"^[A-Za-z0-9_.+-]+\.(html|json|png|wav)$")
WAVE_VIEWER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hornsim", "wave_viewer.html")


@app.post("/api/patients/{pid}/waves", status_code=202)
def rerun_waves(pid: str):
    _check_id(pid)
    if jobs.read_job(pid)["status"] in ("queued", "running"):
        raise HTTPException(409, "this patient is still being processed")
    jobs.submit(jobs.run_waves, pid)
    return {"id": pid, "status_url": f"/api/patients/{pid}"}


def _wave_file(d, name):
    """Names are flat and pattern-checked, so a request can NEVER leave the waves folder."""
    if not WAVE_FILE_RE.match(name):
        raise HTTPException(404, "unknown file")
    p = os.path.join(d, "waves", name)
    if not os.path.isfile(p):
        raise HTTPException(404, "file not ready")
    # The patient's index.html is a copy taken at simulation time — serve the CURRENT viewer instead.
    return FileResponse(WAVE_VIEWER if name == "index.html" else p)


def _ear_dir(pid, ear):
    _check_id(pid)
    d = jobs.ear_dir(pid, ear)
    if d is None:
        raise HTTPException(404, "this patient has no such ear")
    return d


@app.get("/api/patients/{pid}/waves/{ear}/{name}")
def get_ear_wave_file(pid: str, ear: str, name: str):
    """The wave viewer and its frames. The viewer fetches ear.json, runs.json and frames by RELATIVE
    URL, so they MUST stay under the same /waves/{ear}/ path as index.html."""
    return _wave_file(_ear_dir(pid, ear), name)


@app.get("/api/patients/{pid}/waves/{name}")
def get_wave_file(pid: str, name: str):
    """Legacy flat route: the patient folder's own waves/, which only single-ear patients have."""
    _check_id(pid)
    return _wave_file(jobs.patient_dir(pid), name)


class AidDesign(BaseModel):
    # Bounds are what hornsim.aid can route in some ear; a design that misses this ear fails its job with the reason.
    # throat: the bore passes the canal tip with a wall left, so at most pi * (7.5 / 2 - tip clearance - wall)^2:
    # 20.4 mm2 with the defaults, 31 mm2 with the snuggest tip (0.2) and thinnest wall (0.4).
    # A throat above ~3 mm2 leaves no room for a vent beside it: use vent 0 (the bore vents the canal itself).
    throat_mm2: float = Field(1.0, ge=0.3, le=31)
    mouth_mm2: float = Field(22.2, ge=2, le=200)
    vent_diameter_mm: float = Field(0.8, ge=0, le=2.5)      # 0 = no vent
    min_wall_mm: float = Field(0.6, ge=0.4, le=2)
    max_path_mm: float = Field(130, ge=20, le=300)
    tip_clearance_mm: float = Field(0.6, ge=0.2, le=1.5)    # gap between the canal tip and the assumed canal wall


@app.post("/api/patients/{pid}/aid", status_code=202)
def rebuild_aid(pid: str, design: AidDesign):
    _check_id(pid)
    job = jobs.read_job(pid)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "this patient is still being processed")
    if not any("context" in jobs.ear_results(job, e) for e in jobs.ears(job)):
        raise HTTPException(409, "patient context is missing; create the patient again")
    if design.mouth_mm2 <= design.throat_mm2:
        raise HTTPException(422, "mouth area must be larger than throat area")
    jobs._update(pid, status="queued", step="aid", error=None)   # so a poll right after this sees it pending
    jobs.submit(jobs.run_aid, pid, design.model_dump())
    return {"id": pid, "status_url": f"/api/patients/{pid}"}


def _file(d, name):
    if name not in FILES:
        raise HTTPException(404, "unknown file")
    p = os.path.join(d, FILES[name])
    if not os.path.exists(p):
        raise HTTPException(404, "file not ready")
    media = {"glb": "model/gltf-binary", "stl": "model/stl", "json": "application/json"}.get(name.rsplit(".", 1)[-1])
    return FileResponse(p, media_type=media, filename=name if name.endswith(".stl") else None)


@app.get("/api/patients/{pid}/files/{ear}/{name}")
def get_ear_file(pid: str, ear: str, name: str):
    return _file(_ear_dir(pid, ear), name)


@app.get("/api/patients/{pid}/files/{name}")
def get_file(pid: str, name: str):
    """Legacy flat route (backend/preview, frontend/app/demo): the patient folder itself, which only
    single-ear patients fill."""
    _check_id(pid)
    return _file(jobs.patient_dir(pid), name)


if os.path.isdir(settings.frontend_dir):
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
