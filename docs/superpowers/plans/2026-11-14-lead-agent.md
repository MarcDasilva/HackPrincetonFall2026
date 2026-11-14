# Lead Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LangGraph lead agent that talks to the patient through the orb line once the ear cards vanish, and asks before launching research.

**Architecture:** `horn_study.lead` is a small graph (`lead → confirm`) with an in-memory checkpointer, one conversation per backend run ID. `horn_study.server` exposes it over HTTP on port 8010. The dashboard opens the conversation when `EarViews` finishes, and shows each reply in place of "Processing…".

**Tech Stack:** LangGraph 1.2 (`interrupt`, `Command`, `MemorySaver`), langchain-core 1.8 `with_structured_output`, FastAPI + uvicorn (new in agents), Next.js, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-14-lead-agent-design.md`

## Global Constraints

- Research NEVER starts in this step; `lead.py` does not import `workflow.py`.
- Replies are short: 1–3 sentences (the orb line holds about 3 lines).
- Run IDs are validated (`^[A-Za-z0-9_-]{1,64}$`) before touching the filesystem.
- The server URL is `NEXT_PUBLIC_AGENTS_URL`, default `http://localhost:8010`.

## Review Focus

- Agents server down → the orb line says the assistant is unreachable; the app does not hang. (Task 3 handles it in `talkToLead`'s catch.)
- A run ID with no `job.json` (example run, or data wiped) → the lead still talks, without patient context. (Task 1 test.)
- The patient sends while a reply is pending → ignored, no double request. (Task 3: the send button is disabled while waiting.)
- "No" to launch → the conversation continues, `launch_requested` stays false. (Task 1 test.)
- Server restart mid-conversation → a fresh conversation starts. Accepted for now (spec non-goal).

---

### Task 1: Lead graph

**Files:**
- Create: `agents/src/horn_study/lead.py`
- Test: `agents/tests/test_lead.py`

**Interfaces:**
- Produces:
  - `class LeadTurn(BaseModel)` with fields `reply: str`, `needs: NeedsProfile`, `ask_to_launch: bool`, `launch_confirmed: bool`.
  - `build_lead_graph(model: BaseChatModel, patients_dir: Path) -> CompiledStateGraph`, compiled with `MemorySaver`.
  - `async def lead_turn(graph, run_id: str, message: str) -> dict`, returning `{reply, awaiting_launch, launch_requested, needs}`. The thread is the run ID. An empty message opens the conversation. When the thread is paused at `confirm`, the message resumes it via `Command(resume=message)`.

Graph: `START → lead`. After `lead`:
- `launch_confirmed` → `END`, with `launch_requested = True`;
- `ask_to_launch` → `confirm`;
- otherwise → `END`.

`confirm` calls `interrupt(...)`, appends the answer as a `HumanMessage`, then goes back to `lead`. The lead's system prompt carries the audiogram and ear side from `<patients_dir>/<run_id>/job.json`, or "no patient data" when the file is missing.

- [ ] **Step 1: Write failing tests** with `ScriptedChatModel` from `tests/helpers.py`. Its responder returns tool calls named `LeadTurn`.
  - `test_opening_line_uses_patient_audiogram`: an empty message gives the scripted reply, and the system prompt contains `"4000"`.
  - `test_ask_pauses_and_yes_requests_launch`: the second turn asks; `awaiting_launch` is True. Answering "yes" (scripted `launch_confirmed=True`) gives `launch_requested` True.
  - `test_no_keeps_talking`: after a "no", `launch_requested` is False and `awaiting_launch` is False.
  - `test_missing_job_json_still_answers`.
- [ ] **Step 2:** `uv run pytest tests/test_lead.py`. Expect FAIL (import error).
- [ ] **Step 3:** Implement `lead.py`.
- [ ] **Step 4:** `uv run pytest`. Expect all to pass.
- [ ] **Step 5:** Commit.

### Task 2: HTTP server

**Files:**
- Create: `agents/src/horn_study/server.py`
- Modify: `agents/pyproject.toml` (add `fastapi`, `uvicorn`)
- Test: `agents/tests/test_server.py`

**Interfaces:**
- Consumes: `build_lead_graph`, `lead_turn`.
- Produces:
  - `POST /lead/{run_id}` with body `{"message": str}`, returning `{reply, awaiting_launch, launch_requested}`;
  - `GET /health` → `{"ok": true}`.
  - `app` loads `.env` and builds the graph lazily with `llm.load_model("coordinator")`. CORS is open.

- [ ] **Step 1:** Write failing tests with FastAPI's `TestClient`, overriding the graph with the scripted model.
  - `test_lead_route_round_trip`;
  - `test_bad_run_id_is_rejected_400`, using the run ID `"../x"`.
- [ ] **Step 2:** `uv add fastapi uvicorn`, then implement. Run `uv run pytest`; expect all to pass.
- [ ] **Step 3:** Live smoke test: `uv run uvicorn horn_study.server:app --port 8010`, then curl one real turn.
- [ ] **Step 4:** Commit.

### Task 3: Dashboard wiring

**Files:**
- Create: `frontend/lib/lead.ts`
- Modify: `frontend/components/EarViews.tsx` (add an `onGone` prop, called when the collapse finishes)
- Modify: `frontend/app/dashboard/Dashboard.tsx` (lead state, orb line, submit routing)
- Test: `frontend/e2e/lead.spec.ts`

**Interfaces:**
- Produces: `talkToLead(runId: string, message: string): Promise<{ reply: string; awaiting_launch: boolean; launch_requested: boolean }>`.

Changes to `Dashboard.tsx`:
- **State:** `lead: { line: string; waiting: boolean } | null`.
- **Opening:** on `onGone`, set `{line: "", waiting: true}` and call `talkToLead(run.id, "")`.
- **Orb sub-text:** shows `lead.line` (or "…" while waiting) whenever `lead` is set; otherwise "Processing…", as today.
- **Submit:** when `lead` is set, posts the textarea text to the lead instead of starting a run.

- [ ] **Step 1:** Write a failing Playwright spec. Use `e2e/mockBackend.ts` for the run, and route `**/lead/**` to return a scripted reply.
  - After the cards vanish, `[data-testid=orb] [role=status]` shows the opening reply.
  - Typing "what is this?" and pressing Send shows the second reply, and the route received that text.
  - Take a screenshot.
- [ ] **Step 2:** Implement. Run `npx playwright test`; expect all to pass. Read the screenshot.
- [ ] **Step 3:** Commit.
