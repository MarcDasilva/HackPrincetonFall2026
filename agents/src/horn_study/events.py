"""Progress events and per-study artifacts for the frontend.

Events are an append-only, strictly ordered history of what the study did.
They carry short user-facing summaries and identifiers, never hidden model
reasoning and never binary assets.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from horn_study.contracts import Contract, StudyState

EventType = Literal[
    "study.started",
    "study.state_changed",
    "orchestrator.assigned",
    "orchestrator.evidence_opened",
    "orchestrator.note_written",
    "research.agent_started",
    "research.source_read",
    "research.finding_added",
    "research.agent_completed",
    "research.agent_failed",
    "hypothesis.created",
    "plan.revision_requested",
    "plan.frozen",
    "experiment.started",
    "experiment.retried",
    "experiment.completed",
    "experiment.failed",
    "report.completed",
    "study.completed",
    "study.failed",
    "study.cancelled",
]

ARTIFACT_NAMES = (
    "request.json",
    "capabilities.json",
    "research.json",
    "plan.json",
    "events.jsonl",
    "experiment_results.json",
    "results.json",
)


class TraceRef(Contract):
    run_id: str
    project: str | None = None
    tracing_enabled: bool = False


class StudyEvent(Contract):
    study_id: str
    sequence: int
    timestamp: datetime
    phase: StudyState
    component: str
    type: EventType
    summary: str
    finding_ids: tuple[str, ...] = ()
    hypothesis_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    experiment_ids: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    trace: TraceRef | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    replay: bool = False


class StudyExists(Exception):
    pass


class ArtifactStore:
    """One directory per study. An existing study is never overwritten."""

    def __init__(self, root: Path, study_id: str) -> None:
        self.root = Path(root)
        self.study_id = study_id
        self.directory = self.root / study_id

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.directory.mkdir()
        except FileExistsError as exc:
            raise StudyExists(
                f"A study named '{self.study_id}' is already saved at {self.directory}. "
                "Studies are kept as records; start the new one under a different study_id."
            ) from exc

    def path(self, name: str) -> Path:
        return self.directory / name

    def write_json(self, name: str, value: Any) -> Path:
        target = self.path(name)
        payload = json.dumps(_plain(value), indent=2, sort_keys=False, ensure_ascii=False)
        handle, temp_name = tempfile.mkstemp(dir=self.directory, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload + "\n")
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return target

    def append_event(self, event: StudyEvent) -> None:
        with self.path("events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")

    def read_json(self, name: str) -> Any:
        return json.loads(self.path(name).read_text(encoding="utf-8"))

    def exists(self) -> bool:
        return self.directory.is_dir()


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def read_events(store: ArtifactStore) -> list[StudyEvent]:
    path = store.path("events.jsonl")
    if not path.exists():
        return []
    return [
        StudyEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


EventListener = Callable[[StudyEvent], None]


class EventBus:
    """Assigns monotonic sequence numbers, persists, and fans out to listeners.

    Emitting is serialized, so the saved history, the in-memory history, and
    what listeners see are always in the same order, whichever thread emits.
    """

    def __init__(
        self,
        study_id: str,
        store: ArtifactStore | None = None,
        listeners: Iterable[EventListener] = (),
        trace: TraceRef | None = None,
    ) -> None:
        self.study_id = study_id
        self._store = store
        self._listeners = list(listeners)
        self._sequence = 0
        self._lock = threading.Lock()
        self._trace = trace
        self.phase = StudyState.CREATED
        self.history: list[StudyEvent] = []

    def emit(
        self,
        type: EventType,
        summary: str,
        *,
        component: str,
        finding_ids: Iterable[str] = (),
        hypothesis_ids: Iterable[str] = (),
        candidate_ids: Iterable[str] = (),
        experiment_ids: Iterable[str] = (),
        artifacts: Iterable[str] = (),
        data: dict[str, Any] | None = None,
    ) -> StudyEvent:
        with self._lock:
            self._sequence += 1
            event = StudyEvent(
                study_id=self.study_id,
                sequence=self._sequence,
                timestamp=datetime.now(UTC),
                phase=self.phase,
                component=component,
                type=type,
                summary=summary,
                finding_ids=tuple(finding_ids),
                hypothesis_ids=tuple(hypothesis_ids),
                candidate_ids=tuple(candidate_ids),
                experiment_ids=tuple(experiment_ids),
                artifacts=tuple(artifacts),
                trace=self._trace,
                data=_plain(data or {}),
            )
            self.history.append(event)
            if self._store is not None:
                self._store.append_event(event)
            for listener in self._listeners:
                listener(event)
        return event
