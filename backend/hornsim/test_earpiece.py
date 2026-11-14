"""Checks for the parts of earpiece.py that need no patient data.

    .venv/bin/python -m hornsim.test_earpiece      (or pytest)
"""
import math

import numpy as np

from .aid import frames
from .earpiece import SEG, inside_sweep, mouth_outline, profile_stations, ring_radii, section_on_grid, validate

GRID = np.linspace(-np.pi, np.pi, 256, endpoint=False)
KIDNEY = 1 + 0.25 * np.cos(2 * GRID) + 0.1 * np.sin(3 * GRID)          # a kidney-shaped opening


def test_shaping_never_changes_the_mouth_area():
    """The acoustic model is handed mouth_mm2; a stretched or concha-traced outline that drifted
    from it would print a horn the score never saw."""
    for conformity, stretch in ((0, 1), (1, 1), (1, 1.8), (0.5, 0.6)):
        p, _ = validate({"rim_conformity": conformity, "mouth_stretch": stretch, "mouth_mm2": 150})
        r, _ = mouth_outline(p, GRID, 15 * KIDNEY)                    # roomy: nothing clipped
        assert abs(math.pi * np.mean(r ** 2) - 150) < 1.5, (conformity, stretch)


def test_the_mouth_never_crosses_the_concha_opening():
    """A mouth past the opening (minus wall) cuts through the faceplate edge and the part falls
    apart; an oversize request must come back smaller, which build() then reports as mouth_fit."""
    p, _ = validate({"rim_conformity": 0, "mouth_stretch": 2.0, "mouth_mm2": 400})
    r, largest = mouth_outline(p, GRID, 9 * KIDNEY)
    assert np.all(r <= 9 * KIDNEY + 1e-9)
    assert math.pi * np.mean(r ** 2) < 0.95 * 400 and largest < 400


def test_bad_dials_are_all_reported_at_once():
    """A caller (the agent) fixes everything in one retry only if every problem comes back together."""
    _, issues = validate({"aim_yaw_deg": 270, "foo": 1, "rim_conformity": True})
    assert len(issues) == 3
    _, issues = validate({"flare_mid1": 0.8, "flare_mid2": 0.2})
    assert issues == ["flare_mid1 must not exceed flare_mid2 (the bore never narrows)"]
    assert validate({})[1] == []


def test_a_section_front_faces_the_face_on_both_ears():
    """A scoop meant to open toward the talker would open toward the back of the head on one side
    if the left-ear mirror were wrong."""
    t, nvec, bvec = np.array([1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, -1.0, 0])   # sweeping outward
    ang = np.linspace(0, 2 * np.pi, SEG, endpoint=False)
    for left, face in ((False, -1.0), (True, 1.0)):          # forward is -z on a right ear, +z on a left one
        S = section_on_grid([12, 8, 6, 5, 5, 5, 5, 5, 5, 5, 6, 8], left)
        j = int(np.argmax(ring_radii(t, nvec, bvec, S)))
        widest = np.cos(ang[j]) * nvec + np.sin(ang[j]) * bvec
        assert widest[2] * face > 0.9, (left, widest)


def test_inside_sweep_only_counts_what_the_tube_encloses():
    """The ray-cast inside test flagged skin 30 mm off a collector's axis as 19 mm inside, and the
    designer then chased a collision that did not exist through its whole build budget."""
    path = np.c_[np.linspace(0, 20, 41), np.zeros(41), np.zeros(41)]
    R = np.full((41, SEG), 5.0)
    q = np.array([[10, 3, 0], [10, 0, 7], [25, 0, 0], [-3, 0, 0], [10, 30, 0]], float)
    assert inside_sweep(q, path, R, frames(path), 0, 41).tolist() == [True, False, False, False, False]


def test_the_area_profile_always_reaches_the_outer_end():
    """The acoustic model radiates from the LAST area it is given. A profile sampled only at whole
    millimetres dropped the end of an 8.9 mm bore, so a 304 mm2 mouth was scored as 252."""
    along = np.array([0.0, 0.5, 1.1, 1.6, 2.1, 7.6, 8.0, 8.4, 8.9])
    assert along[profile_stations(along)].tolist() == [0.0, 1.1, 2.1, 7.6, 8.0, 8.9]
    # an end that is itself the first station past a whole millimetre is not reported twice
    along = np.array([0.0, 0.6, 1.2, 1.8, 2.4, 3.1])
    assert along[profile_stations(along)].tolist() == [0.0, 1.2, 2.4, 3.1]


if __name__ == "__main__":
    test_shaping_never_changes_the_mouth_area()
    test_the_mouth_never_crosses_the_concha_opening()
    test_bad_dials_are_all_reported_at_once()
    test_a_section_front_faces_the_face_on_both_ears()
    test_inside_sweep_only_counts_what_the_tube_encloses()
    test_the_area_profile_always_reaches_the_outer_end()
    print("ok")
