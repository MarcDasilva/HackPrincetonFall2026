"""Background pipeline jobs: photo -> ear mesh -> patient context -> 3D aid, per ear.

A patient has TWO ears: DATA_DIR/patients/<id>/{left,right}/ each hold photo.jpg, ear/, context/,
waves/ and aid/, and job.json keeps per-ear results under results.<ear>. head/ holds the rough head
both ears are attached to (results.head). Legacy single-ear patients
(request.side, no `ears`) keep everything in the patient folder itself — ear_dir() is the ONE place
that resolves either layout.

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
# The FAST lane: ear meshes and the head take seconds and are what the patient watches. Behind one queue they
# waited out every earlier run's ~12-minute simulations, and the screen sat on "Processing…" with nothing to show.
_fast = ThreadPoolExecutor(max_workers=1)
_write_lock = threading.Lock()

EARS = ("left", "right")
STEPS = ["ear", "context", "waves", "aid", "acoustics", "score"]   # a two-ear job reports "<ear>:<step>"; "head" runs between ear and context
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


def ears(job):
    """The ears a patient has. Legacy single-ear jobs carry `request.side` and no `ears`."""
    return job.get("ears") or [job["request"]["side"]]


def ear_dir(pid, ear, job=None):
    """Folder holding one ear's photo.jpg, ear/, context/, waves/ and aid/, or None when the patient
    has no such ear. A legacy patient's ONE ear lives in the patient folder itself."""
    job = job or read_job(pid) or {}
    if ear not in ("left", "right") or not job.get("request") or ear not in ears(job):
        return None
    return os.path.join(patient_dir(pid), ear) if "ears" in job else patient_dir(pid)


def ear_request(job, ear):
    """One ear's request in the flat shape the stages read (box, side, ear_height_mm, audiogram_db_hl)."""
    req = job["request"]
    if "ears" not in job:
        return req
    return {**req[ear], "side": ear, "ear_height_mm": req["ear_height_mm"], "design": req.get("design")}


def ear_results(job, ear):
    res = job.setdefault("results", {})
    return res.setdefault(ear, {}) if "ears" in job else res


def _set(pid, ear, /, step=None, **results):
    """Store results for one ear (None deletes the key) and, when given, the step it is on."""
    job = read_job(pid)
    res = ear_results(job, ear)
    for k, v in results.items():
        if v is None:
            res.pop(k, None)
        else:
            res[k] = v
    if step:
        job["step"] = f"{ear}:{step}" if "ears" in job else step
    job["updated_at"] = time.time()
    write_job(pid, job)


def _ear_logger(log, ear, job):
    return (lambda msg: log(f"{ear}: {msg}")) if "ears" in job else log


def write_skin(ear_dir):
    """ear_skin.glb: the ear as shown everywhere (homepage, wave viewer, demo). See ear_world.skin."""
    import trimesh
    from hornsim import ear_world
    s, _ = ear_world.skin(trimesh.load(os.path.join(ear_dir, "ear.ply"), process=False))
    s.export(os.path.join(ear_dir, "ear_skin.glb"))


def _context(pid, ear, request, log):
    from earrecon import reconstruct as er
    from hornsim import context

    d = ear_dir(pid, ear)
    _set(pid, ear, step="context")
    cfg = context.load_defaults()
    cfg["patient"].update({"id": pid, "ear_mesh": os.path.join(d, "ear", "ear.ply"),
                           "ear_height_mm": request["ear_height_mm"], "side": ear,
                           "audiogram_db_hl": {int(k): float(v) for k, v in request["audiogram_db_hl"].items()}})
    cfg["ear_world"]["landmarks_xlsx"] = er.LANDMARKS_XLSX
    ctx = context.build(cfg, os.path.join(d, "context"), log=log)
    refs = [{k: r[k] for k in ("clip", "level_db_spl", "unaided", "ceiling", "ceiling_from", "headroom", "use_in_reward")}
            for r in ctx["references_data"]]
    _set(pid, ear, context={"ear_world": {k: ctx["ear_world"][k] for k in
                                          ("bowl_volume_cc", "shell_volume_cc", "opening_area_mm2", "max_depth_mm")},
                            "references": refs})


def _aid(pid, ear, overrides, log):
    """Aid geometry, then its acoustics, then its score for this ear."""
    from hornsim import acoustics, aid, score

    d = ear_dir(pid, ear)
    _set(pid, ear, step="aid", error=None)
    design = aid.build(os.path.join(d, "context"), os.path.join(d, "aid"), overrides, log=log)
    _set(pid, ear, step="acoustics", aid={k: v for k, v in design.items() if k != "acoustic"})
    ac = acoustics.evaluate(d, log=log)
    _set(pid, ear, step="score", acoustics=ac["summary"])
    _set(pid, ear, score=score.score(d, log=log))


def _finish(pid, failed, n):
    """Done if ANY ear finished; error only when every ear failed."""
    if len(failed) < n:
        _update(pid, status="done", step=None, error=None, finished_at=time.time())
    else:
        _update(pid, status="error", step=None, error="; ".join(f"{e}: {m}" for e, m in failed.items()))


def run_full(pid, request):
    """Whole pipeline for a new two-ear patient, on the FAST lane: both ear meshes and the head (seconds — the
    frontend shows them at once), then the slow stages are handed to the one-at-a-time lane (_rest)."""
    from earrecon import reconstruct as er

    log = _logger(pid)
    job = read_job(pid)
    _update(pid, status="running")
    try:
        for ear in ears(job):
            d = ear_dir(pid, ear, job)
            _set(pid, ear, step="ear")
            mesh = er.reconstruct(os.path.join(d, "photo.jpg"), os.path.join(d, "ear"), request[ear]["box"],
                                  left=ear == "left", height_mm=request["ear_height_mm"], log=_ear_logger(log, ear, job))
            write_skin(os.path.join(d, "ear"))
            _set(pid, ear, ear=mesh)
    except Exception as e:  # without both meshes there is no patient; report to the client, keep the trace in the log
        log(traceback.format_exc(limit=3))
        _update(pid, status="error", step=None, error=str(e))
        return

    _head(pid, log)
    _update(pid, step="waiting")         # until the slow lane is free (another run's simulations may be ahead)
    submit(_rest, pid)


def _rest(pid):
    """Context, waves and the aid for each ear — the slow stages, one patient at a time."""
    log = _logger(pid)
    job = read_job(pid)
    failed = {}
    for ear in ears(job):
        elog = _ear_logger(log, ear, job)
        try:
            req = ear_request(job, ear)
            _context(pid, ear, req, elog)
            _waves(pid, ear, elog)
            _aid(pid, ear, req.get("design"), elog)
        except Exception as e:  # one ear failing must NOT cost the patient the other ear
            elog(traceback.format_exc(limit=3))
            _set(pid, ear, error=str(e))
            failed[ear] = str(e)
    _finish(pid, failed, len(ears(job)))


def _waves(pid, ear, log):
    """Wave simulation around one ear. A failure here is logged, NOT fatal: the aid
    does not depend on it yet."""
    from earrecon import reconstruct as er
    from hornsim import wavesim
    d = ear_dir(pid, ear)
    _set(pid, ear, step="waves")
    try:
        runs = wavesim.simulate(os.path.join(d, "waves"), os.path.join(d, "ear", "ear.ply"), left=ear == "left",
                                azimuths=WAVE_DIRECTIONS, landmarks_xlsx=er.LANDMARKS_XLSX, log=log)
        _set(pid, ear, waves=[{k: r[k] for k in ("tag", "az", "el", "eardrum_peak_hz")} for r in runs])
    except Exception:
        log("wave simulation failed:\n" + traceback.format_exc(limit=3))


def head_dir(pid):
    """head/: selfie.jpg (optional upload), landmarks.jpg, head.glb, head_ears.glb, head.json."""
    return os.path.join(patient_dir(pid), "head")


def _head(pid, log):
    """Rough head from the selfie (or the average head) with every reconstructed ear attached. NEVER
    raises: the head is display only, so a failure here is logged and the ears carry on."""
    _update(pid, step="head")
    try:
        from headrecon import head
        try:
            from earrecon.reconstruct import LANDMARKS_XLSX as xlsx
        except Exception:  # the head stage does not need AudioEar's networks, only its landmark table
            xlsx = None
        job = read_job(pid)
        found = {e: ear_dir(pid, e, job) for e in ears(job)}
        found = {e: d for e, d in found.items() if os.path.isfile(os.path.join(d, "ear", "ear.ply"))}
        d = head_dir(pid)
        selfie = os.path.join(d, "selfie.jpg")
        res = head.build(d, selfie if os.path.isfile(selfie) else None, found, xlsx, log=log)
        job = read_job(pid)
        job.setdefault("results", {})["head"] = res
        write_job(pid, job)
    except Exception:
        log("head failed:\n" + traceback.format_exc(limit=3))


def run_head(pid, status):
    """Rerun only the head stage; the job then returns to the `status` it had before."""
    _update(pid, status="running")
    _head(pid, _logger(pid))
    _update(pid, status=status, step=None)


def run_waves(pid):
    """Rerun only the wave simulation, for every ear the patient has."""
    log = _logger(pid)
    job = _update(pid, status="running")
    for ear in ears(job):
        _waves(pid, ear, _ear_logger(log, ear, job))
    _update(pid, status="done", step=None, finished_at=time.time())


def run_aid(pid, overrides):
    """Rebuild only the aid (new design numbers), for every ear the patient has."""
    log = _logger(pid)
    job = read_job(pid)
    _update(pid, status="running", error=None)
    failed = {}
    for ear in ears(job):
        elog = _ear_logger(log, ear, job)
        try:
            _aid(pid, ear, overrides, elog)
        except Exception as e:
            elog(traceback.format_exc(limit=3))
            if "ears" in job:
                _set(pid, ear, error=str(e))
            failed[ear] = str(e)
    _finish(pid, failed, len(ears(job)))


def submit(fn, *args):
    (_fast if fn in (run_full, run_head) else _pool).submit(fn, *args)


def warm(log=print):
    """Import every pipeline module ONCE, on the main thread, before any job runs. With two lanes, one thread's
    first `from hornsim import context` raced the other's earrecon/headrecon imports and the slow lane hung on
    "waiting" for good (Python's per-module import locks can deadlock across threads)."""
    import importlib
    for m in ("earrecon.reconstruct", "headrecon.head", "hornsim.context", "hornsim.wavesim", "hornsim.aid",
              "hornsim.acoustics", "hornsim.score", "hornsim.ear_world", "hornsim.scoring"):
        try:
            importlib.import_module(m)
        except Exception as e:  # a missing optional model must not stop the server; the stage reports it
            log(f"warm: {m} not imported ({type(e).__name__}: {e})")


def recover():
    """Runs a server restart cut off stay "queued"/"running" on disk FOREVER — their threads are gone, and a
    screen polling one spins on "Processing…". Mark them failed at startup so the client says so instead."""
    root = os.path.join(settings.data_dir, "patients")
    for pid in os.listdir(root) if os.path.isdir(root) else []:
        job = read_job(pid)
        if job and job.get("status") in ("queued", "running"):
            _update(pid, status="error", step=None, error="The server restarted before this run finished. Send it again.")
