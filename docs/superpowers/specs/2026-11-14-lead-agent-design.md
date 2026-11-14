# Lead agent in the dashboard

## Intent

Once the ear cards shrink into the orb, a lead agent takes over the conversation. It is the front door of Jeffrey's LangGraph study: it answers the patient's questions, learns what they need the aid for, and asks whether to launch the research agents. A yes is recorded but research does NOT start yet. This step proves the conversation and the hand-off point.

## Goals

- The lead activates when the ear cards disappear, and opens with its first line unprompted.
- Its replies appear in the SAME spot as "Processing…" under the orb, replacing it. Only the latest reply shows; it wraps onto several lines. There are no chat bubbles and no history.
- Typing in the chat box and sending talks to the lead.
- The lead asks about activities, goals and priorities (the study's `NeedsProfile`) and answers questions about the run.
- When it has enough, it asks "launch the research agents?". A yes ends the lead with a filled `NeedsProfile` and a `launch_requested` flag.

## Non-goals

- Running research, planning or evaluation. They stay paused until the next step.
- Saving conversations across a server restart.
- Streaming tokens. One reply per message; streaming can come later.
- Reading uploaded audiogram PDFs.

## Anti-goals

- A chat panel or message list. The orb line is the whole interface.
- Research starting without an explicit yes from the patient.

## Approaches

1. **Small server in `agents/` (picked).** A FastAPI server (`horn_study.server`) on port 8010. LangGraph keeps each conversation in memory (`MemorySaver`), keyed by run ID. Replies are fast. Costs: a third process to run, and `fastapi` and `uvicorn` added to the agents environment.
2. **Through the backend.** One server, but every message starts the agents' Python as a separate process (2–3 s), and the conversation has to be saved to disk between messages.
3. **A Next.js route that runs Python.** Rejected: it mixes environments for no gain.

Marc picked 1 for responsiveness.

## Design

**Agents: `agents/src/horn_study/lead.py`.** The lead is its own small LangGraph graph in front of the study graph: `START → lead → END`. The `lead` node calls the coordinator model (`llm.load_model("coordinator")`) with:

- a system prompt;
- the run's context: the audiogram and ear side, read from `backend/data/patients/<run_id>/job.json`;
- the conversation so far.

The model returns structured output: `{reply, needs: NeedsProfile, ask_to_launch: bool}`. When `ask_to_launch` is true, the graph pauses with LangGraph's `interrupt`. A yes resumes it and sets `launch_requested`; a no resumes it, and the conversation continues.

Jeffrey's `workflow.py` is left untouched. The hand-off ("on yes, build a `StudyRequest` from `NeedsProfile` and run the study graph") is the next step.

**Agents: `agents/src/horn_study/server.py`.** It exposes two routes:

- `POST /lead/{run_id}` with `{message}` (empty to open), which returns `{reply, awaiting_launch, launch_requested}`;
- `GET /health`.

It loads `.env`, has CORS open like the backend, and starts with `uvicorn horn_study.server:app --port 8010` from `agents/`.

**Frontend.**
- `EarViews` gets an `onGone` callback.
- `Dashboard` holds `lead` state, `{line, awaiting}`. On `onGone`, it posts an empty message to open the conversation.
- While the lead is active, the orb's sub-text shows `lead.line` instead of "Processing…", and the form's submit posts the textarea text to the lead instead of starting a run.
- `lib/lead.ts` holds the fetch, with `NEXT_PUBLIC_AGENTS_URL` defaulting to `http://localhost:8010`.

**Tests.**
- **Agents:** a pytest for the lead graph with a fake chat model. It checks that the opening line arrives, that a reply asking to launch pauses the graph, and that a yes sets `launch_requested` and never starts research.
- **Frontend:** a Playwright spec with the lead mocked. After the cards vanish, the orb line shows the lead's reply, and sending text reaches the lead.

## Left to the builder

- The exact system-prompt wording.
- How long a reply can be before it crowds the orb (cap around 2–3 short lines).
- How a no to launch is phrased back.
