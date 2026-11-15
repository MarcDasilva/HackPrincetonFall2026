"""Head from a selfie (headrecon/head.py) and its API: runs without AudioEar; the selfie test needs
mediapipe and face_landmarker.task in WEIGHTS_DIR and skips without them.

Run from backend/: .venv/bin/python -m pytest tests -q
"""
import io
import json
import os
from urllib.parse import urljoin

import numpy as np
import pytest
import trimesh
from PIL import Image

from app import jobs, main
from headrecon import head as H
from test_api import _jpeg, _post, _touch, api  # noqa: F401  (api is the stubbed-pipeline fixture)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "selfie.jpg")
HEAD_KEYS = {"frame", "source", "dims_mm", "assumptions", "ears"}


def _has_landmarker():
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        return False
    return os.path.isfile(os.path.join(H.weights_dir(), H.MODEL))


@pytest.mark.skipif(not _has_landmarker(), reason="mediapipe or face_landmarker.task missing")
def test_selfie_gives_a_measured_closed_head(tmp_path):
    """Catches a selfie silently falling back to the average head, a pixel-to-mm slip giving a
    child-sized or giant head, and a mesh with holes the viewer shows as see-through."""
    res = H.build(str(tmp_path), FIXTURE)
    assert res["source"] == "selfie" and "note" not in res          # no clamping needed for a real adult
    info = json.load(open(tmp_path / "head.json"))
    assert HEAD_KEYS <= set(info) and info["source"] == "selfie"
    for k, (lo, hi) in H.RANGES.items():
        assert lo < info["dims_mm"][k] < hi, (k, info["dims_mm"])
    assert any("63 mm" in a for a in info["assumptions"])
    assert (tmp_path / "landmarks.jpg").is_file()
    m = trimesh.load(tmp_path / "head.glb", force="mesh")
    assert m.is_watertight and m.is_volume and 5000 <= len(m.faces) <= 10000


def test_no_selfie_still_writes_the_average_head(tmp_path):
    """Catches a patient without a selfie getting no head at all, or a stale landmarks overlay from an
    earlier selfie still being shown next to the average head."""
    _touch(str(tmp_path / "landmarks.jpg"))
    res = H.build(str(tmp_path), None)
    assert res["source"] == "average" and res["dims_mm"] == {k: H.AVERAGE[k] for k in ("breadth", "length", "height")}
    assert "selfie" in res["note"].lower()
    assert sorted(os.listdir(tmp_path)) == ["head.glb", "head.json", "head_ears.glb"]
    info = json.load(open(tmp_path / "head.json"))
    assert HEAD_KEYS <= set(info) and info["ears"] == {} and info["note"] == res["note"]


def test_unreadable_selfie_falls_back_to_the_average_head(tmp_path):
    """Catches a corrupt selfie or a missing landmarker model raising out of the head stage."""
    _touch(str(tmp_path / "selfie.jpg"), "not a jpeg")
    res = H.build(str(tmp_path / "out"), str(tmp_path / "selfie.jpg"))
    assert res["source"] == "average" and "failed" in res["note"]


@pytest.mark.parametrize("side", ["left", "right"])
def test_ear_lands_on_its_tragion_facing_out(side):
    """Catches the canal opening missing the head, a right ear stuck on the LEFT side (the head frame's
    +x), an ear facing into the head or upside down, and a mirror (det -1) that turns the mesh inside out."""
    g = H._geometry(dict(H.AVERAGE))
    trag, n = H.tragion(g)
    if side == "right":
        trag, n = trag * [-1, 1, 1], n * [-1, 1, 1]
    canal = np.array([-12.0, -6.0, 3.0])
    # A synthetic pinna in the ear frame: a bumpy disc lateral of the canal's flat head plane.
    t = np.linspace(0, 2 * np.pi, 40)
    r = np.linspace(4, 30, 8)[:, None]
    ear = np.stack([canal[0] + 2 + 8 * np.sin(t) ** 2 + 0 * r, canal[1] + r * np.sin(t), canal[2] + r * np.cos(t)], -1).reshape(-1, 3)

    M = H.ear_to_head(side, canal, trag, n)
    R, T = M[:3, :3], M[:3, 3]
    assert np.allclose(R @ canal + T, trag, atol=1e-6)
    assert np.isclose(np.linalg.det(R), 1.0)
    assert np.sign(trag[0]) == (1 if side == "left" else -1)
    assert np.allclose(R @ [1, 0, 0], n)                             # ear lateral = head outward normal
    assert (R @ [0, 1, 0])[1] > 0.95                                 # up stays up
    fwd = [0, 0, 1] if side == "left" else [0, 0, -1]               # earrecon mirrors z for a left ear
    assert (R @ fwd)[2] > 0.95                                       # the ear's front faces the nose
    assert (H.field(ear @ R.T + T, g) > 0).all()                    # the pinna sits OUTSIDE the head
    # The wave sim's flat head plane (x = canal x) is the head's tangent plane at the tragion.
    plane = np.c_[np.full(5, canal[0]), np.random.default_rng(0).normal(0, 1e-3, (5, 2)) + canal[1:]]
    assert np.allclose((plane @ R.T + T - trag) @ n, 0, atol=1e-9)
    assert np.allclose(H.gradient(trag, g)[0] / np.linalg.norm(H.gradient(trag, g)[0]), n, atol=1e-6)


def test_tragion_is_on_the_mesh_surface():
    """Catches the head mesh drifting off the field the tragions are found on — the ears would float
    off or sink into the head shown in the viewer."""
    g = H._geometry(dict(H.AVERAGE))
    m = H.head_mesh(g)
    trag, _ = H.tragion(g)
    for p in (trag, trag * [-1, 1, 1]):
        _, d, _ = trimesh.proximity.closest_point(m, [p])
        assert d[0] < 0.5


# ---------------------------------------------------------------- API

def _post_with_selfie(api, selfie=None, **data):
    files = {"photo_left": ("l.jpg", _jpeg(), "image/jpeg"), "photo_right": ("r.jpg", _jpeg(), "image/jpeg")}
    if selfie is not None:
        files["photo_selfie"] = ("s.jpg", selfie, "image/jpeg")
    return api.post("/api/patients", files=files, data=data)


def _rotated_jpeg():
    """64x48 pixels stored, EXIF orientation 6 (rotate 90 deg): shown as 48x64."""
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (64, 48), "gray").save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_selfie_is_stored_and_head_files_listed(api, tmp_path, monkeypatch):
    """Catches the selfie being dropped or saved sideways, files.head missing a contract key or listing a
    file that does not exist, and the viewer's relative fetches (head.json, ../waves/<ear>/) missing."""
    viewer = tmp_path / "head_viewer.html"
    viewer.write_text("<html>head viewer</html>")
    monkeypatch.setattr(main, "HEAD_VIEWER", str(viewer))
    pid = _post_with_selfie(api, _rotated_jpeg()).json()["id"]
    d = jobs.head_dir(pid)
    assert Image.open(os.path.join(d, "selfie.jpg")).size == (48, 64)

    job = api.get(f"/api/patients/{pid}").json()
    assert job["status"] == "done", job["log"]
    assert job["results"]["head"]["source"] == "average"           # a grey square has no face
    assert set(job["results"]["head"]) <= {"source", "dims_mm", "note"}
    base = f"/api/patients/{pid}"
    assert job["files"]["head"] == {**{k: f"{base}/files/head/{k}" for k in ("head.glb", "head_ears.glb", "head.json", "selfie.jpg")},
                                    "viewer": f"{base}/head/viewer.html"}
    for url in job["files"]["head"].values():
        assert api.get(url).status_code == 200, url
    assert api.get(job["files"]["head"]["viewer"]).text == "<html>head viewer</html>"
    assert api.get(f"{base}/files/head/head.glb").headers["content-type"] == "model/gltf-binary"

    v = job["files"]["head"]["viewer"]
    info = api.get(urljoin(v, "head.json")).json()
    assert HEAD_KEYS <= set(info) and info["frame"] == H.FRAME
    assert api.get(urljoin(v, "head_ears.glb")).status_code == 200
    assert api.get(urljoin(v, "../waves/left/runs.json")).text == "stale runs.json"
    assert api.get(urljoin(v, "../waves/right/ear.json")).text == "stale ear.json"


def test_no_selfie_still_gives_an_average_head(api):
    """Catches the selfie becoming required, or its absence costing the patient the head view."""
    pid = _post(api).json()["id"]
    job = api.get(f"/api/patients/{pid}").json()
    assert job["results"]["head"]["source"] == "average"
    assert set(job["files"]["head"]) == {"head.glb", "head_ears.glb", "head.json", "viewer"}
    assert set(job["files"]) == {"left", "right", "head"}


def test_head_routes_refuse_unknown_names(api, monkeypatch):
    """Catches a head route serving job.json, another folder's file, or a half-written head.json.tmp,
    and the viewer route serving something before the viewer exists."""
    monkeypatch.setattr(main, "HEAD_VIEWER", "/nonexistent/head_viewer.html")
    pid = _post(api).json()["id"]
    _touch(os.path.join(jobs.head_dir(pid), "head.json.tmp"))
    for path in ("/files/head/job.json", "/files/head/..%2Fjob.json", "/files/head/head.json.tmp",
                 "/files/head/ear.glb", "/head/job.json", "/head/..%2F..%2Fjob.json", "/head/aid.glb",
                 "/head/viewer.html", "/files/head/landmarks.jpg"):    # no face, so no landmarks
        assert api.get(f"/api/patients/{pid}{path}").status_code == 404, path


def test_pipeline_runs_head_after_both_ears(api, monkeypatch):
    """Catches the head stage running before an ear mesh exists (that ear would be left off the head)
    or after the slow stages (the head view would wait minutes)."""
    real, steps = H.build, []

    def build(out, selfie, ears, xlsx, log):
        api.calls.append(("head", sorted(ears)))
        steps.append(jobs.read_job(os.path.basename(os.path.dirname(out)))["step"])
        return real(out, selfie, {}, xlsx, log)

    monkeypatch.setattr(H, "build", build)
    # The stubbed reconstruct writes no ear.ply, and the head stage attaches ONLY ears that have one.
    monkeypatch.setattr(jobs, "write_skin", lambda d: (_touch(os.path.join(d, "ear_skin.glb")), _touch(os.path.join(d, "ear.ply"))))
    _post(api)
    # the head right after both meshes, BEFORE the slow lane — which opens with every ear's quick context (jobs._rest)
    assert api.calls[:4] == [("ear", "left"), ("ear", "right"), ("head", ["left", "right"]), ("context_quick", "left")]
    assert steps == ["head"]


def test_head_failing_does_not_fail_the_job(api, monkeypatch):
    """Catches a head-stage crash costing the patient both aids."""
    def boom(*a, **k):
        raise RuntimeError("head blew up")

    monkeypatch.setattr(H, "build", boom)
    pid = _post(api).json()["id"]
    job = api.get(f"/api/patients/{pid}").json()
    assert job["status"] == "done" and job["error"] is None
    assert all("score" in job["results"][e] for e in ("left", "right"))
    assert "head" not in job["results"] and "head" not in job["files"]
    assert any("head blew up" in line for line in job["log"])


def test_rerun_adds_a_head_to_an_existing_patient(api):
    """Catches the rerun ignoring a new selfie, leaving the patient stuck "running", or touching a
    single-ear legacy patient that has no head."""
    pid = _post(api).json()["id"]
    assert api.post(f"/api/patients/{pid}/head", files={"photo_selfie": ("s.jpg", _jpeg(), "image/jpeg")}).status_code == 202
    job = jobs.read_job(pid)
    assert job["status"] == "done" and job["step"] is None
    assert os.path.isfile(os.path.join(jobs.head_dir(pid), "selfie.jpg"))
    assert api.post(f"/api/patients/{pid}/head").status_code == 202  # reuses the stored selfie
    assert "selfie.jpg" in api.get(f"/api/patients/{pid}").json()["files"]["head"]

    legacy = "d60d88e7550d"
    _touch(os.path.join(jobs.patient_dir(legacy), "ear", "ear.glb"))
    jobs.write_job(legacy, {"id": legacy, "status": "done", "step": None, "results": {},
                            "request": {"box": [1, 2, 3, 4], "side": "left", "ear_height_mm": 62.0,
                                        "audiogram_db_hl": {"250": 15}}})
    assert api.post(f"/api/patients/{legacy}/head").status_code == 409
    assert "head" not in api.get(f"/api/patients/{legacy}").json()["files"]
    assert api.get(f"/api/patients/{legacy}/files/head/head.json").status_code == 404


def _front_z(g, y):
    """How far forward (+z) the head surface reaches at height y, on the midline."""
    lo, hi = 0.0, 400.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if H.field([[0.0, y, mid]], g)[0] < 0 else (lo, mid)
    return lo


@pytest.mark.parametrize("chin_forward", [-30.0, 0.0, 12.5])
def test_chin_never_juts_ahead_of_the_forehead(chin_forward):
    """Catches the beak-jaw: a fixed forward shear put every chin ~8 cm ahead of the face, and a selfie taken
    from below reads the chin as NEARER the camera (12.5 mm on a real phone selfie) — neither may push the chin
    past the forehead."""
    jaw = dict(H.AVERAGE_JAW, chin_forward=chin_forward)
    g = H._geometry(dict(H.AVERAGE), jaw)
    T = H.AVERAGE["tragion_above_chin"]
    forehead, chin = _front_z(g, 0.6 * T), _front_z(g, -0.9 * T)
    assert chin <= forehead + 1.0
    # ...and does not recede either: the measured offset (capped at -25 mm) plus a normal chin's ~15 mm.
    assert chin >= forehead + max(chin_forward, -25.0) - 20.0


def test_jaw_follows_the_measured_taper():
    """Catches a measured jaw being ignored (every head drawn with the same taper): a narrow jaw from the
    photo must make the head narrower at jaw level than a wide one, while ear level keeps the full breadth."""
    width = lambda g, y: 2 * H.tragion(g)[0][0] if y == 0 else max(  # noqa: E731
        x for x in np.linspace(0, 120, 481) if H.field([[x, y, 20.0]], g)[0] < 0)
    narrow = H._geometry(dict(H.AVERAGE), {"r": [0.2] + [0.5] * 9 + [1.0], "chin_forward": 0.0})
    wide = H._geometry(dict(H.AVERAGE), {"r": [0.6] + [0.95] * 9 + [1.0], "chin_forward": 0.0})
    y_jaw = -0.6 * H.AVERAGE["tragion_above_chin"]
    assert width(narrow, y_jaw) < width(wide, y_jaw) - 15
    assert abs(H.tragion(narrow)[0][0] - H.tragion(wide)[0][0]) < 1.0
