"""hornsim.scene_spec: the vocabulary the research step builds scene sets from."""
import os
import re

import pytest

from . import scene_spec as ss

FRONTEND_SOUNDS = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "app", "sim", "lib", "sounds.ts")


def test_frontend_registry_has_the_same_roles():
    src = open(FRONTEND_SOUNDS).read()
    body = src[src.index("export const SOUNDS = {"):src.index("} as const;")]
    roles = set(re.findall(r"^\s{2}(\w+): \{", body, re.M))
    assert roles == set(ss.SOUNDS), "add a sound in BOTH backend/hornsim/scene_spec.py and frontend app/sim/lib/sounds.ts"


def test_validate_fills_defaults_and_refuses_unknown_roles():
    s = ss.validate_scene_set({"source": "t", "scenes": [{"name": "A", "sources": [{"role": "alarm", "az": 450}]}]})
    src = s["scenes"][0]["sources"][0]
    assert src["az"] == 90 and src["target"] is True and src["el"] == ss.SOUNDS["alarm"]["el"]
    with pytest.raises(ValueError, match="role 'kazoo'"):
        ss.validate_scene_set({"scenes": [{"name": "B", "sources": [{"role": "kazoo"}]}]})
    with pytest.raises(ValueError, match="level_db"):
        ss.validate_scene_set({"scenes": [{"name": "C", "sources": [{"role": "talker", "level_db": 140}]}]})


def test_every_library_scene_is_valid():
    ss.validate_scene_set({"source": "library", "scenes": ss.LIBRARY})


def test_suggestions_follow_the_needs():
    s = ss.suggest_scenes({"activities": ["going to concerts", "driving to work"], "priorities": ["hearing my grandkids"]})
    names = [x["name"] for x in s["scenes"]]
    assert "Conversation" in names and "Concert" in names and "Siren while driving" in names and "Kids at home" in names
    kids = next(x for x in s["scenes"] if x["name"] == "Kids at home")
    assert kids["weight"] == 2.0 and "grandkids" in kids["why"]           # a priority weighs more, and says why
    sc = ss.as_scenarios(s)
    assert {"scenario_id", "description", "source_level_db_spl", "tags"} <= set(sc[0])


def test_quiet_life_still_gets_conversation():
    s = ss.suggest_scenes({})
    assert [x["name"] for x in s["scenes"]] == ["Conversation"]
