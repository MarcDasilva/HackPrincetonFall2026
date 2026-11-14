"""The lead: the scripted exchange in front of the study. Research must NEVER start from here."""

from __future__ import annotations

from horn_study.lead import BEGIN, LAUNCH, NOTED, OPENING, WAIT, build_lead_graph, lead_turn


async def test_opens_with_the_audiogram_question() -> None:
    """Catches the first line drifting from the agreed wording."""
    out = await lead_turn(build_lead_graph(), "run1", "")
    assert (
        out["reply"] == OPENING == "Anything I should know before I launch research based on your audiogram?"
    )
    assert not out["launch_requested"]


async def test_no_to_the_opening_launches() -> None:
    """Catches "nothing to add" failing to launch."""
    graph = build_lead_graph()
    await lead_turn(graph, "run1", "")
    out = await lead_turn(graph, "run1", "No.")
    assert out["launch_requested"]
    assert out["reply"] == LAUNCH


async def test_notes_repeat_until_yes() -> None:
    """Catches a note being lost, the prompt not repeating, or a "no" to "May I begin?" launching anyway."""
    graph = build_lead_graph()
    await lead_turn(graph, "run1", "")
    out = await lead_turn(graph, "run1", "I have tinnitus in my left ear")
    assert out["reply"] == f"{NOTED} {BEGIN}" == "Noted. May I begin?"
    out = await lead_turn(graph, "run1", "I also run a lot")
    assert out["reply"] == "Noted. May I begin?"
    out = await lead_turn(graph, "run1", "no")
    assert out["reply"] == WAIT
    assert not out["launch_requested"]
    out = await lead_turn(graph, "run1", "yes go ahead")
    assert out["launch_requested"]
    assert out["notes"] == ["I have tinnitus in my left ear", "I also run a lot"]


async def test_conversations_are_per_run() -> None:
    """Catches one patient's answers leaking into another's conversation."""
    graph = build_lead_graph()
    await lead_turn(graph, "a", "")
    await lead_turn(graph, "a", "no")
    out = await lead_turn(graph, "b", "")
    assert out["reply"] == OPENING
    assert not out["launch_requested"]
