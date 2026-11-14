"""Evidence rules: read before citing, quote verbatim, stay within budget."""

from __future__ import annotations

import asyncio

import pytest
from helpers import PASSAGES, FakeReader, FakeSearch

from horn_study.events import EventBus
from horn_study.research import INVESTIGATORS, ResearchLedger, ResearchSession, investigator_prompt
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


def session(max_calls: int = 6, reader: FakeReader | None = None, search=None):
    events = EventBus("s")
    made = ResearchSession(
        INVESTIGATORS[0],
        max_tool_calls=max_calls,
        search=search or FakeSearch(),
        reader=reader or FakeReader(),
        ledger=ResearchLedger(),
        events=events,
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


def test_each_investigator_owns_one_distinct_question():
    assert [spec.name for spec in INVESTIGATORS] == [
        "hearing_research",
        "use_context_research",
        "acoustic_design_research",
        "evaluation_method_research",
    ]
    for field in ("name", "title", "finding_prefix", "question", "covers", "required_output"):
        values = [getattr(spec, field) for spec in INVESTIGATORS]
        assert len(set(values)) == len(values), field
    assert INVESTIGATORS[3].finding_prefix == "method"


def test_only_the_method_investigator_is_asked_for_the_limits_of_the_model():
    by_name = {spec.name: spec for spec in INVESTIGATORS}
    assert "model_limitations" in by_name["evaluation_method_research"].required_output
    for name in ("hearing_research", "use_context_research", "acoustic_design_research"):
        assert "limitations" not in by_name[name].required_output


@pytest.mark.parametrize("spec", INVESTIGATORS, ids=lambda spec: spec.name)
def test_an_investigator_is_told_its_own_question_and_what_the_others_cover(spec):
    prompt = investigator_prompt(spec, budget=6)
    assert f"You are the {spec.title} " in prompt
    assert f"Your question: {spec.question}" in prompt
    assert spec.required_output in prompt
    assert "You have 6 search and read calls in total." in prompt
    for other in INVESTIGATORS:
        assert (other.covers in prompt) == (other.name != spec.name)
    assert "{" not in prompt
