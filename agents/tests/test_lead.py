"""The lead's scripted exchange. Research must NEVER be requested without a yes (or "nothing to add")."""

from __future__ import annotations

from horn_study.lead import BEGIN, LAUNCH, NOTED, OPENING, WAIT, Stage, step


def talk(*texts: str) -> tuple[list[str], Stage, list[str]]:
    stage: Stage = "new"
    replies: list[str] = []
    notes: list[str] = []
    for text in texts:
        reply, stage, note = step(stage, text)
        replies.append(reply)
        notes += [note] if note else []
    return replies, stage, notes


def test_opens_with_the_audiogram_question() -> None:
    """Catches the first line drifting from the agreed wording."""
    replies, stage, _ = talk("")
    assert (
        replies == [OPENING] == ["Anything I should know before I launch research based on your audiogram?"]
    )
    assert stage == "opening"


def test_no_to_the_opening_launches() -> None:
    """Catches "nothing to add" failing to launch."""
    replies, stage, _ = talk("", "No.")
    assert stage == "launched"
    assert replies[-1] == LAUNCH


def test_notes_repeat_until_yes() -> None:
    """Catches a note being lost, the prompt not repeating, or a "no" to "May I begin?" launching anyway."""
    replies, stage, notes = talk("", "I have tinnitus in my left ear", "I also run a lot", "no")
    assert replies[1:] == [f"{NOTED} {BEGIN}", "Noted. May I begin?", WAIT]
    assert stage == "begin"
    _, stage, notes = talk("", "I have tinnitus in my left ear", "I also run a lot", "no", "yes go ahead")
    assert stage == "launched"
    assert notes == ["I have tinnitus in my left ear", "I also run a lot"]


def test_simulation_count_is_a_number_from_1_to_100() -> None:
    """Catches "100" being refused, or a stray 0 or 500 starting a run the dashboard cannot hold."""
    from horn_study.lead import count

    assert [count(t) for t in ("40", "let's do 100", "0", "500", "lots")] == [40, 100, None, None, None]
