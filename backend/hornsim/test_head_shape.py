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
    assert shape.canal_anchor_x() == pytest.approx(hs.BITRAGION_PER_EURYON * m["breadth_mm"] / 2, rel=0.05)   # narrower across the ears
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
    assert np.allclose(shape.d / shape.w, shape.d[len(shape.d) // 2] / shape.w[len(shape.w) // 2])   # same plan-view proportions
    yw = hs.widest_y(shape.meta["eye_line_mm"], shape.meta["crown_mm"])
    assert np.all(np.diff(shape.w[shape.y < yw]) >= -1e-9)          # widens monotonically up to its widest point


def synthetic_rows(px_per_mm=4.0, W=1200, H=1600, skull_b=150.0, crown_above_eye=100.0, n=3.0, hair_top=20.0, hair_side=6.0):
    """Hair + face silhouette rows ([y, x_left, x_right] px) for synthetic_face's geometry: under the eye line
    the face (half-width 68 mm, tapering), above it a superellipse skull wrapped in hair."""
    rows = []
    for y in np.arange(-120.0, crown_above_eye + hair_top, 1.0):          # mm, eye line at 0
        if y >= 0:
            t = min(1.0, y / (crown_above_eye + hair_top))
            half = (skull_b / 2 + hair_side) * (1 - t ** n) ** (1 / n)
        else:
            half = 68.0 * max(0.15, 1 - max(0.0, -60 - y) / 70)
        if half <= 0:
            continue
        rows.append([H / 2 - y * px_per_mm, W / 2 - half * px_per_mm, W / 2 + half * px_per_mm])
    return rows


def test_hair_outline_sets_crown_breadth_and_roundness():
    L, W, H = synthetic_face()
    shape, rep = hs.fit(L, W, H, head_rows=synthetic_rows())
    m = rep["meta"]
    assert m["segmented"]
    assert m["breadth_mm"] == pytest.approx(150.0, abs=4.0)               # temple width less 6 mm hair a side
    eye = m["eye_line_mm"]
    assert m["crown_mm"] - eye == pytest.approx(120.0 - hs.HAIR_TOP_MM, abs=3.0)   # capped under the hair top
    assert m["vault_exponent"] > 2.4                                      # fuller than an ellipse
    assert rep["overlay"]["hair_outline_px"]


def test_without_outline_the_vault_is_rounder_than_an_ellipse():
    shape, rep = hs.fit(*synthetic_face())
    m = rep["meta"]
    assert m["vault_exponent"] == hs.N_TOP_DEFAULT and not m["segmented"]
    yw = hs.widest_y(m["eye_line_mm"], m["crown_mm"])
    y_mid = yw + 0.7 * (m["crown_mm"] - yw)
    ellipse = m["breadth_mm"] / 2 * math.sqrt(1 - 0.7 ** 2)
    assert np.interp(y_mid, shape.y, shape.w) > ellipse + 3              # wider near the top: not a dome


def test_implausible_outline_is_ignored():
    L, W, H = synthetic_face()
    _, rep = hs.fit(L, W, H, head_rows=synthetic_rows(skull_b=260.0))   # e.g. a hood or a big hairstyle
    assert rep["meta"]["breadth_mm"] == pytest.approx(hs.EURYON_PER_BIZYGOMATIC * 136, rel=0.03)
    assert any("implausible" in w for w in rep["warnings"])


def test_head_narrows_below_the_eyes():
    L, W, H = synthetic_face()
    shape, rep = hs.fit(L, W, H, head_rows=synthetic_rows())
    m = rep["meta"]
    B = m["breadth_mm"]
    assert np.interp(0.0, shape.y, shape.w) == pytest.approx(hs.BITRAGION_PER_EURYON * B / 2, abs=4)   # across the ears
    face = dict(zip(m["face_outline"]["y"], m["face_outline"]["half_width"]))
    yj = min(face, key=lambda v: abs(v - (-70)))
    assert np.interp(yj, shape.y, shape.w) == pytest.approx(face[yj], abs=6)                          # follows the jawline


def test_hair_does_not_stretch_the_length():
    L, W, H = synthetic_face()
    plain, _ = hs.fit(L, W, H)
    hairy, _ = hs.fit(L, W, H, head_rows=synthetic_rows(hair_side=12.0))
    assert hairy.meta["length_mm"] == pytest.approx(plain.meta["length_mm"], abs=0.5)
