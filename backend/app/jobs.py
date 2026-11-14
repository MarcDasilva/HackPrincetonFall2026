"""Background pipeline jobs: photo -> ear mesh -> patient context -> 3D aid.

State lives on disk (DATA_DIR/patients/<id>/job.json) so the server can restart and
the frontend can poll. One worker by default: the models share one device.
"""
import json
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from .settings import settings

_pool = ThreadPoolExecutor(max_workers=settings.workers)
_write_lock = threading.Lock()

STEPS = ["ear", "context", "waves", "aid"]
WAVE_DIRECTIONS = [0, 45, 90, 135, 180]   # azimuths on the ear's side; the flat head plane cannot model the far side


def patient_dir(pid):
    return os.path.join(settings.data_dir, "patients", pid)


def read_job(pid):
    p = os.path.join(patient_dir(pid), "job.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def write_job(pid, job):
    p = os.path.join(patient_dir(pid), "job.json")
    with _write_lock:
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(job, f, indent=1, default=float)
        os.replace(tmp, p)


def _update(pid, **kw):
    job = read_job(pid) or {}
    job.update(kw)
    job["updated_at"] = time.time()
    write_job(pid, job)
    return job


def _logger(pid):
    def log(msg):
        job = read_job(pid) or {}
        job.setdefault("log", []).append(f"{time.strftime('%H:%M:%S')} {msg}")
        job["updated_at"] = time.time()
        write_job(pid, job)
    return log


def run_full(pid, request):
    """Whole pipeline for a new patient."""
    from earrecon import reconstruct as er
    from hornsim import aid, context

    d = patient_dir(pid)
    log = _logger(pid)
    try:
        _update(pid, status="running", step="ear")
        ear = er.reconstruct(os.path.join(d, "photo.jpg"), os.path.join(d, "ear"), request["box"],
                             left=request["side"] == "left", height_mm=request["ear_height_mm"], log=log)
        _update(pid, results={"ear": ear}, step="context")

        cfg = context.load_defaults()
        cfg["patient"].update({"id": pid, "ear_mesh": os.path.join(d, "ear", "ear.ply"),
                               "ear_height_mm": request["ear_height_mm"], "side": request["side"],
                               "audiogram_db_hl": {int(k): float(v) for k, v in request["audiogram_db_hl"].items()}})
        cfg["ear_world"]["landmarks_xlsx"] = er.LANDMARKS_XLSX
        ctx = context.build(cfg, os.path.join(d, "context"), log=log)
        refs = [{k: r[k] for k in ("clip", "level_db_spl", "unaided", "ceiling", "ceiling_from", "headroom", "use_in_reward")}
                for r in ctx["references_data"]]
        job = read_job(pid)
        job["results"]["context"] = {"ear_world": {k: ctx["ear_world"][k] for k in
                                                   ("bowl_volume_cc", "shell_volume_cc", "opening_area_mm2", "max_depth_mm")},
                                     "references": refs}
        job["step"] = "waves"
        write_job(pid, job)
        _waves(pid, request, log)

        _update(pid, step="aid")
        design = aid.build(os.path.join(d, "context"), os.path.join(d, "aid"), request.get("design"), log=log)
        job = read_job(pid)
        job["results"]["aid"] = design
        job.update(status="done", step=None, finished_at=time.time())
        write_job(pid, job)
    except Exception as e:  # report to the client; keep the trace in the log
        log(traceback.format_exc(limit=3))
        _update(pid, status="error", error=str(e))


def _waves(pid, request, log):
    """Wave simulation around the patient's ear. A failure here is logged, NOT fatal: the aid
    does not depend on it yet."""
    from earrecon import reconstruct as er
    from hornsim import wavesim
    d = patient_dir(pid)
    try:
        runs = wavesim.simulate(os.path.join(d, "waves"), os.path.join(d, "ear", "ear.ply"), left=request["side"] == "left",
                                azimuths=WAVE_DIRECTIONS, landmarks_xlsx=er.LANDMARKS_XLSX, log=log)
        job = read_job(pid)
        job["results"]["waves"] = [{k: r[k] for k in ("tag", "az", "el", "eardrum_peak_hz")} for r in runs]
        write_job(pid, job)
    except Exception:
        log("wave simulation failed:\n" + traceback.format_exc(limit=3))


def run_waves(pid):
    """Rerun only the wave simulation for an existing patient."""
    log = _logger(pid)
    _update(pid, status="running", step="waves")
    _waves(pid, read_job(pid)["request"], log)
    _update(pid, status="done", step=None, finished_at=time.time())


def run_aid(pid, overrides):
    """Rebuild only the aid (new design numbers) for an existing patient."""
    from hornsim import aid

    d = patient_dir(pid)
    log = _logger(pid)
    try:
        _update(pid, status="running", step="aid", error=None)
        design = aid.build(os.path.join(d, "context"), os.path.join(d, "aid"), overrides, log=log)
        job = read_job(pid)
        job["results"]["aid"] = design
        job.update(status="done", step=None, finished_at=time.time())
        write_job(pid, job)
    except Exception as e:
        log(traceback.format_exc(limit=3))
        _update(pid, status="error", error=str(e))


def submit(fn, *args):
    _pool.submit(fn, *args)
