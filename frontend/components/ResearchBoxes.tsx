"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import Orb, { type OrbNode, type OrbVariant } from "@/components/Orb";
import { MetalFx } from "@/components/metal";
import { AGENTS as AGENTS_URL, studyEvents, type StudyEvent } from "@/lib/lead";

/**
 * The research view: four investigators run in parallel, one per corner, around the lead's orb and the chat box.
 * Traces are the study's REAL events (agents/src/horn_study/research.py emits them; server.py serves events.jsonl), polled while the study runs.
 */

type RunType = "chain" | "llm" | "tool" | "retriever";
type Trace = { id: number; type: RunType; name: string; detail: string; ms?: number; done?: boolean; event: StudyEvent };
type Hit = { title?: string; year?: number | string | null; authors?: string; venue?: string; url?: string; open_access?: boolean; snippet?: string };

/** Where a row's click goes in LangSmith: the run the event happened inside (agents' events.py stamps data.langsmith), else the whole study's trace for older studies; null when the study was not traced. The agents server builds the URL — it needs the org and project ids. */
function langsmithHref(e: StudyEvent): string | null {
  const ls = e.data?.langsmith as { run_id?: string; trace_id?: string } | undefined;
  if (ls?.run_id) return `${AGENTS_URL}/langsmith/${ls.run_id}${ls.trace_id ? `?trace_id=${ls.trace_id}` : ""}`;
  return e.trace?.tracing_enabled && e.trace.run_id ? `${AGENTS_URL}/langsmith/${e.trace.run_id}` : null;
}
/** key is the investigator's name in research.py INVESTIGATORS — events are matched to a box by it. */
type Agent = { key: string; title: string; orb: OrbVariant; corner: "tl" | "tr" | "bl" | "br" };

const AGENTS: Agent[] = [
  { key: "hearing_research", title: "Hearing research", orb: "tidal", corner: "tl" },
  { key: "use_context_research", title: "Use context", orb: "halo", corner: "tr" },
  { key: "acoustic_design_research", title: "Acoustic design", orb: "loxodrome", corner: "bl" },
  { key: "ear_fit_research", title: "Ear fit", orb: "nebula", corner: "br" },
];

export const RESEARCH_LINE = "Four agents are researching your aid. Ask me anything.";
const POLL_MS = 1500;
const FINISHED = new Set(["research.agent_completed", "research.agent_failed"]);

/** One event as a trace row; null for events a box does not list. A row's time is the gap to the agent's next event. */
function toTrace(e: StudyEvent, next: StudyEvent | undefined): Trace | null {
  const row = (type: RunType, name: string, detail: string): Trace => ({
    id: e.sequence, type, name, detail, event: e,
    ms: next ? Date.parse(next.timestamp) - Date.parse(e.timestamp) : undefined,
    done: FINISHED.has(e.type),
  });
  switch (e.type) {
    case "research.agent_started": return row("chain", `${e.component}_agent`, "start");
    case "research.searched": return row("retriever", "search_literature", e.summary);
    case "research.source_read": return row("tool", "read_source", e.summary.replace(/^Read: /, ""));
    case "research.finding_added": return row("tool", "record_finding", e.summary);
    case "research.board_posted": return row("tool", "submit_finding", e.summary);
    case "research.agent_completed": return row("chain", "finished", e.summary);
    case "research.agent_failed": return row("chain", "stopped", e.summary);
    default: return null;
  }
}

/** Footer line: the agent's own summary once it finishes, else its latest info-board post or finding, else its latest step. */
function summarize(events: StudyEvent[]): string {
  const last = events.at(-1);
  if (!last) return "Waiting to start.";
  if (last.type === "research.agent_completed" && typeof last.data?.summary === "string") return last.data.summary;
  return events.findLast((e) => e.type === "research.board_posted" || e.type === "research.finding_added")?.summary ?? last.summary;
}

/** Run-type glyphs in the spirit of LangSmith's trace tree: chain = link, llm = sparkle, tool = wrench, retriever = document search. Drawn here, not copied. */
const RUN_ICON: Record<RunType, { d: string[]; color: string }> = {
  chain: { d: ["M9 15l6-6", "M11 6l1.5-1.5a4 4 0 0 1 5.7 5.7L16.5 12", "M13 18l-1.5 1.5a4 4 0 0 1-5.7-5.7L7.5 12"], color: "#7aa2ff" },
  llm: { d: ["M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z", "M19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z"], color: "#c084fc" },
  tool: { d: ["M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"], color: "#f5a524" },
  retriever: { d: ["M14 3H6v18h12V7z", "M14 3v4h4", "M11.5 16.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z", "M13.3 16.3L15 18"], color: "#34d399" },
};
const RunIcon = ({ type }: { type: RunType }) => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke={RUN_ICON[type].color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-label={type} style={{ flex: "none" }}>
    {RUN_ICON[type].d.map((p) => <path key={p} d={p} />)}
  </svg>
);

const RADIUS = 20;
const GUTTER = 24;
/** Gap between a box and its neighbours (the other box in its column, the chat box). */
const GAP = 16;
/** Top boxes start under the Auris logo (fixed at top 24, ~48 tall); bottom boxes end level with the chat card (Dashboard BOTTOM = 64). */
const TOP = 96;
const BOTTOM = 64;
const BOX_H = `calc((100vh - ${TOP + BOTTOM + GAP}px) / 2)`;
/** Each box reaches inward to the chat card's edge: the card is min(600px, 100vw - 32px) wide and centered (Dashboard's chat wrapper) — change BOTH together. */
const BOX_W = `calc((100vw - min(600px, 100vw - 32px)) / 2 - ${GUTTER + GAP}px)`;
const CORNER: Record<Agent["corner"], React.CSSProperties> = {
  tl: { top: TOP, left: GUTTER }, tr: { top: TOP, right: GUTTER }, bl: { bottom: BOTTOM, left: GUTTER }, br: { bottom: BOTTOM, right: GUTTER },
};

const ORB_PX = 72;
/** Flight out of the center orb, seconds: duration, stagger between the four, and the border fade once they land. */
const FLY = 1.6, STAGGER = 0.12, FADE = 0.6;
/** Shooting-star tail: px of tail per px moved in the last frame, capped; peak opacity. Kept subtle — long and faint while fast, gone as the orb lands. */
const TAIL_K = 6, TAIL_MAX = 90, TAIL_ALPHA = 0.35;
/** Info-board dot (one per submit_finding post): px, seconds of flight, stagger between dots from the same poll. */
const DOT_PX = 8, DOT_FLY = 1.1, DOT_STAGGER = 0.18;

type Found = { query?: string; results?: Hit[]; notes?: string[]; langsmith?: { run_id: string; trace_id: string } };

/** A search row's query and hits. Newer events carry them (research.py puts them in data); for older ones the agents server reads them back out of the search's LangSmith tool run. */
function SearchModal({ event, onClose }: { event: StudyEvent; onClose: () => void }) {
  const saved = Array.isArray(event.data?.results);
  const [found, setFound] = useState<Found | "loading" | "missing" | null>(saved ? null : "loading");
  useEffect(() => {
    if (saved) return;
    const traceId = event.trace?.run_id;
    // The summary is "<query, cut at 120> (N results)"; the server matches the run whose query STARTS with it.
    const q = event.summary.replace(/ \(\d+ results?\)$/, "");
    if (!traceId) { setFound("missing"); return; }
    let live = true;
    fetch(`${AGENTS_URL}/langsmith/search?trace_id=${traceId}&query=${encodeURIComponent(q)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((f: Found) => live && setFound(f), () => live && setFound("missing"));
    return () => { live = false; };
  }, [event, saved]);
  const got = typeof found === "object" && found ? found : null;
  useEffect(() => {
    const k = (ev: KeyboardEvent) => ev.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const query = typeof event.data?.query === "string" ? event.data.query : got?.query || event.summary;
  const hits = (saved ? event.data!.results : got?.results ?? []) as Hit[];
  const notes = (saved ? (event.data?.notes ?? []) : got?.notes ?? []) as string[];
  // The recovered run is THIS search's tool call; better than the whole-study fallback.
  const href = got?.langsmith ? `${AGENTS_URL}/langsmith/${got.langsmith.run_id}?trace_id=${got.langsmith.trace_id}` : langsmithHref(event);
  return (
    <div data-testid="search-modal" role="dialog" aria-modal="true" aria-label="Literature search" onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 40, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div onClick={(ev) => ev.stopPropagation()} style={{ width: "min(720px, 100%)", maxHeight: "min(80vh, 760px)", display: "flex", flexDirection: "column", background: "#0b0b0d", border: "1px solid #2a2b2f", borderRadius: 20, color: "#e6e8eb", boxShadow: "0 24px 64px rgba(0,0,0,0.7)" }}>
        <header style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "16px 18px 12px", borderBottom: "1px solid #1c1d20" }}>
          <RunIcon type="retriever" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, color: "#757575", letterSpacing: "0.04em" }}>search_literature · {event.component}</div>
            <div style={{ fontSize: 16, marginTop: 4, lineHeight: 1.35 }}>{query}</div>
          </div>
          {href && <a href={href} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "#7aa2ff", whiteSpace: "nowrap", marginTop: 2 }}>Open in LangSmith</a>}
          <button type="button" aria-label="Close search" onClick={onClose} style={{ width: 28, height: 28, borderRadius: 999, border: 0, background: "#1c1d20", color: "#e6e8eb", cursor: "pointer", flex: "none" }}>×</button>
        </header>
        <ol style={{ listStyle: "none", margin: 0, padding: "8px 18px 16px", overflowY: "auto" }}>
          {hits.length === 0 && <li data-testid="search-empty" style={{ color: "#9aa0a8", fontSize: 13, padding: "8px 0" }}>{found === "loading" ? "Loading what this search found…" : found === "missing" ? "The results of this search could not be found in LangSmith." : "No results."}</li>}
          {hits.map((h, i) => (
            <li key={h.url ?? i} data-testid="search-hit" style={{ padding: "10px 0", borderTop: i ? "1px solid #1c1d20" : undefined }}>
              <a href={h.url} target="_blank" rel="noreferrer" style={{ color: "#e6e8eb", fontSize: 14, textDecoration: "none" }}>{h.title || h.url}</a>
              <div style={{ fontSize: 12, color: "#757575", marginTop: 3 }}>
                {[h.year || "n.d.", h.authors, h.venue].filter(Boolean).join(" · ")}
                {h.open_access !== undefined && <span style={{ marginLeft: 8, color: h.open_access ? "#34d399" : "#9aa0a8" }}>{h.open_access ? "open access" : "may be paywalled"}</span>}
              </div>
              {h.snippet && <p style={{ margin: "6px 0 0", fontSize: 12.5, lineHeight: 1.45, color: "#9aa0a8" }}>{h.snippet}</p>}
            </li>
          ))}
          {notes.map((n) => <li key={n} style={{ fontSize: 12, color: "#9aa0a8", paddingTop: 8 }}>Note: {n}</li>)}
        </ol>
      </div>
    </div>
  );
}

function AgentBox({ agent, events, onSearch }: { agent: Agent; events: StudyEvent[]; onSearch: (e: StudyEvent) => void }) {
  const list = useRef<HTMLDivElement>(null);
  const traces = events.flatMap((e, i) => toTrace(e, events[i + 1]) ?? []);
  useEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" }); }, [traces.length]);
  const summary = summarize(events);

  return (
    // Starts invisible: ResearchBoxes fades it in once its orb has flown into the slot.
    <div data-testid={`agent-${agent.key}`} data-box="" style={{ position: "fixed", ...CORNER[agent.corner], width: BOX_W, height: BOX_H, borderRadius: RADIUS, zIndex: 5, opacity: 0 }}>
      {/* disableGlow: the wandering halo lit random segments along these long edges; the ring alone stays. */}
      <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={RADIUS} disableGlow style={{ width: "100%", height: "100%" }}>
        {/* Explicit height, NOT 100%: MetalFx centers a child that does not resolve its percentage height, so each box's content floated at a different offset. */}
        <div style={{ display: "flex", flexDirection: "column", width: "100%", height: BOX_H, borderRadius: RADIUS, overflow: "hidden" }}>
          {/* Orb centered in the box, title centered below it. */}
          <header style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 4, padding: "12px 14px 8px" }}>
            {/* Empty slot: the orb is the flyer ResearchBoxes launched from the center, parked over this spot — it NEVER swaps for a second canvas, so landing does not pop. */}
            <div data-orb-slot={agent.key} style={{ width: ORB_PX, height: ORB_PX, flex: "none" }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, color: "#e6e8eb" }}>{agent.title}</div>
              <div style={{ fontSize: 11, color: "#757575", letterSpacing: "0.04em" }}>{agent.key}</div>
            </div>
          </header>
          {/* Scrolls, but with NO visible scrollbar (scrollbarWidth; the WebKit rule is in the <style> below). */}
          <div ref={list} data-testid="traces" className="traces-noscroll" style={{ flex: 1, minHeight: 0, overflowY: "auto", scrollbarWidth: "none", margin: "0 10px", padding: "6px 4px", borderTop: "1px solid #1c1d20", borderBottom: "1px solid #1c1d20", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11.5 }}>
            {traces.map((t) => {
              // A search opens its query and hits; every other row opens its run in LangSmith (a new tab). Rows with neither stay plain.
              const href = t.type === "retriever" ? null : langsmithHref(t.event);
              const open = t.type === "retriever" ? () => onSearch(t.event) : href ? () => window.open(href, "_blank", "noopener") : undefined;
              return (
              <div key={t.id} data-testid="trace-row" role={open ? "button" : undefined} tabIndex={open ? 0 : undefined} title={open ? (t.type === "retriever" ? "Show what was searched" : "Open in LangSmith") : undefined}
                onClick={open} onKeyDown={open ? (ev) => (ev.key === "Enter" || ev.key === " ") && (ev.preventDefault(), open()) : undefined}
                className={open ? "trace-row" : undefined}
                style={{ display: "flex", alignItems: "center", gap: 7, padding: "3px 2px", paddingLeft: t.type === "chain" ? 2 : 16, color: "#c9ccd1", borderRadius: 6, cursor: open ? "pointer" : undefined }}>
                <RunIcon type={t.type} />
                <span style={{ flex: "none" }}>{t.name}</span>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#757575" }}>{t.detail}</span>
                {/* The newest row of a working agent is live (●); a finished agent's last row has no time. */}
                {!t.done && <span style={{ flex: "none", color: t.ms === undefined ? "#7aa2ff" : "#5c5f66" }}>{t.ms === undefined ? "●" : `${(t.ms / 1000).toFixed(1)}s`}</span>}
              </div>
              );
            })}
          </div>
          {/* Clamped: a finished agent's summary runs to a paragraph. The full text is the tooltip. */}
          <footer data-testid="summary" title={summary} style={{ margin: "10px 14px 12px", fontSize: 13, lineHeight: "18px", color: "#9aa0a8", minHeight: 36, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{summary}</footer>
        </div>
      </MetalFx>
    </div>
  );
}

/**
 * The four corner boxes. No fill anywhere: only the metal rings and text draw over the page's grid.
 * Opening: each agent's orb flies out of the center orb (`origin`, its rect) to its box's header with a fading tracer, then the boxes fade in. `delay` waits for the center orb to finish moving first.
 * ponytail: slots are measured once on open, not on window resize.
 */
/** `nodes`: the center orb's dots as drawn (Orb's `nodes` prop, the SAME ref object) — info-board dots land on one of them. Without it they land on the orb's center. */
export default function ResearchBoxes({ runId, origin, delay = 0, nodes }: { runId: string; origin: () => DOMRect | null; delay?: number; nodes?: { current: OrbNode[] } }) {
  const [slots, setSlots] = useState<Record<string, DOMRect> | null>(null);
  const [events, setEvents] = useState<StudyEvent[]>([]);
  // Polls while the study runs, then stops: a finished or stopped study's events never change.
  useEffect(() => {
    let live = true, t: ReturnType<typeof setTimeout>;
    const poll = () => studyEvents(runId).then((r) => {
      if (!live) return;
      setEvents(r.events);
      if (r.status === "running") t = setTimeout(poll, POLL_MS);
    }, () => { if (live) t = setTimeout(poll, POLL_MS * 4); });
    void poll();
    return () => { live = false; clearTimeout(t); };
  }, [runId]);
  const flyers = useRef<(HTMLDivElement | null)[]>([]);
  const tails = useRef<(HTMLDivElement | null)[]>([]);
  useLayoutEffect(() => {
    setSlots(Object.fromEntries(AGENTS.map((a) => [a.key, document.querySelector(`[data-orb-slot="${a.key}"]`)!.getBoundingClientRect()])));
  }, []);
  useLayoutEffect(() => {
    if (!slots) return;
    const ctx = gsap.context(() => {
      gsap.set(flyers.current, { opacity: 0 });
      const tl = gsap.timeline({ delay });
      // Origin is read when the flight STARTS (the center orb may still be rising when 5 is pressed).
      tl.call(() => {
        const o = origin(), ox = o ? o.left + o.width / 2 : innerWidth / 2, oy = o ? o.top + o.height / 2 : innerHeight / 2;
        AGENTS.forEach((a, i) => {
          const r = slots[a.key], el = flyers.current[i]!, tail = tails.current[i]!;
          const dx = ox - (r.left + r.width / 2), dy = oy - (r.top + r.height / 2);
          // The tail points back along the path, toward the center orb.
          tail.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
          let px = dx, py = dy;
          gsap.fromTo(el, { x: dx, y: dy, scale: 0.35, opacity: 0 }, {
            x: 0, y: 0, scale: 1, opacity: 1, duration: FLY, ease: "power3.out", delay: i * STAGGER,
            onUpdate() {
              const x = gsap.getProperty(el, "x") as number, y = gsap.getProperty(el, "y") as number;
              const len = Math.min(TAIL_MAX, Math.hypot(x - px, y - py) * TAIL_K);
              px = x; py = y;
              tail.style.width = `${len}px`;
              tail.style.opacity = String(TAIL_ALPHA * (len / TAIL_MAX));
            },
            onComplete: () => { tail.style.width = "0px"; },
          });
        });
      });
      tl.to("[data-box]", { opacity: 1, duration: FADE, ease: "power1.out" }, `+=${FLY + 3 * STAGGER - 0.15}`);
    });
    return () => ctx.revert();
  }, [slots]); // eslint-disable-line react-hooks/exhaustive-deps

  // Each NEW info-board post (submit_finding) sends a white dot from its agent's orb to a random dot on the center orb. Posts already
  // there on the first load are history, NOT news — a reopened session must not fire its whole backlog at once.
  const dots = useRef<HTMLDivElement>(null);
  const posted = useRef<Set<number> | null>(null);
  useEffect(() => {
    const posts = events.filter((e) => e.type === "research.board_posted");
    if (!posted.current) {
      if (events.length) posted.current = new Set(posts.map((e) => e.sequence));
      return;
    }
    const fresh = posts.filter((e) => !posted.current!.has(e.sequence));
    fresh.forEach((e, n) => {
      posted.current!.add(e.sequence);
      // Read from the flyer, not the slot: it is the orb as drawn, even mid-flight.
      const from = flyers.current[AGENTS.findIndex((a) => a.key === e.component)]?.getBoundingClientRect();
      if (!from || !dots.current || !origin()) return;
      // A dot on the FRONT of the sphere (a back one is dim and half hidden), picked once and FOLLOWED: the orb keeps turning while the dot flies.
      const front = (nodes?.current ?? []).flatMap((p, i) => (p[2] > 0.2 ? [i] : []));
      const pick = front.length ? front[Math.floor(Math.random() * front.length)] : -1;
      const target = () => {
        const r = origin()!, p = pick >= 0 ? nodes!.current[pick] : undefined;
        // OrbNode is in the orb's 64-unit design space; the rect carries the orb's on-screen size and scale.
        return p ? { x: r.left + (p[0] / 64) * r.width, y: r.top + (p[1] / 64) * r.height } : { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      };
      const x0 = from.left + from.width / 2, y0 = from.top + from.height / 2;
      const dot = document.createElement("div");
      dot.dataset.testid = "board-dot";
      dot.dataset.node = String(pick); // which center-orb dot it lands on; -1 = the orb's center (no nodes)
      Object.assign(dot.style, { position: "fixed", left: `${-DOT_PX / 2}px`, top: `${-DOT_PX / 2}px`, width: `${DOT_PX}px`, height: `${DOT_PX}px`, borderRadius: "50%", background: "#fff", boxShadow: "0 0 10px 3px rgba(255,255,255,0.6)", opacity: "0", transform: `translate(${x0}px, ${y0}px)` });
      dots.current.appendChild(dot);
      // x and y on DIFFERENT eases bend the path into an arc; the end point is re-read every frame, so the dot lands ON its moving node.
      const ex = gsap.parseEase("power1.in"), ey = gsap.parseEase("power2.out");
      const fly = { p: 0, s: 1 };
      const place = () => {
        const t = target();
        dot.style.transform = `translate(${x0 + (t.x - x0) * ex(fly.p)}px, ${y0 + (t.y - y0) * ey(fly.p)}px) scale(${fly.s})`;
      };
      gsap.timeline({ delay: n * DOT_STAGGER, onComplete: () => dot.remove() })
        .to(dot, { opacity: 1, duration: 0.15 })
        .to(fly, { p: 1, duration: DOT_FLY, ease: "none", onUpdate: place }, 0)
        // Landed: it rides its node while it shrinks into it.
        .to(fly, { s: 0.3, duration: 0.35, ease: "power1.in", onUpdate: place }, DOT_FLY)
        .to(dot, { opacity: 0, duration: 0.35, ease: "power1.in" }, DOT_FLY);
    });
  }, [events]); // eslint-disable-line react-hooks/exhaustive-deps

  const [search, setSearch] = useState<StudyEvent | null>(null);
  return (
    <>
      <style>{`.traces-noscroll::-webkit-scrollbar{display:none}.trace-row:hover,.trace-row:focus-visible{background:#16171a;outline:none}`}</style>
      {AGENTS.map((a) => <AgentBox key={a.key} agent={a} events={events.filter((e) => e.component === a.key)} onSearch={setSearch} />)}
      {search && <SearchModal event={search} onClose={() => setSearch(null)} />}
      {/* Info-board dots fly here (see the posted effect). Above the chat card (10) so a dot lands ON the center orb. Unmounting drops any dot still in flight. */}
      <div ref={dots} style={{ position: "fixed", inset: 0, zIndex: 11, pointerEvents: "none" }} />
      {slots && AGENTS.map((a, i) => (
        <div key={a.key} ref={(el) => { flyers.current[i] = el; }} data-testid={`flyer-${a.key}`} style={{ position: "fixed", left: slots[a.key].left, top: slots[a.key].top, width: ORB_PX, height: ORB_PX, zIndex: 6, pointerEvents: "none" }}>
          {/* Shooting-star tail, BEHIND the orb: tapered to a point (clip-path), brightest at the orb, fading out; width and opacity follow the orb's speed. */}
          <div ref={(t) => { tails.current[i] = t; }} style={{ position: "absolute", left: ORB_PX / 2, top: ORB_PX / 2 - 3, width: 0, height: 6, transformOrigin: "0 50%", opacity: 0, clipPath: "polygon(0 0, 100% 50%, 0 100%)", background: "linear-gradient(to right, #fff, rgba(255,255,255,0))", filter: "blur(0.6px)" }} />
          <div style={{ position: "relative" }}><Orb px={ORB_PX} variant={a.orb} speed={1.6} /></div>
        </div>
      ))}
    </>
  );
}
