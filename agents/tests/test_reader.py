"""Reading sources over HTTP: PubMed Central through its API, politely, with a fallback."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from horn_study.sources import HttpReader, Pacer, SourceUnavailable, extract_jats_text

PARAGRAPH = "Listeners were tested twice within fourteen days and the thresholds were compared. " * 6
JATS = f"""<?xml version="1.0" ?>
<!DOCTYPE pmc-articleset PUBLIC "-//NLM//DTD ARTICLE SET 2.0//EN" "https://dtd.nlm.nih.gov/x.dtd">
<pmc-articleset><article>
<front><article-meta>
<title-group><article-title>Short-term variability of <italic>pure-tone</italic> thresholds</article-title></title-group>
<abstract><title>Abstract</title><p>The abstract states the 50% critical difference boundaries.</p></abstract>
</article-meta></front>
<body>
<sec><title>Methods</title>
<p>{PARAGRAPH}See <xref rid="R1">Smith et al., 2001</xref> for the earphones.</p>
<table-wrap><table><tr><td>cell that is not prose</td></tr></table></table-wrap>
<fig><caption><p>A figure caption.</p></caption></fig>
<p>Thresholds at 4&#x2009;kHz varied by 5 dB<inline-formula><mml:math xmlns:mml="m">x</mml:math></inline-formula> between sessions.</p>
</sec>
</body>
<back><ref-list><ref><mixed-citation>Smith J. A reference that is not the paper's text.</mixed-citation></ref></ref-list></back>
</article></pmc-articleset>"""
ABSTRACT_ONLY_JATS = JATS.split("<body>")[0] + JATS.split("</body>")[1]
PAGE = (
    "<html><head><title>Web page title</title></head><body><p>"
    + "Web page prose. " * 60
    + "</p></body></html>"
)
CHALLENGE = "<html><body><p>Checking your browser before accessing pmc.ncbi.nlm.nih.gov ...</p></body></html>"


def reader_for(handler) -> tuple[HttpReader, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return HttpReader(client, pacer=Pacer(0)), seen


def api_or_page(api: httpx.Response, page: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        return api if request.url.host == "eutils.ncbi.nlm.nih.gov" else page

    return handler


def test_article_xml_becomes_title_and_prose_without_references_tables_or_figures():
    title, text = extract_jats_text(JATS)
    assert title == "Short-term variability of pure-tone thresholds"
    lines = text.split("\n")
    assert lines[:3] == ["Abstract", "The abstract states the 50% critical difference boundaries.", "Methods"]
    assert lines[3].endswith("See Smith et al., 2001 for the earphones.")
    assert lines[4] == "Thresholds at 4 kHz varied by 5 dB between sessions."
    assert "not the paper's text" not in text
    assert "cell that is not prose" not in text
    assert "figure caption" not in text


@pytest.mark.parametrize(
    ("url", "pmcid"),
    [
        ("https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587/", "4668587"),
        ("https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587", "4668587"),
        ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4668587/", "4668587"),
        ("https://www.ncbi.nlm.nih.gov/pmc/articles/1011367", "1011367"),
        ("http://pmc.ncbi.nlm.nih.gov/articles/pmc4668587/?report=classic", "4668587"),
    ],
)
async def test_a_pubmed_central_article_is_read_through_the_api_not_the_web_page(url, pmcid):
    reader, seen = reader_for(api_or_page(httpx.Response(200, text=JATS), httpx.Response(500)))
    fetched = await reader.fetch(url)

    assert [request.url.host for request in seen] == ["eutils.ncbi.nlm.nih.gov"]
    assert dict(seen[0].url.params) == {"db": "pmc", "id": pmcid, "retmode": "xml"}
    assert fetched.url == fetched.final_url == url
    assert fetched.content_type == "xml"
    assert fetched.title == "Short-term variability of pure-tone thresholds"
    assert "Thresholds at 4 kHz varied by 5 dB between sessions." in fetched.text


@pytest.mark.parametrize(
    "api",
    [
        httpx.Response(429, text="rate limited"),
        httpx.Response(200, text=ABSTRACT_ONLY_JATS),
        httpx.Response(200, text="<pmc-articleset><error>not found</error></pmc-articleset>"),
        httpx.Response(200, text="this is not xml <<<"),
    ],
    ids=["api_refuses", "api_has_no_body_text", "api_has_no_article", "api_returns_garbage"],
)
async def test_when_the_api_has_no_full_text_the_web_page_is_read_instead(api):
    url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587/"
    reader, seen = reader_for(
        api_or_page(api, httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}))
    )
    fetched = await reader.fetch(url)

    hosts = [request.url.host for request in seen]
    assert hosts[-1] == "pmc.ncbi.nlm.nih.gov"
    assert set(hosts[:-1]) == {"eutils.ncbi.nlm.nih.gov"}
    assert fetched.content_type == "html"
    assert fetched.title == "Web page title"


async def test_a_browser_check_page_is_not_mistaken_for_the_article():
    url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587/"
    reader, _ = reader_for(
        api_or_page(
            httpx.Response(503), httpx.Response(200, text=CHALLENGE, headers={"content-type": "text/html"})
        )
    )
    with pytest.raises(SourceUnavailable):
        await reader.fetch(url)


async def test_other_pages_on_the_same_site_are_fetched_directly():
    url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587/pdf/nihms1.pdf"
    reader, seen = reader_for(
        lambda request: httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
    )
    await reader.fetch(url)
    assert [str(request.url) for request in seen] == [url]


async def test_calls_to_the_api_are_spaced_out_even_when_made_at_once():
    now = [100.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(round(seconds, 6))
        now[0] += seconds

    pacer = Pacer(0.4, clock=lambda: now[0], sleep=sleep)
    started: list[float] = []

    async def one() -> None:
        await pacer.wait()
        started.append(round(now[0], 6))

    await asyncio.gather(one(), one(), one())
    assert started == [100.0, 100.4, 100.8]
    assert slept == [0.4, 0.4]

    now[0] += 5
    await one()
    assert slept == [0.4, 0.4]


async def test_a_rate_limited_api_call_waits_as_told_and_is_tried_once_more():
    now = [50.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(round(seconds, 6))
        now[0] += seconds

    answers = [httpx.Response(429, headers={"retry-after": "2"}, text="{}"), httpx.Response(200, text=JATS)]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers[len(seen) - 1]

    reader = HttpReader(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        pacer=Pacer(0.5, clock=lambda: now[0], sleep=sleep),
    )
    fetched = await reader.fetch("https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587/")

    assert fetched.content_type == "xml"
    assert [request.url.host for request in seen] == ["eutils.ncbi.nlm.nih.gov"] * 2
    assert slept == [2.0]


async def test_a_rate_limit_is_retried_only_once():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "eutils.ncbi.nlm.nih.gov":
            return httpx.Response(429, headers={"retry-after": "not a number"}, text="{}")
        return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})

    async def no_sleep(seconds: float) -> None:
        return None

    reader = HttpReader(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)), pacer=Pacer(0.5, sleep=no_sleep)
    )
    fetched = await reader.fetch("https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587/")
    assert [request.url.host for request in seen] == ["eutils.ncbi.nlm.nih.gov"] * 2 + [
        "pmc.ncbi.nlm.nih.gov"
    ]
    assert fetched.content_type == "html"


async def test_holding_the_pace_delays_every_later_call():
    now = [10.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(round(seconds, 6))
        now[0] += seconds

    pacer = Pacer(0.5, clock=lambda: now[0], sleep=sleep)
    await pacer.wait()
    await pacer.hold(3)
    await pacer.wait()
    await pacer.wait()
    assert slept == [3.0, 0.5]


async def test_pubmed_records_and_articles_share_one_pace():
    waits: list[str] = []

    class CountingPacer(Pacer):
        async def wait(self) -> None:
            waits.append("wait")

    record = "1. J Tests. 2020.\nA record title\n\n" + "Abstract text of the record. " * 20
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=JATS if request.url.params["db"] == "pmc" else record)
    )
    reader = HttpReader(httpx.AsyncClient(transport=transport), pacer=CountingPacer(0))
    await reader.fetch("https://pmc.ncbi.nlm.nih.gov/articles/PMC4668587/")
    await reader.fetch("https://pubmed.ncbi.nlm.nih.gov/16212766/")
    assert waits == ["wait", "wait"]
