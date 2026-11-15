"""Evidence rules: read before citing, quote verbatim, stay within budget."""

from __future__ import annotations

import asyncio

import pytest
from helpers import PASSAGES, FakeReader, FakeSearch

from horn_study.events import EventBus
from horn_study.research import INVESTIGATORS, ResearchLedger, ResearchSession
from horn_study.sources import (
    SearchHit,
    SourceUnavailable,
    check_url_allowed,
    classify_source,
    extract_html_text,
    passage_in_text,
    select_passages,
)

URL = "https://papers.example.org/a"
FINDING = {
    "question": "q",
    "claim": "c",
    "applicability": "a",
    "limitations": "l",
    "related_user_goal": "g",
    "motivates": "m",
}


def session(max_calls: int = 6, reader: FakeReader | None = None, search=None, post_every: int | None = None):
    # The post-often gate is OFF here: these cases are about evidence, not posting. Its own test turns it on.
    events = EventBus("s")
    made = ResearchSession(
        INVESTIGATORS[0],
        max_tool_calls=max_calls,
        search=search or FakeSearch(),
        reader=reader or FakeReader(),
        ledger=ResearchLedger(),
        events=events,
        post_every=post_every,
    )
    return made, events


async def test_a_search_snippet_cannot_support_a_finding():
    s, events = session()
    await s.search_literature("horn acoustics")
    reply = s.record_finding(
        source="https://papers.example.org/horn-acoustics",
        evidence_passage="A snippet that is only a lead.",
        **FINDING,
    )
    assert reply.startswith("Not recorded: that source has not been read")
    assert s.rejected_findings == 1
    assert not [e for e in events.history if e.type == "research.finding_added"]


async def test_a_passage_must_appear_in_the_text_that_was_read():
    s, events = session()
    await s.read_source(URL, "horn")
    invented = s.record_finding(
        source=URL, evidence_passage="Horns provide exactly 15 dB of gain for all listeners.", **FINDING
    )
    assert "was not found in S1" in invented
    accepted = s.record_finding(source="S1", evidence_passage=PASSAGES["acoustic_design_research"], **FINDING)
    assert accepted == "Recorded as hearing-F1."
    (event,) = [e for e in events.history if e.type == "research.finding_added"]
    assert event.finding_ids == ("hearing-F1",)
    assert event.data["source_url"] == URL


async def test_search_and_read_calls_stop_at_the_budget():
    reader, search = FakeReader(), FakeSearch()
    s, _ = session(max_calls=2, reader=reader, search=search)
    await s.search_literature("one")
    await s.read_source(URL, "horn")
    blocked_search = await s.search_literature("two")
    blocked_read, files = await s.read_source("https://papers.example.org/b", "horn")
    assert "Research budget used up (2/2" in blocked_search
    assert "Research budget used up" in blocked_read
    assert files == {}
    assert search.queries == ["one"]
    assert reader.fetched == [URL]
    assert s.calls_used == 2


async def test_search_stops_when_research_time_is_up():
    # Without the deadline the slowest investigator held synthesis for over five minutes.
    search = FakeSearch()
    s = ResearchSession(
        INVESTIGATORS[0],
        max_tool_calls=6,
        search=search,
        reader=FakeReader(),
        ledger=ResearchLedger(),
        events=EventBus("s"),
        post_every=None,
        max_seconds=0,
    )
    assert "Research time is up" in await s.search_literature("one")
    assert search.queries == []
    assert s.calls_used == 0


async def test_rereading_is_free_and_findings_remain_possible_after_the_budget():
    s, _ = session(max_calls=1)
    await s.read_source(URL, "horn")
    again, _ = await s.read_source(URL, "talkers")
    assert "Already read" in again
    assert s.calls_used == 1
    reply = s.record_finding(source=URL, evidence_passage=PASSAGES["hearing_research"], **FINDING)
    assert reply.startswith("Recorded")


async def test_unreadable_source_falls_back_to_the_abstract_and_says_so():
    sentence = "The abstract states one precise thing about horn length and response."

    class AbstractSearch:
        async def search(self, query, limit=6):
            hit = SearchHit(
                title="Paywalled paper",
                url=URL,
                year=2021,
                authors="B",
                venue="J",
                snippet="short",
                open_access=False,
                backend="fake",
                abstract=(sentence + " ") * 4,
            )
            return [hit], []

    s, _ = session(reader=FakeReader(unavailable={URL}), search=AbstractSearch())
    await s.search_literature("x")
    message, _ = await s.read_source(URL, "horn")
    assert "abstract_only" in message
    assert "Only the abstract could be retrieved" in message
    assert s.record_finding(source=URL, evidence_passage=sentence, **FINDING).startswith("Recorded")

    blind, _ = session(reader=FakeReader(unavailable={URL}))
    message, files = await blind.read_source(URL, "horn")
    assert message.startswith(f"Could not read {URL}")
    assert files == {}


async def test_two_branches_reading_the_same_url_at_once_share_one_source():
    events = EventBus("s")
    ledger = ResearchLedger()
    reader = FakeReader()
    sessions = [
        ResearchSession(
            spec, max_tool_calls=6, search=FakeSearch(), reader=reader, ledger=ledger, events=events
        )
        for spec in INVESTIGATORS[:2]
    ]
    replies = await asyncio.gather(*(s.read_source(URL, "horn") for s in sessions))

    assert [record.source_id for record in ledger.sources] == ["S1"]
    assert all("Source S1:" in message for message, _ in replies)
    assert all(list(files) == ["/sources/S1.txt"] for _, files in replies)


def test_quote_matching_tolerates_typography_but_not_rewording():
    source = "The horn’s response – measured at the canal – peaked near 2.7 kHz in every case."
    assert passage_in_text("The horn's response - measured at the canal - peaked near 2.7 kHz", source)
    assert not passage_in_text("The horn response peaked around 2.7 kHz", source)
    assert not passage_in_text("peaked", source)


def test_passage_selection_prefers_paragraphs_about_the_focus():
    filler = " This sentence pads the paragraph so that it reads like ordinary body text in a paper." * 3
    document = "\n".join(
        [
            "Abstract. The opening paragraph introduces the study." + filler,
            "The acoustic path length of a horn shifts where its response peaks." + filler,
            "Competing talkers reduce the audibility margin in everyday listening." + filler,
        ]
    )
    picked = select_passages(document, "competing talkers", max_chars=600)
    assert picked.startswith("Competing talkers reduce")
    assert "acoustic path length" not in picked
    assert select_passages(document, "zebrafish", max_chars=200).startswith("Abstract.")


def test_passage_selection_merges_line_wrapped_text_into_readable_passages():
    wrapped = "\n".join(f"Line {n} of a PDF page with roughly sixty characters of text." for n in range(40))
    wrapped += "\nThe cochlear amplifier is discussed on this particular line of the page."
    picked = select_passages(wrapped, "cochlear amplifier", max_chars=2000)
    assert "cochlear amplifier" in picked
    assert len(picked) > 300


def test_html_extraction_drops_scripts_and_navigation():
    title, text = extract_html_text(
        "<html><head><title>A  Paper</title><script>var x='secret'</script></head>"
        "<body><nav>Menu</nav><p>First paragraph.</p><div>Second <b>bold</b> part.</div></body></html>"
    )
    assert title == "A Paper"
    assert text == "First paragraph.\nSecond bold part."


@pytest.mark.parametrize(
    "blocked",
    [
        "file:///etc/passwd",
        "http://localhost:8000/x",
        "http://127.0.0.1/x",
        "http://10.0.0.5/x",
        "http://intranet/x",
    ],
)
def test_only_public_http_sources_can_be_read(blocked):
    with pytest.raises(SourceUnavailable):
        check_url_allowed(blocked)


def test_public_sources_are_allowed():
    check_url_allowed("https://pmc.ncbi.nlm.nih.gov/articles/PMC5970796/")


@pytest.mark.parametrize(
    ("url", "from_search", "expected"),
    [
        ("https://en.wikipedia.org/wiki/Horn_(acoustic)", False, "tertiary"),
        ("https://en.wikipedia.org/wiki/Horn_(acoustic)", True, "tertiary"),
        ("https://www.britannica.com/science/ear", False, "tertiary"),
        ("https://pmc.ncbi.nlm.nih.gov/articles/PMC5970796/", False, "scholarly"),
        ("https://doi.org/10.1121/1.395867", False, "scholarly"),
        ("https://www.nature.com/articles/s41598-020-77042-w.pdf", False, "scholarly"),
        ("https://some-university.example.edu/paper.pdf", True, "scholarly"),
        ("https://github.com/claritychallenge/clarity", False, "technical_documentation"),
        (
            "https://raw.githubusercontent.com/claritychallenge/clarity/main/x.py",
            False,
            "technical_documentation",
        ),
        ("https://pypi.org/project/brucezilany/", False, "technical_documentation"),
        ("https://some-blog.example.com/horns", False, "other"),
        ("https://notwikipedia.org.example.com/x", False, "other"),
    ],
)
def test_sources_are_classified_by_what_they_are(url, from_search, expected):
    assert classify_source(url, from_literature_search=from_search) == expected


async def test_a_read_source_and_its_findings_carry_the_tier():
    s, events = session()
    await s.search_literature("a")
    await s.read_source(URL, "horn")
    s.record_finding(source=URL, evidence_passage=PASSAGES["hearing_research"], **FINDING)
    (source,) = s._ledger.sources
    (finding,) = s._ledger.findings
    assert source.tier == finding.source_tier == "scholarly"
    assert [e.data["tier"] for e in events.history if e.type == "research.source_read"] == ["scholarly"]


async def test_encyclopedia_pages_are_refused_without_spending_a_call():
    reader = FakeReader()
    s, events = session(reader=reader)
    message, files = await s.read_source("https://en.wikipedia.org/wiki/Horn_(acoustic)", "cutoff")
    assert message.startswith("Not read: https://en.wikipedia.org/wiki/Horn_(acoustic) is an encyclopedia")
    assert "No call was spent" in message
    assert files == {}
    assert reader.fetched == []
    assert s.calls_used == 0
    assert s._ledger.sources == ()
    assert events.history == []


async def test_only_one_finding_per_investigator_may_rest_on_a_non_scholarly_source():
    docs = "https://github.com/example/tool"
    web = "https://some-blog.example.com/post"
    s, _ = session()
    await s.read_source(docs, "tool")
    await s.read_source(web, "tool")
    await s.search_literature("a")
    await s.read_source(URL, "horn")

    first = s.record_finding(source=docs, evidence_passage=PASSAGES["hearing_research"], **FINDING)
    second = s.record_finding(source=web, evidence_passage=PASSAGES["use_context_research"], **FINDING)
    assert first == "Recorded as hearing-F1."
    assert second.startswith("Not recorded: S2 is a general web page")
    assert "need a paper" in second
    assert s.rejected_findings == 1

    paper_one = s.record_finding(source=URL, evidence_passage=PASSAGES["use_context_research"], **FINDING)
    paper_two = s.record_finding(source=URL, evidence_passage=PASSAGES["acoustic_design_research"], **FINDING)
    assert (paper_one, paper_two) == ("Recorded as hearing-F2.", "Recorded as hearing-F3.")
    assert [f.source_tier for f in s._ledger.findings] == [
        "technical_documentation",
        "scholarly",
        "scholarly",
    ]


async def test_a_search_event_carries_its_query_and_results():
    """Catches the dashboard's search modal coming up empty: the event must carry the full query and every hit,
    not only the one-line summary (truncated at 120 characters)."""
    s, events = session()
    await s.search_literature("horn acoustics " + "x" * 200)
    (event,) = [e for e in events.history if e.type == "research.searched"]
    assert event.data["query"] == "horn acoustics " + "x" * 200
    assert event.data["results"] and {"title", "url", "year", "snippet"} <= set(event.data["results"][0])


def test_an_event_inside_a_traced_run_names_that_run(monkeypatch):
    """Catches trace rows linking only to the whole study: an event emitted inside a LangSmith run (a tool
    call) records that run's id and trace id; outside any run it records none."""
    from types import SimpleNamespace

    import langsmith.run_helpers as rh

    events = EventBus("s")
    monkeypatch.setattr(rh, "get_current_run_tree", lambda: None)
    assert "langsmith" not in events.emit("research.agent_started", "s", component="c").data
    monkeypatch.setattr(rh, "get_current_run_tree", lambda: SimpleNamespace(id="run-1", trace_id="trace-1"))
    assert events.emit("research.agent_started", "s", component="c").data["langsmith"] == {
        "run_id": "run-1",
        "trace_id": "trace-1",
    }


async def test_board_posts_land_on_the_shared_board_and_cost_no_budget():
    """Catches submit_finding eating the search/read budget (agents would stop posting to save calls), a post
    missing from the board the lead reads, or its event missing from the boxes' feed."""
    s, events = session(max_calls=1)
    await s.read_source(URL, "gain")
    assert s.submit_finding("High-frequency gain matters", "Most consonant cues sit at 2-4 kHz.", URL) == (
        "Posted hearing-B1 to the info board."
    )
    s.submit_finding("Second note", "No source.")
    assert s.calls_used == 1
    board = s._ledger.board
    assert [p["headline"] for p in board] == ["High-frequency gain matters", "Second note"]
    assert board[0]["source_id"] == "S1"
    assert board[1]["source"] is None
    assert [e.data["post_id"] for e in events.history if e.type == "research.board_posted"] == [
        "hearing-B1",
        "hearing-B2",
    ]
    assert s.submit_finding("  ", "x").startswith("Not posted")


async def test_tool_results_nudge_the_agent_to_post():
    """Catches the post-often nudge dropping out of search and read results — it is what keeps posting frequent."""
    s, _ = session()
    assert "submit_finding" in await s.search_literature("horn acoustics")
    message, _ = await s.read_source(URL, "gain")
    assert "submit_finding" in message


async def test_a_search_reply_parses_back_into_its_hits():
    """Catches the search modal for older studies coming back empty: the server rebuilds their hits by
    parsing the tool's reply text out of LangSmith (server.parse_search), so that parser must read EXACTLY
    what search_literature writes."""
    from horn_study.server import parse_search

    s, events = session()
    reply = await s.search_literature("horn acoustics")
    (event,) = [e for e in events.history if e.type == "research.searched"]
    parsed = parse_search(reply)
    assert parsed["query"] == "horn acoustics"
    keys = ("title", "url", "open_access", "venue")
    want = [{k: h[k] or None for k in keys} for h in event.data["results"]]
    assert [{k: h.get(k) for k in keys} for h in parsed["results"]] == want
    assert [str(h.get("year")) for h in parsed["results"]] == [str(h["year"]) for h in event.data["results"]]


async def test_two_unposted_research_calls_block_the_third_until_a_post():
    """Catches agents researching for long stretches without posting: after two searches or reads with no
    submit_finding, the next is refused WITHOUT spending budget, and a post opens it again."""
    s, _ = session(post_every=2)
    await s.search_literature("a")
    await s.search_literature("b")
    refused = await s.search_literature("c")
    assert refused.startswith("Not run, and no call spent")
    assert s.calls_used == 2
    s.submit_finding("Headline", "Detail.")
    assert (await s.search_literature("c")).startswith("Results for")
    assert s.calls_used == 3


async def test_the_ledger_writes_a_sorted_evidence_tree(tmp_path):
    """Catches board posts, findings or source texts missing from the lead's file system (lead.answer)."""
    s = ResearchSession(
        INVESTIGATORS[0],
        max_tool_calls=6,
        search=FakeSearch(),
        reader=FakeReader(),
        ledger=ResearchLedger(tmp_path),
        events=EventBus("s"),
        post_every=None,
    )
    await s.read_source(URL, "horn")
    s.record_finding(source="S1", evidence_passage=PASSAGES["acoustic_design_research"], **FINDING)
    s.submit_finding("Horn length shifts the peak", "Matters for 2-4 kHz loss.", "S1")
    files = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.md"))
    assert files == [
        "board/hearing_research/hearing-B1.md",
        "findings/hearing_research/hearing-F1.md",
        "sources/S1.md",
    ]
    assert PASSAGES["acoustic_design_research"] in (tmp_path / "sources/S1.md").read_text()
    assert "source: S1" in (tmp_path / "board/hearing_research/hearing-B1.md").read_text()


async def test_a_stopped_study_refuses_search():
    # The patient said move on: investigators must stop spending calls and report.
    from horn_study.research import stop_research

    search = FakeSearch()
    s = ResearchSession(
        INVESTIGATORS[0],
        max_tool_calls=6,
        search=search,
        reader=FakeReader(),
        ledger=ResearchLedger(),
        events=EventBus("s"),
        post_every=None,
        study_id="stopped-study",
    )
    stop_research("stopped-study")
    assert "Research time is up" in await s.search_literature("one")
    assert search.queries == []
