"""HTTP front for the lead, for the dashboard (frontend/lib/lead.ts).

cd agents && uv run uvicorn horn_study.server:app --port 8010
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from horn_study.lead import build_lead_graph, lead_turn

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class State:
    graph: Any = None


state = State()
app = FastAPI(title="horn-study lead")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Message(BaseModel):
    message: str = ""


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/lead/{run_id}")
async def lead(run_id: str, body: Message) -> dict[str, Any]:
    # The run ID keys the conversation; the backend's IDs are plain, so anything else is a bad request.
    if not RUN_ID.match(run_id):
        raise HTTPException(400, "bad run id")
    if state.graph is None:
        state.graph = build_lead_graph()
    out = await lead_turn(state.graph, run_id, body.message[:2000])
    return {k: out[k] for k in ("reply", "awaiting_launch", "launch_requested")}
