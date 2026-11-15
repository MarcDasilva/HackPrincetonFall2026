"""Read-only tools for the lead Deep Agent beyond its evidence files: the patient's own data and the literature.

Every tool answers with JSON text and NEVER writes. The patient's data comes from the session and the backend's
patient folder through `ctx` (lead.Lead.ctx, set by server.agent_ctx before each job): run_id, session() -> the
session dict, patient_dir, ear. The lead calls them for QUESTION, EARPIECE TASK and REPORT TASK alike.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

MAX_CHARS = 12000   # one tool answer never floods the agent's context
SESSION_TOOLS = frozenset(
    {
        "get_hearing_profile", "get_ear_measurements", "get_scenes", "get_design_options", "compare_designs",
        "get_validation", "search_literature", "read_source",
    }
)


def _clip(value: Any) -> str:
    text = json.dumps(value, indent=1, default=str)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n...[cut: ask for less, or use a narrower tool]"


def _scalars(d: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (d or {}).items() if isinstance(v, (int, float, str)) and not isinstance(v, bool)}


def _run(coro: Any) -> Any:
    """Runs a coroutine to completion from sync code, whether or not an event loop is already running here."""
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()


def session_tools(ctx: Callable[[], dict[str, Any]]) -> list[Any]:
    def session() -> dict[str, Any]:
        return (ctx().get("session") or (lambda: None))() or {}

    def patient_dir() -> Path | None:
        return ctx().get("patient_dir")

    def job() -> dict[str, Any]:
        d = patient_dir()
        p = d / "job.json" if d else None
        return json.loads(p.read_text()) if p and p.is_file() else {}

    def ear_dir() -> Path | None:
        d, ear = patient_dir(), ctx().get("ear")
        return (d / ear if ear and d and (d / ear).is_dir() else d)

    def options() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        d = ear_dir()
        p = d / "scene_design" / "result.json" if d else None
        r = json.loads(p.read_text()) if p and p.is_file() else {}
        return r.get("options") or [], r

    @tool
    def get_hearing_profile() -> str:
        """The patient's audiogram per ear (dB HL by frequency), which ear the aid is for, and their notes."""
        req = job().get("request", {})
        ags = {e: req[e].get("audiogram_db_hl") for e in ("left", "right") if isinstance(req.get(e), dict)} or {
            req.get("side"): req.get("audiogram_db_hl")
        }
        return _clip({"audiogram_db_hl": ags, "aided_ear": session().get("ear"), "notes": session().get("notes"),
                      "ear_height_mm": req.get("ear_height_mm"), "audiogram_is_example": req.get("audiogram_is_example")})

    @tool
    def get_ear_measurements() -> str:
        """The aided ear's measured shape (bowl volume, opening area, depth, ear-canal volumes), how well the 3D ear fit its photo, and the head's size."""
        j, ear = job(), ctx().get("ear")
        res = j.get("results", {})
        res = res.get(ear, res) if ear else res
        d = ear_dir()
        canals = json.loads((d / "context" / "canals.json").read_text()) if d and (d / "context" / "canals.json").is_file() else None
        return _clip({"ear": ear, "reconstruction": res.get("ear"), "ear_world": (res.get("context") or {}).get("ear_world"),
                      "canals": canals, "head": j.get("results", {}).get("head")})

    @tool
    def get_scenes() -> str:
        """The listening scenes the lead picked and simulated: each scene's sources (talker or babble, direction, level, sound) and speech audibility for normal hearing, this ear unaided and with the picked earpiece."""
        s = session()
        res = {r["id"]: r for r in (s.get("sims") or {}).get("results", [])}
        aided = (s.get("validation") or {}).get("aided") or []
        order = [r["id"] for r in (s.get("sims") or {}).get("results", [])]
        out = []
        for sc in s.get("scenes") or []:
            r = res.get(sc["id"], {})
            i = order.index(sc["id"]) if sc["id"] in order else -1
            out.append({"id": sc["id"], "name": sc["name"], "weight": sc["weight"], "why": sc.get("why"),
                        "sources": sc.get("sources"), "sii_healthy": r.get("sii_healthy"), "sii_unaided": r.get("sii_unaided"),
                        "sii_aided": aided[i] if 0 <= i < len(aided) else None})
        return _clip(out)

    @tool
    def get_design_options(design_id: str = "") -> str:
        """The designer's four earpiece options (or one by design_id): reason, key bands met, mean and worst gain by frequency, build parameters, measured geometry. Also which one the patient picked."""
        opts, r = options()
        keep = [o for o in opts if not design_id or o["id"] == design_id]
        return _clip({"picked": session().get("picked"), "freqs_hz": r.get("freqs_hz"), "target_db": r.get("target_db"),
                      "options": [{"id": o["id"], "recommended": o.get("recommended"), "reason": o.get("reason"), "key_met": o.get("key_met"),
                                   "gain_mean_db": o.get("gain_mean_db"), "gain_worst_db": o.get("gain_worst_db"),
                                   "params": _scalars(o.get("params")), "collector_reach_mm": o.get("collector_reach_mm"),
                                   "geometry": _scalars(o.get("geometry"))} for o in keep]})

    @tool
    def compare_designs(design_a: str, design_b: str) -> str:
        """Two options side by side: how their build parameters and geometry differ, and their mean gain difference (a minus b) at each frequency."""
        opts = {o["id"]: o for o in options()[0]}
        if design_a not in opts or design_b not in opts:
            return f"Unknown design. Options: {sorted(opts)}"
        a, b = opts[design_a], opts[design_b]
        diff = lambda x, y: {k: [x.get(k), y.get(k)] for k in {*x, *y} if x.get(k) != y.get(k)}  # noqa: E731
        return _clip({"params_differing": diff(_scalars(a.get("params")), _scalars(b.get("params"))),
                      "geometry_differing": diff(_scalars(a.get("geometry")), _scalars(b.get("geometry"))),
                      "gain_a_minus_b_db": [round(x - y, 2) for x, y in zip(a["gain_mean_db"], b["gain_mean_db"], strict=False)]})

    @tool
    def get_validation() -> str:
        """The validation of the picked earpiece: the summary, speech audibility per scene with the aid, and the aid's insertion gain by frequency (3D wave simulation, or the design's own 1D curve if the check failed)."""
        s = session()
        v = s.get("validation") or {}
        return _clip({"picked": s.get("picked"), "summary": v.get("summary"), "aided_by_scene": v.get("aided"), "gain_db": v.get("gain_db"),
                      "custom_earpiece": s.get("earpiece")})

    @tool
    def search_literature(query: str) -> str:
        """Search scholarly literature (OpenAlex, Europe PMC). Returns titles, years, URLs and snippets. Keep the query about the science; never include the patient's data."""
        from horn_study.sources import default_search, make_http_client

        async def go() -> Any:
            async with make_http_client() as client:
                return await default_search(client).search(query, 6)

        try:
            hits, notes = _run(go())
        except Exception as error:  # a tool must answer, never crash the run
            return f"Search failed: {type(error).__name__}: {error}"
        return _clip({"hits": [{"title": h.title, "year": h.year, "authors": h.authors, "venue": h.venue, "url": h.url, "snippet": h.snippet} for h in hits], "notes": notes})

    @tool
    def read_source(url: str, focus: str = "") -> str:
        """Fetch a paper or page and return its text, starting at the first passage that mentions `focus` (a few words). Cite the URL for anything you take from it."""
        from horn_study.sources import HttpReader, make_http_client

        async def go() -> Any:
            async with make_http_client() as client:
                return await HttpReader(client).fetch(url)

        try:
            src = _run(go())
        except Exception as error:
            return f"Read failed: {type(error).__name__}: {error}"
        text, at = src.text, 0
        for word in focus.lower().split():
            if (i := text.lower().find(word)) >= 0:
                at = max(0, i - 500)
                break
        return f"{src.title}\n{src.final_url}\n\n{text[at : at + 8000]}"

    return [get_hearing_profile, get_ear_measurements, get_scenes, get_design_options, compare_designs, get_validation, search_literature, read_source]
