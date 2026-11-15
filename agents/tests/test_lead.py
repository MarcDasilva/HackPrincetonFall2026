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


def test_deep_agent_lead_sends_exactly_the_plain_call() -> None:
    """Catches Deep Agents' base prompt, file tools or subagents leaking into the orb reply's model call."""
    import asyncio

    from deepagents._models import get_model_provider
    from deepagents.profiles import HarnessProfile, register_harness_profile
    from helpers import ScriptedChatModel
    from langchain_core.messages import AIMessage, BaseMessage

    from horn_study.lead import _messages, answer

    seen: list[list[BaseMessage]] = []

    def respond(messages: list[BaseMessage], bound: list[str]) -> AIMessage:
        seen.append(messages)
        return AIMessage("  The research is halfway done.  ")

    class ProfiledModel(ScriptedChatModel):
        pass

    model = ProfiledModel(responder=respond)
    # Built-in profiles (Claude 4.x) append a suffix to the system prompt; a subclass keeps this one off other tests.
    register_harness_profile(
        str(get_model_provider(model)), HarnessProfile(system_prompt_suffix="DEEP AGENT SUFFIX")
    )
    history = [{"role": "lead", "text": "Ask me anything."}, {"role": "patient", "text": "How far along?"}]
    context: dict = dict(patient="right ear, mild", notes=["tinnitus"], status="running", events=[])

    reply = asyncio.run(answer(model, history, **context))

    assert reply == "The research is halfway done."
    assert [(type(m), m.content) for m in seen[0]] == [
        (type(m), m.content) for m in _messages(history, **context)
    ]
    assert model.log.calls == 1
    assert all(tools == [] for tools in model.log.bound_tool_sets)


def test_lead_reads_the_evidence_tree_and_nothing_else(tmp_path) -> None:
    """Catches the lead losing its file tools (it could only see board headlines), gaining write tools over the
    research record, or tool results being dropped between calls so a read never reaches the answer."""
    import asyncio

    from helpers import ScriptedChatModel, call
    from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

    from horn_study.lead import READ_TOOLS, answer

    (tmp_path / "board" / "hearing").mkdir(parents=True)
    (tmp_path / "board" / "hearing" / "hearing-B1.md").write_text("# Gain peaks near 3 kHz\n")

    def respond(messages: list[BaseMessage], bound: list[str]) -> AIMessage:
        read = [m for m in messages if isinstance(m, ToolMessage)]
        if not read:
            return call("read_file", {"file_path": "/board/hearing/hearing-B1.md"})
        return AIMessage(
            "Board says gain peaks near 3 kHz." if "3 kHz" in str(read[-1].content) else "missing"
        )

    model = ScriptedChatModel(responder=respond)
    history = [{"role": "patient", "text": "What did hearing find?"}]
    context: dict = dict(patient="right ear", notes=[], status="running", events=[])

    assert (
        asyncio.run(answer(model, history, evidence=tmp_path, **context))
        == "Board says gain peaks near 3 kHz."
    )
    assert all(set(tools) <= READ_TOOLS for tools in model.log.bound_tool_sets)
