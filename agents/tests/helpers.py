"""Test doubles: a scripted chat model, offline evidence sources, and request builders.

The scripted model stands in for a provider so the workflow can be exercised
deterministically. It is never used outside tests.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field

from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator
from horn_study.sources import FetchedSource, SearchHit, SourceUnavailable
from horn_study.workflow import StudyDependencies

Responder = Callable[[list[BaseMessage], list[str]], AIMessage]


class ModelLog:
    def __init__(self) -> None:
        self.bound_tool_sets: list[list[str]] = []
        self.calls = 0
        self.active = 0
        self.max_active = 0


class ScriptedChatModel(BaseChatModel):
    responder: Responder
    log: ModelLog = Field(default_factory=ModelLog)
    bound: list[str] = Field(default_factory=list)
    delay: float = 0.01

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        names = [t["name"] if isinstance(t, dict) else getattr(t, "name", "") for t in tools]
        self.log.bound_tool_sets.append(names)
        return self.model_copy(update={"bound": names})

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.log.calls += 1
        return ChatResult(generations=[ChatGeneration(message=self.responder(messages, self.bound))])

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.log.calls += 1
        self.log.active += 1
        self.log.max_active = max(self.log.max_active, self.log.active)
        try:
            await asyncio.sleep(self.delay)
            return ChatResult(generations=[ChatGeneration(message=self.responder(messages, self.bound))])
        finally:
            self.log.active -= 1


def call(name: str, args: dict[str, Any], call_id: str = "call") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


# --------------------------------------------------------------------------
# Offline evidence
# --------------------------------------------------------------------------

PAPER_TEXT = (
    "Abstract. This placeholder document exists only for automated tests of the workflow.\n"
    "It stands in for a source that an investigator searched for, fetched, and read in full.\n"
    "The acoustic path length of a horn shifts the frequency region where its response peaks.\n"
    "Listeners with elevated high-frequency thresholds depend on audibility between 2 and 4 kHz.\n"
    "Competing talkers reduce the audibility margin available in everyday listening situations.\n"
    "A shell that seals the canal entrance raises the occlusion effect unless it is vented.\n"
    + "Filler sentence so that the document is long enough to be treated as readable text. "
    * 6
)
PASSAGES = {
    "hearing_research": "Listeners with elevated high-frequency thresholds depend on audibility between 2 and 4 kHz.",
    "use_context_research": "Competing talkers reduce the audibility margin available in everyday listening situations.",
    "acoustic_design_research": "The acoustic path length of a horn shifts the frequency region where its response peaks.",
    "ear_fit_research": "A shell that seals the canal entrance raises the occlusion effect unless it is vented.",
}
PREFIX = {
    "hearing_research": "hearing",
    "use_context_research": "context",
    "acoustic_design_research": "design",
    "ear_fit_research": "fit",
}
TITLES = {
    "hearing research investigator": "hearing_research",
    "use-context investigator": "use_context_research",
    "acoustic-design investigator": "acoustic_design_research",
    "ear-fit investigator": "ear_fit_research",
}


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, limit: int = 6) -> tuple[list[SearchHit], list[str]]:
        self.queries.append(query)
        slug = query.replace(" ", "-")
        return (
            [
                SearchHit(
                    title=f"Test source about {query}",
                    url=f"https://papers.example.org/{slug}",
                    year=2020,
                    authors="A. Tester",
                    venue="Journal of Tests",
                    snippet="A snippet that is only a lead.",
                    open_access=True,
                    backend="fake",
                )
            ],
            [],
        )


class FakeReader:
    def __init__(self, unavailable: set[str] | None = None) -> None:
        self.fetched: list[str] = []
        self.unavailable = unavailable or set()

    async def fetch(self, url: str) -> FetchedSource:
        self.fetched.append(url)
        await asyncio.sleep(0)
        if url in self.unavailable:
            raise SourceUnavailable("The server answered HTTP 403.")
        return FetchedSource(
            url=url, final_url=url, title=f"Paper at {url}", content_type="html", text=PAPER_TEXT
        )


def investigator_of(messages: list[BaseMessage]) -> str:
    system = next(m for m in messages if isinstance(m, SystemMessage))
    text = system.text if isinstance(system.text, str) else str(system.content)
    return next(name for title, name in TITLES.items() if f"You are the {title}" in text)


def research_responder(messages: list[BaseMessage], bound: list[str]) -> AIMessage:
    """Search once, read the hit, record one verified finding, then report."""
    who = investigator_of(messages)
    step = sum(1 for m in messages if isinstance(m, AIMessage))
    url = f"https://papers.example.org/{who}"
    if step == 0:
        return call("search_literature", {"query": who}, f"{who}-1")
    if step == 1:
        return call("read_source", {"url": url, "focus": "audibility horn"}, f"{who}-2")
    if step == 2:
        return call(
            "record_finding",
            {
                "question": f"Question for {who}",
                "source": url,
                "claim": f"Claim recorded by {who}.",
                "evidence_passage": PASSAGES[who],
                "applicability": "Applies only as a test placeholder.",
                "limitations": "Synthetic test text.",
                "related_user_goal": "follow_conversation",
                "motivates": "Compare horn lengths.",
            },
            f"{who}-3",
        )
    return call("InvestigatorOutput", investigator_report(who), f"{who}-4")


def investigator_report(who: str, **overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "summary": f"{who} finished.",
        "candidate_hypotheses": [
            {
                "statement": "Path length changes the response in the target region.",
                "supporting_finding_ids": [f"{PREFIX[who]}-F1"],
                "suggested_comparison": "Vary length_mm.",
            }
        ],
        "suggested_scenario_ids": ["quiet_conversation"],
        "suggested_metric_names": ["fixture_audible_speech_fraction"],
        "suggested_comparisons": [],
        "model_limitations": [],
        "untested_needs": [],
        "conflicting_goals": [],
        "evidence_gaps": [],
        "future_work": [],
    }
    report.update(overrides)
    return report


def design(candidate_id: str, length: float, mouth: float = 30.0) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "kind": "design",
        "family_id": "conical_horn_fixture",
        "baseline_id": "",
        "parameters": [
            {"name": "length_mm", "value": length, "choice": ""},
            {"name": "throat_diameter_mm", "value": 4.0, "choice": ""},
            {"name": "mouth_diameter_mm", "value": mouth, "choice": ""},
        ],
        "label": f"Conical {length:g} mm",
        "rationale": "Length sweep.",
    }


def need(name: str, classification: str = "modeled", **fields: Any) -> dict[str, Any]:
    return {
        "need": name,
        "classification": classification,
        "scenario_ids": [],
        "metric_names": [],
        "explanation": "",
        **fields,
    }


def valid_draft(needs: bool = True) -> dict[str, Any]:
    return {
        "rationale": "Compare three path lengths against the unaided control.",
        "hypotheses": [
            {
                "hypothesis_id": "H1",
                "statement": "Within the allowed range, path length changes the modeled audible fraction.",
                "supporting_finding_ids": ["design-F1", "hearing-F1"],
                "user_goals": ["follow_conversation"],
                "candidate_ids": ["len30", "len45", "len90"],
                "metric": "fixture_audible_speech_fraction",
                "varied_parameter": "length_mm",
                "scenario_ids": [],
                "supports_if": "The mean differs across lengths.",
                "contradicts_if": "The mean is the same for every length.",
            }
        ],
        "candidates": [
            {
                "candidate_id": "unaided",
                "kind": "baseline",
                "family_id": "",
                "baseline_id": "unaided",
                "parameters": [],
                "label": "Unaided",
                "rationale": "Control.",
            },
            design("len30", 30),
            design("len45", 45),
            design("len90", 90),
        ],
        "scenario_ids": ["quiet_conversation", "speech_in_babble", "distant_talker"],
        "canal_config_ids": [],
        "seeds": [],
        "fidelity": "",
        "selection": {
            "primary_metric": "fixture_audible_speech_fraction",
            "reference_candidate_id": "unaided",
            "tie_breaker_metrics": ["fixture_device_length_mm"],
            "constraints": [{"metric": "fixture_device_length_mm", "bound": "max", "value": 100}],
        },
        "needs_coverage": (
            [
                need("sports", scenario_ids=["distant_talker"], explanation="Coach at a distance."),
                need("busy_restaurants", scenario_ids=["speech_in_babble"]),
                need("follow_conversation", metric_names=["fixture_audible_speech_fraction"]),
                need("hear_coach", scenario_ids=["distant_talker"]),
                need("speech_clarity", metric_names=["fixture_audible_speech_fraction"]),
                need("compact_size", metric_names=["fixture_device_length_mm"]),
                need("secure_retention", "untested", explanation="No mechanical model."),
            ]
            if needs
            else []
        ),
        "conflicting_goals": [],
        "future_work": ["Physical retention testing."],
    }


REVIEW_TEXT = "Evidence review: the cited findings hold up for the comparisons the evaluator can run."


def reviews_first(plan: Responder) -> Responder:
    """The coordinator's evidence review (planner.review_evidence) runs before the plan call and binds no PlanDraft:
    answer it with a fixed review, unless the responder scripts the review itself (`reviews = True`)."""

    def respond(messages: list[BaseMessage], bound: list[str]) -> AIMessage:
        if "PlanDraft" not in bound and not getattr(plan, "reviews", False):
            return AIMessage(content=REVIEW_TEXT)
        return plan(messages, bound)

    return respond


def coordinator_responder(*drafts: dict[str, Any]) -> Responder:
    """Return each draft in turn, one per planning round."""

    def respond(messages: list[BaseMessage], bound: list[str]) -> AIMessage:
        rounds = sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)
        draft = drafts[min(rounds, len(drafts) - 1)]
        return call("PlanDraft", copy.deepcopy(draft), f"plan-{rounds}")

    return respond


def narrative(**overrides: Any) -> dict[str, Any]:
    base = {
        "summary": "Fixture placeholder numbers, not simulation results. One design ranked first.",
        "hypothesis_verdicts": [
            {"hypothesis_id": "H1", "verdict": "supported", "explanation": "Means differ across lengths."}
        ],
        "limitations": ["Fixture output only."],
        "inconclusive_findings": [],
        "follow_up_proposals": [
            {
                "kind": "refine_design",
                "title": "Refine around the selected length",
                "description": "Compare lengths near the selected design.",
                "rationale": "The sweep was coarse.",
            }
        ],
    }
    base.update(overrides)
    return base


def interpreter_responder(payload: dict[str, Any] | None = None) -> Responder:
    def respond(messages: list[BaseMessage], bound: list[str]) -> AIMessage:
        return call("ReportNarrative", copy.deepcopy(payload or narrative()), "report-1")

    return respond


def measurements(ear: str = "right", **overrides: Any) -> list[dict[str, Any]]:
    values = {250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 8000: 50}
    return [
        {
            "ear": ear,
            "frequency_hz": f,
            "threshold_db_hl": t,
            "measurement_type": "air_conduction",
            "status": "measured",
            **overrides,
        }
        for f, t in values.items()
    ]


def make_request(study_id: str = "study_test_001", *, needs: bool = True, **overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema_version": "1",
        "study_id": study_id,
        "parent_study_id": None,
        "mode": "personalized",
        "evaluation_mode": "development_fixture",
        "development_fixture_label": "Fictional thresholds for automated tests.",
        "start": {"initiated_by": "user", "action": "start_study"},
        "hearing_profile": {
            "profile_id": "entered_test_example",
            "source": "user_entered_test_results",
            "target_ear": "right",
            "measurements": measurements(),
            "user_notes": "",
        },
        "anatomy": {"ear_mesh_ref": None, "source": "not_supplied"},
        "budget": {
            "max_evaluation_cases": 12,
            "max_parallel_evaluations": 2,
            "max_research_tool_calls_per_agent": 6,
        },
    }
    if needs:
        request["needs_profile"] = {
            "activities": ["sports", "busy restaurants"],
            "goals": ["follow_conversation", "hear_coach"],
            "priorities": ["speech_clarity", "compact_size"],
            "requirements": ["secure_retention"],
            "free_text": "I want to hear people during activities.",
        }
    request.update(overrides)
    return request


class CountingEvaluator:
    """Wraps an evaluator and records every evaluate call."""

    def __init__(self, inner: Any | None = None) -> None:
        self.inner = inner or DevelopmentFixtureEvaluator()
        self.calls: list[str] = []
        self.capability_reads = 0

    def get_evaluator_capabilities(self) -> Any:
        self.capability_reads += 1
        return self.inner.get_evaluator_capabilities()

    def evaluate_experiment(self, spec: Any) -> Any:
        self.calls.append(spec.experiment_id)
        return self.inner.evaluate_experiment(spec)


class Harness:
    def __init__(
        self,
        root: Path,
        *,
        research: Responder = research_responder,
        coordinator: Responder | None = None,
        interpreter: Responder | None = None,
        evaluator: Any | None = None,
        reader: FakeReader | None = None,
        callbacks: list[Any] | None = None,
        use_cache: bool = False,
    ) -> None:
        self.research_model = ScriptedChatModel(responder=research)
        self.coordinator_model = ScriptedChatModel(
            responder=reviews_first(coordinator or coordinator_responder(valid_draft()))
        )
        self.interpreter_model = ScriptedChatModel(responder=interpreter or interpreter_responder())
        self.evaluator = evaluator or CountingEvaluator()
        self.search = FakeSearch()
        self.reader = reader or FakeReader()
        self.deps = StudyDependencies(
            evaluator=self.evaluator,
            research_model=self.research_model,
            coordinator_model=self.coordinator_model,
            interpreter_model=self.interpreter_model,
            search=self.search,
            reader=self.reader,
            studies_root=root,
            use_cache=use_cache,
            callbacks=callbacks or [],
        )


def tool_messages(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]
