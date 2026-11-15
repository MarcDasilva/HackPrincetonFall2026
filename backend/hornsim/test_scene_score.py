"""hornsim.scene_score matches frontend lib/hearing.ts (values computed by the TS sceneDeficit)."""
import numpy as np
import pytest

from . import scene_score as ss

AG = {250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 6000: 55}
G1 = np.array([np.sin(i) * 4 for i in range(18)])
G2 = np.array([-i * 0.5 for i in range(18)])


@pytest.mark.parametrize("sources,gains,expected", [
    ([{"role": "talker", "level_db": 65}], [G1], 0.500589),
    ([{"role": "talker", "level_db": 65}, {"role": "babble", "level_db": 62}], [G1, G2], 0.378565),
    ([{"role": "alarm", "level_db": 65, "target": True}, {"role": "babble", "level_db": 62}], [G1, G2], 0.573794),
    ([{"role": "birds", "level_db": 50, "target": True}, {"role": "traffic", "level_db": 58}], [G2, G1], 0.0),
    ([{"role": "music", "level_db": 100, "target": True}], [G1], 0.985014),
])
def test_matches_browser(sources, gains, expected):
    assert ss.scene_index(sources, gains, AG) == pytest.approx(expected, abs=1e-6)


def test_no_target_no_score():
    assert ss.scene_index([{"role": "babble", "level_db": 60}], [G1], AG) is None
