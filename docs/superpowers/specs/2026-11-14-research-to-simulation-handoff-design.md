# Research to simulation handoff

## Intent

When the four research agents finish, the lead asks the patient how many simulations to run. A scene picker then chooses every other setting for each simulation from the patient's profile and the research findings. The patient never picks angles, clips or levels.

## Goals

- The study pauses after `synthesize_evidence` and resumes when the patient answers.
- The lead asks one question: how many simulations (bounded 1 to 100, default 4; `Budget.max_evaluation_cases` (default 12, ceiling 500) is set to the count so the study does not reject its own plan).
- The scene picker returns N scenes, each justified in a line from the research or profile. Up to 20 scenes per model call; larger counts run several calls, each told which scenes already exist so they spread across angles, clips and levels.
- The planner receives those scenes as its scenarios; the report shows each scene's reason.

## Non-goals

- Angle does not change any score yet. The evaluator has no angle input, so `azimuth_deg` is a recorded scene setting (call (a), chosen by the user). The 3D wave check (0 to 180 degrees) is not wired in.
- No LangGraph checkpointer, no split into two runs.
- No target frequency band; "frequency dB" is read as level in dB SPL.

## Approaches

1. Pause inside the graph with one awaited hook before `plan_experiments` (chosen): smallest diff; a server restart while waiting reads as "stopped", as today.
2. Split into two runs: cleaner boundary, but rewrites `run_study` start and finish handling.
3. LangGraph interrupt and resume: needs a checkpointer nothing else here uses.

## Design

- `StudyDependencies` gains an optional `choose_scenes(evidence) -> scenes` hook, awaited between `NODE_SYNTHESIZE` and `NODE_PLAN` (`workflow.py`). Absent, the study runs as today (CLI, tests).
- `server.py` implements the hook: it sets the session stage to `count`, then awaits an `asyncio.Future` that `post_lead` resolves with the patient's number. Stage `count` is part of `lead.py`'s fixed copy, so no model is called for the question. A non-number reply re-asks.
- Scene fields the model picks, each from a fixed menu so the evaluator never sees an unknown value:
  - `clip`: a Harvard sentence or a sound-library label, matched to the patient's stated situations.
  - `level_db_spl`: from the evaluator's declared levels, capped by the patient's audiogram.
  - `noise`: none, babble or reverb.
  - `snr_db`: for babble only.
  - `azimuth_deg`: 0 to 359, recorded.
  - `noise_azimuth_deg`: recorded.
  - `rt60_s`: for reverb, recorded.
  - `reason`: one sentence.
- Not picked by the model: the audiogram (from the profile), ear-canal samples (the evaluator samples them), and the aid design (the planner).
- Only `clip`, `level_db_spl` and `snr_db` change the HASPI score today.

## Left to the builder

Scene schema validation and retry on a bad pick; the exact stage names; the test that a study with no hook still runs unchanged.
