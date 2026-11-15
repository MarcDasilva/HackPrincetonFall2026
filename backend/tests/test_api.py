"""HTTP API for two-ear patients, with every heavy stage stubbed: runs without weights or AudioEar.

Run from backend/: .venv/bin/python -m pytest tests -q
"""
import io
import json
import os
import sys
import types

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import earrecon
from app import jobs, main
from app.settings import settings
from hornsim import acoustics, aid, context, score, wavesim


def _ear_of(path):
    return "left" if f"{os.sep}left{os.sep}" in path else "right" if f"{os.sep}right{os.sep}" in path else "root"


def _touch(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


@pytest.fixture
def api(tmp_path, monkeypatch):
    """TestClient on a temp DATA_DIR. `calls` records (stage, ear) in run order; add an ear to
    `fail_context` to make its context stage raise."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(tmp_path / "patients")
    calls, fail_context = [], set()

    def reconstruct(photo, out, box, left, height_mm, log):
        assert os.path.isfile(photo)
        calls.append(("ear", _ear_of(out + os.sep)))
        _touch(os.path.join(out, "ear.glb"), f"glb {'left' if left else 'right'}")
        return {"side": "left" if left else "right", "box": box}

    er = types.SimpleNamespace(reconstruct=reconstruct, LANDMARKS_XLSX="landmarks.xlsx")
    monkeypatch.setitem(sys.modules, "earrecon.reconstruct", er)      # the real one needs AudioEar
    monkeypatch.setattr(earrecon, "reconstruct", er, raising=False)
    monkeypatch.setattr(jobs, "write_skin", lambda d: _touch(os.path.join(d, "ear_skin.glb")))

    def build_context(cfg, out, log, stop_when_ready=False):
        ear = _ear_of(out + os.sep)
        calls.append(("context_quick" if stop_when_ready else "context", ear))
        assert cfg["patient"]["side"] == ear
        if ear in fail_context:
            raise RuntimeError("context blew up")
        _touch(os.path.join(out, "canals.json"), "{}")
        return {"references_data": [], "ear_world": dict.fromkeys(
            ("bowl_volume_cc", "shell_volume_cc", "opening_area_mm2", "max_depth_mm"), 1.0)}

    def simulate(out, ply, left, azimuths, landmarks_xlsx, log, **_display):   # tones_hz, dx: jobs._waves display settings
        calls.append(("waves", _ear_of(out + os.sep)))
        for name in ("index.html", "runs.json", "ear.json", "az0_p.png"):
            _touch(os.path.join(out, name), f"stale {name}")
        return [{"tag": "az0", "az": 0, "el": 0, "eardrum_peak_hz": 3000.0}]

    def build_aid(ctx, out, overrides, log):
        calls.append(("aid", _ear_of(out + os.sep)))
        _touch(os.path.join(out, "aid.glb"), f"aid {_ear_of(out + os.sep)}")
        return {"throat_mm2": 1.0, "acoustic": "dropped"}

    monkeypatch.setattr(context, "build", build_context)
    monkeypatch.setattr(wavesim, "simulate", simulate)
    monkeypatch.setattr(aid, "build", build_aid)
    monkeypatch.setattr(acoustics, "evaluate", lambda d, log: {"summary": {"gain_db": 10}})
    monkeypatch.setattr(score, "score", lambda d, log: {"score": 0.5})
    monkeypatch.setattr(main, "detect_ear", lambda img: {"box": [1, 2, 30, 40], "side": "right"})
    monkeypatch.setattr(jobs, "submit", lambda fn, *a: fn(*a))
    client = TestClient(main.app)
    client.calls, client.fail_context = calls, fail_context
    return client


def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "gray").save(buf, "JPEG")
    return buf.getvalue()


def _post(api, **data):
    files = {"photo_left": ("l.jpg", _jpeg(), "image/jpeg"), "photo_right": ("r.jpg", _jpeg(), "image/jpeg")}
    return api.post("/api/patients", files=files, data=data)


def test_two_photos_build_both_ears_meshes_first(api):
    """Catches the right ear reusing the left photo or side, and the slow stages delaying the second
    ear's 3D model the frontend shows while processing."""
    r = _post(api, box_left="5,6,50,40", audiogram=json.dumps({"left": {"250": 10, "500": 20, "1000": 30},
                                                               "right": {"250": 40, "500": 50, "1000": 60}}))
    assert r.status_code == 202
    pid = r.json()["id"]
    d = jobs.patient_dir(pid)
    for ear in ("left", "right"):
        assert os.path.isfile(os.path.join(d, ear, "photo.jpg"))
    assert not os.path.exists(os.path.join(d, "photo.jpg"))

    job = jobs.read_job(pid)
    assert job["ears"] == ["left", "right"]
    assert job["status"] == "done" and job["step"] is None, job["log"]
    req = job["request"]
    assert req["ear_height_mm"] == 62 and req["audiogram_is_example"] is False
    assert req["left"]["box"] == [5, 6, 50, 40] and req["right"]["box"] == [1, 2, 30, 40]   # only the blank box is detected
    assert req["left"]["audiogram_db_hl"] == {"250": 10, "500": 20, "1000": 30}
    assert req["right"]["audiogram_db_hl"] == {"250": 40, "500": 50, "1000": 60}
    for ear in ("left", "right"):
        res = job["results"][ear]
        assert res["ear"]["side"] == ear
        assert {"context", "waves", "aid", "acoustics", "score"} <= set(res)
        assert "acoustic" not in res["aid"]

    # three passes over the ears (jobs._rest): EVERY ear's quick context first — what the sims need — then the waves,
    # then the references and the aid. Ear by ear, the second ear's sims waited behind the first ear's waves. An ear's
    # references and aid run in a thread beside the next ear's waves, so ONLY the order within each lane is fixed.
    c = api.calls
    assert c[:5] == [("ear", "left"), ("ear", "right"), ("context_quick", "left"), ("context_quick", "right"), ("waves", "left")]
    assert sorted(c[5:]) == sorted([("waves", "right"), ("context", "left"), ("aid", "left"), ("context", "right"), ("aid", "right")])
    for ear in ("left", "right"):
        assert c.index(("waves", ear)) < c.index(("context", ear)) < c.index(("aid", ear))


def test_flat_audiogram_and_blank_audiogram_cover_both_ears(api):
    """Catches a one-ear audiogram (or none) leaving the other ear without thresholds."""
    pid = _post(api, audiogram=json.dumps({"250": 15, "500": 20, "1000": 30})).json()["id"]
    req = jobs.read_job(pid)["request"]
    assert req["left"]["audiogram_db_hl"] == req["right"]["audiogram_db_hl"] == {"250": 15, "500": 20, "1000": 30}
    req = jobs.read_job(_post(api).json()["id"])["request"]
    assert req["audiogram_is_example"] is True and req["left"]["audiogram_db_hl"] == req["right"]["audiogram_db_hl"]


def test_missing_right_photo_is_rejected(api):
    """Catches a one-photo upload starting a patient with only one ear."""
    r = api.post("/api/patients", files={"photo_left": ("l.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 422
    assert os.listdir(os.path.join(settings.data_dir, "patients")) == []


def test_per_ear_audiogram_missing_one_ear_is_rejected(api):
    """Catches a per-ear audiogram silently leaving one ear empty."""
    r = _post(api, audiogram=json.dumps({"left": {"250": 10, "500": 20, "1000": 30}}))
    assert r.status_code == 422


def test_files_are_grouped_by_ear_and_cannot_escape(api):
    """Catches one ear's mesh being served for the other, the viewer's relative fetches missing their
    ear, a stale copied viewer being served, and a path leaving the patient folder."""
    pid = _post(api).json()["id"]
    files = api.get(f"/api/patients/{pid}").json()["files"]
    assert set(files) == {"left", "right", "head"}             # head: the average head, no selfie given
    assert files["left"]["ear.glb"] == f"/api/patients/{pid}/files/left/ear.glb"
    assert files["right"]["waves"] == f"/api/patients/{pid}/waves/right/index.html"
    assert "summary.png" not in files["left"]                    # only files that exist

    assert api.get(files["right"]["aid.glb"]).text == "aid right"
    assert api.get(files["left"]["ear.glb"]).text == "glb left"
    viewer = api.get(files["left"]["waves"])
    assert viewer.status_code == 200 and viewer.text == open(main.WAVE_VIEWER).read()
    assert api.get(f"/api/patients/{pid}/waves/left/runs.json").text == "stale runs.json"

    for path in (f"/files/center/ear.glb", f"/files/left/job.json", f"/files/left/..%2Fjob.json",
                 f"/waves/left/..%2F..%2Fjob.json", f"/waves/left/job.json", f"/waves/up/index.html",
                 f"/files/ear.glb", f"/waves/index.html"):           # flat routes: root holds nothing for two ears
        assert api.get(f"/api/patients/{pid}{path}").status_code == 404, path


def test_legacy_single_ear_patient_is_served_under_its_side(api):
    """Catches patients made before two-ear support vanishing from the dashboard or old clients."""
    pid = "d60d88e7550d"
    d = jobs.patient_dir(pid)
    for p in ("ear/ear.glb", "waves/runs.json", "waves/index.html", "waves/ear.json"):
        _touch(os.path.join(d, p), f"legacy {p}")
    jobs.write_job(pid, {"id": pid, "status": "done", "step": None, "results": {"context": {}},
                         "request": {"box": [1, 2, 3, 4], "side": "left", "ear_height_mm": 62.0,
                                     "audiogram_db_hl": {"250": 15}, "audiogram_is_example": False}})
    job = api.get(f"/api/patients/{pid}").json()
    assert job["ears"] == ["left"]
    assert job["files"] == {"left": {"ear.glb": f"/api/patients/{pid}/files/left/ear.glb",
                                     "waves": f"/api/patients/{pid}/waves/left/index.html"}}
    assert api.get(job["files"]["left"]["ear.glb"]).text == "legacy ear/ear.glb"
    assert api.get(f"/api/patients/{pid}/waves/left/ear.json").text == "legacy waves/ear.json"
    assert api.get(f"/api/patients/{pid}/files/right/ear.glb").status_code == 404
    assert api.get(f"/api/patients/{pid}/files/ear.glb").text == "legacy ear/ear.glb"
    assert api.get(f"/api/patients/{pid}/waves/index.html").text == open(main.WAVE_VIEWER).read()

    assert api.post(f"/api/patients/{pid}/aid", json={}).status_code == 202
    job = jobs.read_job(pid)
    assert job["status"] == "done" and "score" in job["results"] and "left" not in job["results"]
    assert api.calls == [("aid", "root")]


def test_one_ear_failing_still_finishes_the_other(api):
    """Catches one bad ear photo costing the patient both aids."""
    api.fail_context.add("left")
    pid = _post(api).json()["id"]
    job = jobs.read_job(pid)
    assert job["status"] == "done"
    assert job["results"]["left"]["error"] == "context blew up"
    assert "score" in job["results"]["right"] and "error" not in job["results"]["right"]
    assert ("aid", "right") in api.calls and ("aid", "left") not in api.calls

    api.fail_context.add("right")
    job = jobs.read_job(_post(api).json()["id"])
    assert job["status"] == "error" and "left" in job["error"] and "right" in job["error"]


def test_aid_and_waves_reruns_cover_both_ears(api):
    """Catches a design change or wave rerun updating only one of the patient's ears."""
    pid = _post(api).json()["id"]
    api.calls.clear()
    assert api.post(f"/api/patients/{pid}/aid", json={"throat_mm2": 2}).status_code == 202
    assert api.post(f"/api/patients/{pid}/waves").status_code == 202
    assert api.calls == [("aid", "left"), ("aid", "right"), ("waves", "left"), ("waves", "right")]
    assert jobs.read_job(pid)["status"] == "done"


def test_sim_router_serves_the_worse_ear_of_a_two_ear_patient(api):
    """Catches the dashboard's design landing in the better ear, or in a patient folder that holds no ear."""
    pid = _post(api, audiogram=json.dumps({"left": {"250": 10, "500": 20, "1000": 30}, "right": {"250": 40, "500": 50, "1000": 60}})).json()["id"]
    for ear in ("left", "right"):
        _touch(os.path.join(jobs.ear_dir(pid, ear), "context", "context.json"), "{}")
        _touch(os.path.join(jobs.ear_dir(pid, ear), "scene_design", "status.json"), json.dumps({"status": "done", "ear": ear}))
    assert api.get(f"/api/sim/patients/{pid}/design").json()["ear"] == "right"
    assert api.get(f"/api/sim/patients/{pid}/design?ear=left").json()["ear"] == "left"


def test_ear_and_head_stages_never_wait_behind_another_runs_simulations(monkeypatch):
    """Catches a new upload sitting on "Processing…" for ~12 minutes: the fast stages (ear meshes, head) must go
    to their OWN lane, and only the slow stages (context, waves, aid) share the one-at-a-time lane."""
    lanes = []
    monkeypatch.setattr(jobs, "_fast", types.SimpleNamespace(submit=lambda fn, *a: lanes.append(("fast", fn.__name__))))
    monkeypatch.setattr(jobs, "_pool", types.SimpleNamespace(submit=lambda fn, *a: lanes.append(("slow", fn.__name__))))
    for fn in (jobs.run_full, jobs.run_head, jobs._rest, jobs.run_waves, jobs.run_aid):
        jobs.submit(fn, "abc123abc123")
    assert lanes == [("fast", "run_full"), ("fast", "run_head"), ("slow", "_rest"), ("slow", "run_waves"), ("slow", "run_aid")]


def test_restart_fails_runs_it_cut_off(tmp_path, monkeypatch):
    """Catches runs stranded by a server restart: their threads are gone, so "queued"/"running" on disk would
    keep a polling screen on "Processing…" forever. Finished runs are left alone."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    for pid, status in (("aaaaaaaaaaaa", "queued"), ("bbbbbbbbbbbb", "running"), ("cccccccccccc", "done")):
        os.makedirs(tmp_path / "patients" / pid)
        jobs.write_job(pid, {"id": pid, "status": status, "step": "left:waves" if status == "running" else None})
    jobs.recover()
    assert [jobs.read_job(p)["status"] for p in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc")] == ["error", "error", "done"]
    assert "restarted" in jobs.read_job("bbbbbbbbbbbb")["error"]


def test_importing_the_app_never_touches_live_runs(tmp_path, monkeypatch):
    """Catches recover() at import time: a test run (or any script) importing app.main marked the RUNNING server's live
    jobs "server restarted" and killed a real end-to-end run mid-validation. Only a starting server may do that."""
    import importlib
    from app import main
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    os.makedirs(tmp_path / "patients" / "dddddddddddd")
    jobs.write_job("dddddddddddd", {"id": "dddddddddddd", "status": "running", "step": "left:waves"})
    importlib.reload(main)
    assert jobs.read_job("dddddddddddd")["status"] == "running"

