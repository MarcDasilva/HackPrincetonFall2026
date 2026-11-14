"""The earpiece step: the model shapes, code guards the acoustic numbers and the fit checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers import ScriptedChatModel, call
from langchain_core.messages import AIMessage, ToolMessage

from horn_study.earpiece import EarpieceError, produce_earpiece

DIALS = {"aim_yaw_deg": {"min": 0, "max": 180}}
SHAPING = {
    "aim_yaw_deg": 60,
    "aim_pitch_deg": 0,
    "hood_mm": 0,
    "rim_conformity": 0.7,
    "mouth_stretch": 1.0,
    "flare_mid1": 0.1,
    "flare_mid2": 0.4,
    "canal_stem_mm": 5,
    "tab_side_deg": -90,
    "why": "test",
}


def _study(tmp_path: Path, selected: dict[str, Any] | None) -> Path:
    study = tmp_path / "s1"
    study.mkdir()
    (study / "results.json").write_text(json.dumps({"study_id": "s1", "selected_candidate": selected}))
    return study


def _selected() -> dict[str, Any]:
    return {
        "candidate_id": "D1",
        "kind": "design",
        "parameters": {"throat_mm2": 40.0, "mouth_mm2": 300.0},
    }


class FakeBuilder:
    """Rejects yaw below 90 as hitting the ear; records every parameter set it was given."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, patient_dir: Path, params: dict[str, Any], design_id: str) -> dict[str, Any]:
        self.calls.append(params)
        if params["aim_yaw_deg"] < 90:
            return {"ok": False, "reasons": [{"check": "ear_clearance", "message": "hits the ear"}]}
        return {"ok": True, "checks": {"bore_wall_mm": 2.0}, "geometry": {}}


def _tool_results(messages: list[Any]) -> int:
    return sum(isinstance(m, ToolMessage) for m in messages)


def test_a_rejected_build_cannot_be_chosen_and_the_locked_numbers_hold(tmp_path: Path) -> None:
    """Catches a model choosing a piece that failed its fit check, or smuggling in its own acoustics."""
    builder = FakeBuilder()

    def respond(messages: list[Any], bound: list[str]) -> AIMessage:
        step = _tool_results(messages)
        if step == 0:
            # throat_mm2 is not a tool argument; it must never reach the builder
            return call("build_earpiece", {**SHAPING, "throat_mm2": 5.0}, "c1")
        if step == 1:
            return call("finish", {"design_id": "s1-e1", "explanation": "x"}, "c2")
        if step == 2:
            return call("build_earpiece", {**SHAPING, "aim_yaw_deg": 100}, "c3")
        return call("finish", {"design_id": "s1-e2", "explanation": "faces the talker"}, "c4")

    record = produce_earpiece(
        _study(tmp_path, _selected()),
        tmp_path,
        ScriptedChatModel(responder=respond),
        build=builder,
        dials=DIALS,
    )
    assert record["chosen"] == {"design_id": "s1-e2", "explanation": "faces the talker", "chosen_by": "agent"}
    assert all(c["throat_mm2"] == 40.0 and c["mouth_mm2"] == 300.0 for c in builder.calls)
    # S and L reuse the chosen shaping exactly; only the cast size differs
    assert [c.get("fit_offset_mm") for c in builder.calls[-2:]] == [-0.5, 0.5]
    assert all(c["aim_yaw_deg"] == 100 for c in builder.calls[-2:])
    assert record["sizes"]["S"]["design_id"] == "s1-e2-S"
    assert record["sizes"]["L"]["ok"]
    assert json.loads((tmp_path / "s1" / "earpiece.json").read_text())["status"] == "built"


def test_the_build_budget_is_a_hard_cap(tmp_path: Path) -> None:
    """Catches a model that keeps building forever and burns a minute of geometry per call."""
    builder = FakeBuilder()

    def respond(messages: list[Any], bound: list[str]) -> AIMessage:
        return call("build_earpiece", SHAPING, f"c{len(messages)}")

    record = produce_earpiece(
        _study(tmp_path, _selected()),
        tmp_path,
        ScriptedChatModel(responder=respond),
        build=builder,
        dials=DIALS,
        max_builds=2,
    )
    assert len(builder.calls) == 2
    assert record["status"] == "no_buildable_design"


def test_no_selected_design_builds_nothing(tmp_path: Path) -> None:
    """Catches printing a part for a study whose code-side selection justified no design."""
    builder = FakeBuilder()
    with pytest.raises(EarpieceError):
        produce_earpiece(
            _study(tmp_path, None),
            tmp_path,
            ScriptedChatModel(responder=lambda m, b: AIMessage(content="")),
            build=builder,
            dials=DIALS,
        )
    assert builder.calls == []


def test_the_model_sees_each_build_it_made(tmp_path: Path) -> None:
    """Catches a designer that passes every check but picks a shape it never looked at."""
    png = tmp_path / "preview.png"
    png.write_bytes(b"\x89PNG fake")
    seen: list[Any] = []

    def builder(patient_dir: Path, params: dict[str, Any], design_id: str) -> dict[str, Any]:
        return {"ok": True, "checks": {"bore_wall_mm": 2.0}, "files": {"preview.png": str(png)}}

    def respond(messages: list[Any], bound: list[str]) -> AIMessage:
        if _tool_results(messages) == 0:
            return call("build_earpiece", {**SHAPING, "aim_yaw_deg": 100}, "c1")
        seen.append(messages[-1].content)
        return call("finish", {"design_id": "s1-e1", "explanation": "x"}, "c2")

    produce_earpiece(
        _study(tmp_path, _selected()),
        tmp_path,
        ScriptedChatModel(responder=respond),
        build=builder,
        dials=DIALS,
    )
    assert seen[0][1]["type"] == "image"
