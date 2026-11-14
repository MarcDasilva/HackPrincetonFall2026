"""hornsim.head_shape: a synthetic front photo with known size, roll and scale."""
import math

import numpy as np
import pytest

from . import head_shape as hs


def synthetic_face(px_per_mm=4.0, roll_deg=0.0, face_halfwidth_mm=68.0, W=1200, H=1600):
    """MediaPipe-like landmarks for a face drawn at a known scale. Only the indices hornsim.head_shape
    reads are placed; the rest sit at the face centre. Lower lid 22 mm above the chin-to-eye midpoint."""
    L = np.zeros((478, 3))
    eye_y, chin_y, brow_y = 0.0, -120.0, 70.0          # mm, y up, eye line at 0
    # face oval: widest (face_halfwidth) a little below the eyes, narrowing to the chin and forehead
    n = len(hs.FACE_OVAL)
    pts = {}
    for k, idx in enumerate(hs.FACE_OVAL):              # 10 (forehead) clockwise round to 109
        t = 2 * math.pi * k / n
        y = brow_y * math.cos(t) if math.cos(t) > 0 else -chin_y * math.cos(t)
        y = brow_y if k == 0 else y
        w = face_halfwidth_mm * math.sin(t)
        if y < -60:                                     # jaw tapers to the chin
            w *= max(0.15, 1 - (-60 - y) / 70)
        pts[idx] = (w, y)
    pts[hs.CHIN] = (0.0, chin_y)
    pts[hs.FOREHEAD] = (0.0, brow_y)
    for idx in hs.MIDLINE:
        pts.setdefault(idx, (0.0, -30.0))
    r_iris = hs.IRIS_MM / 2
    for (c, ring), cx in zip(hs.IRIS.values(), (-31.5, 31.5)):
        pts[c] = (cx, eye_y)
        for j, ang in zip(ring, (0, 90, 180, 270)):
            pts[j] = (cx + r_iris * math.cos(math.radians(ang)), eye_y + r_iris * math.sin(math.radians(ang)))
    for idx, cx in zip(hs.LOWER_LID, (-31.5, 31.5)):
        pts[idx] = (cx, eye_y - 5.0)
    a = math.radians(roll_deg)
    for idx, (x, y) in pts.items():
        xr, yr = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
        L[idx, 0] = (W / 2 + xr * px_per_mm) / W
        L[idx, 1] = (H / 2 - yr * px_per_mm) / H        # image y down
    return L, W, H


def test_scale_breadth_and_canal_height():
    L, W, H = synthetic_face()
    shape, rep = hs.fit(L, W, H)
    m = rep["meta"]
    assert m["ipd_mm"] == pytest.approx(63.0, abs=0.5)
    assert m["bizygomatic_mm"] == pytest.approx(2 * 68.0, rel=0.03)
    assert m["breadth_mm"] == pytest.approx(hs.EURYON_PER_BIZYGOMATIC * 2 * 68.0, rel=0.03)
    # canal at orbitale: lower lid (5 mm under the eye line) less 6 mm -> eye line 11 mm above y = 0
    assert m["eye_line_mm"] == pytest.approx(5.0 + hs.ORBITALE_BELOW_LID_MM, abs=0.3)
    assert m["chin_mm"] == pytest.approx(-120.0 + 11.0, abs=0.5)
    assert shape.canal_anchor_x() == pytest.approx(m["breadth_mm"] / 2, rel=0.05)
    assert not rep["warnings"]


def test_roll_and_scale_do_not_change_the_head():
    a, _ = hs.fit(*synthetic_face())
    b, _ = hs.fit(*synthetic_face(px_per_mm=2.5, roll_deg=12.0))
    assert abs(b.meta["roll_deg"]) == pytest.approx(12.0, abs=0.2)     # image coordinates: y down flips the sign
    y = np.linspace(-90, 120, 30)
    assert np.allclose(np.interp(y, a.y, a.w), np.interp(y, b.y, b.w), atol=1.0)


def test_jaw_follows_the_photo():
    wide, _ = hs.fit(*synthetic_face(face_halfwidth_mm=74.0))
    narrow, _ = hs.fit(*synthetic_face(face_halfwidth_mm=62.0))
    assert np.interp(-70, wide.y, wide.w) > np.interp(-70, narrow.y, narrow.w) + 4


def test_turned_face_warns():
    _, rep = hs.fit(*synthetic_face(), yaw_deg=25)
    assert any("turned" in w for w in rep["warnings"])


def test_solid_and_surface_agree():
    shape, _ = hs.fit(*synthetic_face())
    x = shape.surface_x(0.0, 0.0)
    assert shape.head_solid(np.array([x - 0.5, 0.0, 0.0]))
    assert not shape.head_solid(np.array([x + 0.5, 0.0, 0.0]))


def test_one_smooth_oval_no_jutting_face():
    shape, _ = hs.fit(*synthetic_face())
    assert np.allclose(shape.c, shape.c[0])                       # every section about the same centre
    assert np.allclose(shape.d / shape.w, hs.LENGTH_PER_BREADTH)  # same plan-view proportions
    assert np.all(np.diff(shape.w[shape.y < shape.meta["eye_line_mm"]]) >= -1e-9)   # widens monotonically up to the eyes
