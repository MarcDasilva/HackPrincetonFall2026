"""HTTP front for the lead, for the dashboard (frontend/lib/lead.ts).

    cd agents && uv run uvicorn horn_study.server:app --port 8010

Patient data is read from the backend's folder: HORN_STUDY_PATIENTS_DIR, default
../backend/data/patients beside this repo's agents/ (the backend's DATA_DIR default).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from horn_study.lead import build_lead_graph, lead_turn
from horn_study.llm import load_model

PATIENTS_DIR = Path(
    os.environ.get(
        "HORN_STUDY_PATIENTS_DIR", Path(__file__).resolve().parents[3] / "backend" / "data" / "patients"
    )
)
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
    # The run ID is joined onto PATIENTS_DIR — anything but a plain ID could read outside it.
    if not RUN_ID.match(run_id):
        raise HTTPException(400, "bad run id")
    if state.graph is None:
        # .env loads HERE, not at import — importing this module must not switch on tracing for the test suite.
        load_dotenv(find_dotenv(usecwd=True))
        state.graph = build_lead_graph(load_model("coordinator"), PATIENTS_DIR)
    out = await lead_turn(state.graph, run_id, body.message[:2000])
    return {k: out[k] for k in ("reply", "awaiting_launch", "launch_requested")}
