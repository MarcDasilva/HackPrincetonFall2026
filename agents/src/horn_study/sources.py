"""Evidence access: literature search and source reading.

Search results are leads. Only text that was actually fetched and read can
support a finding, and the fetched text is kept so quoted passages can be
checked against it.
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

USER_AGENT = "horn-study-research/0.1 (literature research agent)"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MIN_USEFUL_CHARS = 400
MIN_ABSTRACT_RECORD_CHARS = 200


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    year: int | None
    authors: str
    venue: str
    snippet: str
    open_access: bool
    backend: str
    doi: str | None = None
    abstract: str = ""


@dataclass(frozen=True)
class FetchedSource:
    url: str
    final_url: str
    title: str
    content_type: str
    text: str


class SourceUnavailable(Exception):
    pass


class SearchBackend(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> list[SearchHit]: ...


class Reader(Protocol):
    async def fetch(self, url: str) -> FetchedSource: ...


class Search(Protocol):
    async def search(self, query: str, limit: int = 6) -> tuple[list[SearchHit], list[str]]: ...


# --------------------------------------------------------------------------
# Search backends
# --------------------------------------------------------------------------


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class OpenAlexBackend:
    """Cross-disciplinary index. Works without a key on a small shared budget."""

    name = "openalex"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = client
        self._api_key = api_key

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        params: dict[str, Any] = {
            "search": query,
            "per-page": limit,
            "select": (
                "id,doi,title,publication_year,authorships,primary_location,"
                "best_oa_location,open_access,abstract_inverted_index"
            ),
        }
        if self._api_key:
            params["api_key"] = self._api_key
        response = await self._client.get("https://api.openalex.org/works", params=params)
        response.raise_for_status()
        hits: list[SearchHit] = []
        for work in response.json().get("results", []):
            title = work.get("title")
            if not title:
                continue
            best = work.get("best_oa_location") or {}
            primary = work.get("primary_location") or {}
            oa = work.get("open_access") or {}
            url = (
                best.get("landing_page_url")
                or best.get("pdf_url")
                or oa.get("oa_url")
                or primary.get("landing_page_url")
                or work.get("doi")
                or work.get("id")
            )
            authors = ", ".join(
                (a.get("author") or {}).get("display_name", "") for a in (work.get("authorships") or [])[:4]
            )
            abstract = _abstract_from_inverted_index(work.get("abstract_inverted_index"))
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    year=work.get("publication_year"),
                    authors=authors,
                    venue=((primary.get("source") or {}).get("display_name") or ""),
                    snippet=_clip(abstract, 500),
                    open_access=bool(oa.get("is_oa")),
                    backend=self.name,
                    doi=_bare_doi(work.get("doi")),
                    abstract=abstract,
                )
            )
        return hits


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, places in index.items():
        positions.extend((place, word) for place in places)
    return " ".join(word for _, word in sorted(positions))


def _bare_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.IGNORECASE).lower()


class EuropePmcBackend:
    """Biomedical and life-science literature. No key needed."""

    name = "europe_pmc"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        response = await self._client.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": query, "format": "json", "pageSize": limit, "resultType": "core"},
        )
        response.raise_for_status()
        hits: list[SearchHit] = []
        for item in (response.json().get("resultList") or {}).get("result", []):
            title = item.get("title")
            if not title:
                continue
            pmcid = item.get("pmcid")
            doi = item.get("doi")
            if pmcid:
                url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            elif doi:
                url = f"https://doi.org/{doi}"
            else:
                url = f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}"
            year = item.get("pubYear")
            abstract = " ".join(_strip_tags(item.get("abstractText") or "").split())
            hits.append(
                SearchHit(
                    title=_clip(title, 300),
                    url=url,
                    year=int(year) if year and str(year).isdigit() else None,
                    authors=_clip(item.get("authorString") or "", 120),
                    venue=((item.get("journalInfo") or {}).get("journal") or {}).get("title") or "",
                    snippet=_clip(abstract, 500),
                    open_access=bool(pmcid) or item.get("isOpenAccess") == "Y",
                    backend=self.name,
                    doi=_bare_doi(doi),
                    abstract=abstract,
                )
            )
        return hits


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


class LiteratureSearch:
    """Queries every backend at once and interleaves what they return."""

    def __init__(self, backends: list[SearchBackend]) -> None:
        self._backends = backends

    async def search(self, query: str, limit: int = 6) -> tuple[list[SearchHit], list[str]]:
        outcomes = await asyncio.gather(
            *(backend.search(query, limit) for backend in self._backends), return_exceptions=True
        )
        notes: list[str] = []
        per_backend: list[list[SearchHit]] = []
        for backend, outcome in zip(self._backends, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                notes.append(f"{backend.name} search failed: {_describe_error(outcome)}")
            else:
                per_backend.append(outcome)
        merged: list[SearchHit] = []
        seen: set[str] = set()
        for rank in range(limit):
            for hits in per_backend:
                if rank >= len(hits):
                    continue
                hit = hits[rank]
                key = hit.doi or hit.url
                if key in seen:
                    continue
                seen.add(key)
                merged.append(hit)
        return merged[:limit], notes


def _describe_error(error: BaseException) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    return f"{type(error).__name__}: {error}"[:200]


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button"}
_BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "li",
    "tr",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "table",
    "ul",
    "ol",
    "dd",
    "dt",
    "figcaption",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.meta_title: str | None = None
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            fields = dict(attrs)
            if fields.get("name") in {"citation_title", "dc.title", "DC.title"} and fields.get("content"):
                self.meta_title = fields["content"]
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif not self._skip_depth:
            self.chunks.append(data)


def extract_html_text(html: str) -> tuple[str, str]:
    """Return (title, readable text) from an HTML document."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.chunks).split("\n")]
    text = "\n".join(line for line in lines if line)
    title = parser.meta_title or " ".join("".join(parser.title_parts).split())
    return title, text


def extract_pdf_text(data: bytes) -> tuple[str, str]:
    """Return (title, text) from a PDF. The title is empty when the file declares none."""
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(io.BytesIO(data))
    pages = [(page.extract_text() or "") for page in reader.pages]
    lines = [" ".join(line.split()) for line in "\n".join(pages).split("\n")]
    title = " ".join(str((reader.metadata.title if reader.metadata else "") or "").split())
    return title, "\n".join(line for line in lines if line)


def check_url_allowed(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceUnavailable("Only http and https URLs can be read.")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal")) or "." not in host:
        raise SourceUnavailable("That host is not a public source.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise SourceUnavailable("That address is not a public source.")


_PUBMED_RECORD = re.compile(r"^https?://(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?(?:[?#].*)?$")
_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _unwrap(text: str) -> str:
    """Join hard-wrapped lines so each blank-line-separated block is one paragraph."""
    blocks = re.split(r"\n\s*\n", text)
    return "\n".join(" ".join(block.split()) for block in blocks if block.strip())


class HttpReader:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, url: str) -> FetchedSource:
        check_url_allowed(url)
        pubmed = _PUBMED_RECORD.match(url)
        if pubmed:
            return await self._fetch_pubmed_record(url, pubmed.group(1))
        try:
            async with self._client.stream("GET", url, follow_redirects=True) as response:
                check_url_allowed(str(response.url))
                if response.status_code >= 400:
                    raise SourceUnavailable(f"The server answered HTTP {response.status_code}.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_DOWNLOAD_BYTES:
                        raise SourceUnavailable("The document is too large to read.")
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                final_url = str(response.url)
                encoding = response.encoding or "utf-8"
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"Could not fetch the source ({_describe_error(exc)}).") from exc

        data = bytes(body)
        if content_type == "application/pdf" or data[:5] == b"%PDF-":
            try:
                title, text = extract_pdf_text(data)
            except Exception as exc:
                raise SourceUnavailable(f"The PDF could not be parsed ({type(exc).__name__}).") from exc
            kind = "pdf"
        elif content_type == "text/plain":
            title, text, kind = "", _unwrap(data.decode(encoding, errors="replace")), "text"
        elif content_type in {"text/html", "application/xhtml+xml", ""} or content_type.startswith("text/"):
            title, text = extract_html_text(data.decode(encoding, errors="replace"))
            kind = "html"
        else:
            raise SourceUnavailable(f"Unsupported content type '{content_type}'.")
        if len(text) < MIN_USEFUL_CHARS:
            raise SourceUnavailable("The page returned too little readable text.")
        return FetchedSource(url=url, final_url=final_url, title=title, content_type=kind, text=text)

    async def _fetch_pubmed_record(self, url: str, pmid: str) -> FetchedSource:
        """PubMed pages refuse automated clients, so read the record through NCBI E-utilities."""
        try:
            response = await self._client.get(
                _EFETCH, params={"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"Could not fetch the PubMed record ({_describe_error(exc)}).") from exc
        text = _unwrap(response.text)
        if len(text) < MIN_ABSTRACT_RECORD_CHARS:
            raise SourceUnavailable("PubMed has no abstract for this record.")
        lines = text.split("\n")
        title = lines[1] if len(lines) > 1 else ""
        return FetchedSource(url=url, final_url=url, title=title, content_type="abstract_only", text=text)


def make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5"},
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_connections=12),
    )


def default_search(client: httpx.AsyncClient) -> LiteratureSearch:
    return LiteratureSearch(
        [
            OpenAlexBackend(client, api_key=os.environ.get("OPENALEX_API_KEY") or None),
            EuropePmcBackend(client),
        ]
    )


# --------------------------------------------------------------------------
# Passage selection and quote verification
# --------------------------------------------------------------------------

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {ord(c): "'" for c in "‘’‚′"} | {ord(c): '"' for c in "“”„″"}


def normalize_for_match(text: str) -> str:
    """Fold typography and whitespace so a faithful quote matches its source."""
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_QUOTES)
    text = text.replace("­", "")
    return " ".join(text.lower().split())


def passage_in_text(passage: str, text: str) -> bool:
    needle = normalize_for_match(passage).strip(" .\"'")
    return len(needle) >= 20 and needle in normalize_for_match(text)


def _paragraphs(text: str) -> list[str]:
    """Split into passages. Short consecutive lines (PDF text, wrapped pages) are merged."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return []
    if sum(len(line) for line in lines) / len(lines) >= 200:
        return [line for line in lines if len(line) > 40]
    merged: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        current.append(line)
        size += len(line) + 1
        if size >= 700:
            merged.append(" ".join(current))
            current, size = [], 0
    if current:
        merged.append(" ".join(current))
    return merged


def select_passages(text: str, focus: str, max_chars: int = 5000) -> str:
    """Pick the passages most related to `focus`, in document order.

    With no matching passage the opening of the document is returned.
    """
    paragraphs = _paragraphs(text)
    if not paragraphs:
        return text[:max_chars]
    terms = set(re.findall(r"[a-z0-9]{4,}", focus.lower()))
    scored = sorted(
        ((sum(p.lower().count(t) for t in terms), i) for i, p in enumerate(paragraphs)),
        key=lambda pair: (-pair[0], pair[1]),
    )
    budget = max_chars
    chosen: set[int] = set()
    for score, index in scored:
        if score == 0:
            break
        length = len(paragraphs[index]) + 2
        if length > budget:
            continue
        chosen.add(index)
        budget -= length
    if not chosen:
        return "\n\n".join(paragraphs)[:max_chars]
    return "\n\n".join(paragraphs[i] for i in sorted(chosen))[:max_chars]
