"""User-requested follow-up studies.

A follow-up proposal in a report is inert text. A follow-up study exists only
when a user asks for one, and then it is a new study with its own ID that
links to its parent. The parent's saved record is read, never rewritten.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from horn_study.contracts import PriorStudyContext


class FollowUpError(Exception):
    pass


def _read(root: Path, study_id: str, name: str) -> Any:
    path = Path(root) / study_id / name
    if not path.exists():
        raise FollowUpError(f"Study '{study_id}' has no saved {name} under {root}.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_prior_study(root: Path, parent_study_id: str, proposal_id: str | None = None) -> PriorStudyContext:
    """Summarize a saved parent study as read-only context for a new one."""
    results = _read(root, parent_study_id, "results.json")
    report = results.get("report") or {}
    proposal = None
    if proposal_id is not None:
        proposal = next(
            (p for p in report.get("follow_up_proposals", []) if p.get("proposal_id") == proposal_id),
            None,
        )
        if proposal is None:
            raise FollowUpError(f"Study '{parent_study_id}' has no follow-up proposal '{proposal_id}'.")
    return PriorStudyContext(
        parent_study_id=parent_study_id,
        follow_up_proposal=proposal,
        selected_candidate_id=report.get("selected_candidate_id"),
        selected_candidate=results.get("selected_candidate"),
        hypothesis_verdicts=tuple(
            {
                "hypothesis_id": h.get("hypothesis_id"),
                "verdict": h.get("verdict"),
                "explanation": h.get("explanation"),
            }
            for h in report.get("hypotheses", [])
        ),
        summary=report.get("summary", ""),
    )


def follow_up_request(
    root: Path,
    parent_study_id: str,
    proposal_id: str,
    new_study_id: str,
    needs_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the request for a new study from a proposal the user selected.

    This only builds a request. Nothing runs until the user starts it.
    """
    prior = load_prior_study(root, parent_study_id, proposal_id)
    assert prior.follow_up_proposal is not None
    original = _read(root, parent_study_id, "request.json")["original"]
    request = dict(original)
    request["study_id"] = new_study_id
    request["parent_study_id"] = parent_study_id
    request["start"] = {
        "initiated_by": "user",
        "action": prior.follow_up_proposal["kind"],
        "follow_up_proposal_id": proposal_id,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    if needs_profile is not None:
        request["needs_profile"] = needs_profile
    return request
