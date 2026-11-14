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


# --------------------------------------------------------------------------
# Everything the study evaluated is carried over unchanged
# --------------------------------------------------------------------------

BUILDER_DIALS = {
    "aim_yaw_deg": {"min": 0, "max": 180, "default": 60},
    "canal_stem_mm": {"min": 0, "max": 8, "default": 5.0},
    "flare_mid1": {"min": 0, "max": 1, "default": 0.15},
    "flare_mid2": {"min": 0, "max": 1, "default": 0.45},
}
COLLECTOR = {
    "throat_mm2": 27.0,
    "mouth_mm2": 200.0,
    "canal_stem_mm": 0.0,
    "collector_reach_mm": 18.0,
    "collector_mouth_mm2": 450.0,
}


def _earpiece_selected(**parameters: float) -> dict[str, Any]:
    return {"candidate_id": "E1", "kind": "design", "parameters": {**COLLECTOR, **parameters}}


def _opening(collector: dict[str, Any]) -> float:
    radii = collector["sections"][-1]
    return 3.141592653589793 * sum(r * r for r in radii) / len(radii)


def _reach(collector: dict[str, Any]) -> float:
    return sum(v * v for v in collector["spine"][-1]) ** 0.5


def _run(
    tmp_path: Path, selected: dict[str, Any], shaping: dict[str, Any], geometry: dict[str, Any] | None = None
):
    sent: list[dict[str, Any]] = []

    def builder(patient_dir: Path, params: dict[str, Any], design_id: str) -> dict[str, Any]:
        sent.append(params)
        built = {
            "throat_mm2": params["throat_mm2"],
            "mouth_mm2": params["mouth_mm2"],
            "canal_stem_mm": params.get("canal_stem_mm"),
            "collector": bool(params.get("collector")),
            "collector_mouth_mm2": _opening(params["collector"]) if params.get("collector") else None,
        }
        return {"ok": True, "checks": {"bore_wall_mm": 2.0}, "geometry": {**built, **(geometry or {})}}

    def respond(messages: list[Any], bound: list[str]) -> AIMessage:
        if _tool_results(messages) == 0:
            return call("build_earpiece", {**SHAPING, "aim_yaw_deg": 100, **shaping}, "c1")
        return call("finish", {"design_id": "s1-e1", "explanation": "x"}, "c2")

    record = produce_earpiece(
        _study(tmp_path, selected),
        tmp_path,
        ScriptedChatModel(responder=respond),
        build=builder,
        dials=BUILDER_DIALS,
    )
    return record, sent


def test_the_stem_flare_and_collector_size_come_from_the_study_not_the_model(tmp_path: Path) -> None:
    """The model asks for a stem, its own flare, and a small scoop. The study chose none of those."""
    scoop = {
        "spine": [[4, 0, 2], [8, 1, 6]],
        "sections": [[6] * 12, [10, 10, 10, 9, 8, 7, 6, 7, 8, 9, 10, 10]],
    }
    record, sent = _run(
        tmp_path, _earpiece_selected(), {"canal_stem_mm": 5, "flare_mid1": 0.9, "collector": scoop}
    )

    for params in sent:  # the chosen build and its S and L sizes
        assert params["canal_stem_mm"] == 0.0
        assert (params["flare_mid1"], params["flare_mid2"]) == (0.15, 0.45)
        assert (params["throat_mm2"], params["mouth_mm2"]) == (27.0, 200.0)
        assert _reach(params["collector"]) == pytest.approx(18.0, abs=0.01)
        assert _opening(params["collector"]) == pytest.approx(450.0, rel=0.002)
        assert len(params["collector"]["spine"]) == 1
    built = sent[0]["collector"]
    # The model's direction and rim outline survive: same lean toward the front, front lip larger than the back.
    out, up, front = built["spine"][0]
    assert (up / out, front / out) == pytest.approx((1 / 8, 6 / 8), abs=0.001)
    assert built["sections"][0][0] > built["sections"][0][6]
    assert record["departures_from_study"] == []
    assert record["study_collector"] == {"reach_mm": 18.0, "opening_mm2": 450.0}
    assert record["locked"]["canal_stem_mm"] == 0.0


def test_a_flush_selection_is_never_given_a_collector(tmp_path: Path) -> None:
    cone = {"spine": [[10, 0, 0]], "sections": [[12] * 12]}
    record, sent = _run(
        tmp_path, _earpiece_selected(collector_reach_mm=0.0, collector_mouth_mm2=0.0), {"collector": cone}
    )
    assert all(params["collector"] is None for params in sent)
    assert record["departures_from_study"] == []


def test_a_selected_collector_is_built_even_when_the_model_omits_it(tmp_path: Path) -> None:
    record, sent = _run(tmp_path, _earpiece_selected(), {"hood_mm": 3})
    assert sent[0]["collector"]["spine"] == [[18.0, 0.0, 0.0]]
    assert _opening(sent[0]["collector"]) == pytest.approx(450.0, rel=0.002)
    assert sent[0]["hood_mm"] == 0.0
    assert record["departures_from_study"] == []


def test_a_collector_cannot_be_laid_flat_against_the_head(tmp_path: Path) -> None:
    sideways = {"spine": [[0, 0, 12]], "sections": [[9] * 12]}
    _, sent = _run(tmp_path, _earpiece_selected(), {"collector": sideways})
    out, _, front = sent[0]["collector"]["spine"][0]
    assert out == pytest.approx(9.0, abs=0.01)
    assert _reach(sent[0]["collector"]) == pytest.approx(18.0, abs=0.01)
    assert front > 0


def test_a_build_that_differs_from_the_study_is_reported(tmp_path: Path) -> None:
    record, _ = _run(
        tmp_path, _earpiece_selected(), {}, geometry={"canal_stem_mm": 5.0, "collector_mouth_mm2": 256.0}
    )
    assert record["departures_from_study"] == [
        "canal_stem_mm: built 5 mm, study evaluated 0 mm",
        "collector opening: built 256 mm^2, study evaluated 450 mm^2",
    ]
    assert record["builds"][0]["departures_from_study"] == record["departures_from_study"]


def test_a_study_without_collector_dials_keeps_the_models_collector(tmp_path: Path) -> None:
    """A spiral-horn study says nothing about a collector, so the old behaviour holds for it."""
    cone = {"spine": [[10, 0, 0]], "sections": [[12] * 12]}
    record, sent = _run(tmp_path, _selected(), {"collector": cone})
    assert sent[0]["collector"] == cone
    assert record["study_collector"] is None


def test_a_piece_over_the_studys_size_limit_is_sent_back_and_reported(tmp_path: Path) -> None:
    """Shaping can make a collector stand out further than the tested one. The study's limit still holds."""
    selected = _earpiece_selected()
    study = tmp_path / "s1"
    study.mkdir()
    results = {
        "study_id": "s1",
        "selected_candidate_id": "E1",
        "selected_candidate": selected,
        "plan": {
            "selection_rule": {"constraints": [{"metric": "protrusion_mm", "bound": "max", "value": 20.0}]}
        },
        "report": {
            "candidates": [{"candidate_id": "E1", "metrics": [{"name": "protrusion_mm", "mean": 17.1}]}]
        },
    }
    (study / "results.json").write_text(json.dumps(results))
    heights = iter([24.0, 19.0, 19.0, 19.0])

    def builder(patient_dir: Path, params: dict[str, Any], design_id: str) -> dict[str, Any]:
        geometry = {
            "canal_stem_mm": 0.0,
            "collector": True,
            "collector_mouth_mm2": 450.0,
            "proud_of_concha_mm": next(heights),
        }
        return {"ok": True, "checks": {"bore_wall_mm": 2.0}, "geometry": geometry}

    replies: list[str] = []

    def respond(messages: list[Any], bound: list[str]) -> AIMessage:
        step = _tool_results(messages)
        if step:
            replies.append(str(messages[-1].content))
        if step == 0:
            return call("build_earpiece", {**SHAPING, "aim_yaw_deg": 100}, "c1")
        if step == 1:
            return call("finish", {"design_id": "s1-e1", "explanation": "x"}, "c2")
        if step == 2:
            return call("build_earpiece", {**SHAPING, "aim_yaw_deg": 100}, "c3")
        return call("finish", {"design_id": "s1-e2", "explanation": "within the limit"}, "c4")

    record = produce_earpiece(
        study, tmp_path, ScriptedChatModel(responder=respond), build=builder, dials=BUILDER_DIALS
    )

    assert "stands out 24 mm, over the study's limit of 20 mm" in replies[0]
    assert replies[1].startswith("Rejected: s1-e1 differs from the design the study tested")
    assert record["chosen"]["design_id"] == "s1-e2"
    assert record["departures_from_study"] == []
    assert record["size_mm"] == {"stood_out_in_study": 17.1, "study_limit": 20.0, "built": 19.0}
