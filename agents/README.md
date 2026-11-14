# horn-study: research and experiment-planning agents

This package is the agent workstream for the passive acoustic hearing device project.
It takes a profile with existing hearing-test results and optional needs, researches the question in three parallel branches, forms hypotheses, freezes one finite experiment plan, sends that plan to the team's evaluator, explains the returned results, and stops.

The product starts after hearing testing.
Users supply their existing results.
Nothing here conducts a hearing test, decides whether someone is deaf, or produces a diagnosis.

A study runs once.
A follow-up is a new study that a user has to start.

## Quick start

```bash
cd agents
uv sync
cp .env.example .env        # then fill in the keys

uv run horn-study capabilities                                  # what the evaluator supports
uv run horn-study validate examples/requests/dev_with_needs.json
uv run horn-study run examples/requests/dev_with_needs.json     # one full study
uv run horn-study replay dev_with_needs_001                     # re-emit a recorded study
```

`run` needs a chat model key.
The default model is `anthropic:claude-sonnet-5-5`, so set `ANTHROPIC_API_KEY`.
Any `provider:model` string that LangChain's `init_chat_model` understands works through `HORN_STUDY_MODEL`.
`validate`, `capabilities`, `follow-up` (without `--run`), and `replay` need no keys.

Exit codes: `0` completed, `1` failed, `2` input rejected, `3` configuration problem.

## How a study runs

```mermaid
flowchart TD
    I["Validate input, read capabilities, create study"]
    I --> H["hearing_research"]
    I --> U["use_context_research"]
    I --> A["acoustic_design_research"]
    H --> S["synthesize_evidence"]
    U --> S
    A --> S
    S --> P["plan_experiments (coordinator)"]
    P --> V["validate_and_freeze_plan"]
    V -- "validation errors, before freezing" --> P
    V --> E["evaluate_batch"]
    E --> R["interpret_results"]
    R --> D["COMPLETED"]
```

States: `CREATED -> RESEARCHING -> PLANNING -> PLAN_FROZEN -> EVALUATING -> INTERPRETING -> COMPLETED`, with terminal `FAILED` and `CANCELLED`.

The only cycle is between planning and validation, and it closes before the plan is frozen.
No edge leads from evaluation or interpretation back to planning.

| Phase | Who | Can do | Cannot do |
| --- | --- | --- | --- |
| Research | Three Deep Agents, run concurrently by LangGraph | Search literature, read sources, record findings, read saved source text | Run the evaluator, write files, run shell commands, spawn subagents |
| Planning | Coordinator model with no tools | Propose hypotheses, candidates, scenarios, and a selection rule | Freeze its own plan, skip the coverage the evaluator requires, or relax the per-scenario rule. Code validates the plan against capabilities and budget. |
| Evaluation | Bounded runner (code) | Evaluate each frozen spec, retry the identical spec after a transient failure | Change a spec, add a case, turn a failure into a number |
| Interpretation | Model with no tools | Explain the computed comparison, judge hypotheses, suggest follow-ups | Change scores or the selection, run anything |

### What code decides, not a model

- Whether supplied hearing data is usable (`intake.py`).
- Whether a finding is accepted: its source must have been read in this study, and its quoted passage must appear in the text that was read (`research.py`).
- Whether a plan is executable and within budget (`planner.py`).
- Whether a plan covers what the evaluator requires of every study: enough scenarios, and at least one of each required kind (`planner.py`).
- Every aggregate, the candidate ranking, and `selected_candidate_id` (`reporting.py`).
- A hypothesis verdict is forced to `inconclusive` when any of its cases did not complete.

### The selection rule

The rule is frozen with the plan as `selection_rule` and applied by code in `reporting.py`.
A design is eligible only if all of these hold:

- It completed every planned case.
- It meets every constraint in the plan.
- In every scenario of the plan, its primary-metric result is not worse than the reference control's result in that same scenario.
- Its primary-metric mean over all cases is better than the control's.

The per-scenario check is always on.
The coordinator cannot turn it off, and `selection_rule.require_not_worse_than_reference_in_every_scenario` is always `true`.
"Not worse" allows for metric noise: a design may fall short of the control in a scenario by at most `selection_rule.scenario_tolerance`.
That tolerance is the primary metric's declared `resolution`, copied into the plan when it is built, and it is 0 when the evaluator declares none.
A design that only equals the control in a scenario, for example where both sit at the metric's ceiling, is not disqualified by that scenario.
It still has to beat the control on the mean over all cases.
With several canal configurations or seeds, a scenario is compared on its mean over that scenario's cases.
A scenario where either side is missing a case is never counted as "not worse".
Eligible designs are ranked by improvement over the control, then by the plan's tie-breakers.
When no design is eligible, `selected_candidate_id` is `null` and the explanation names the scenarios each design lost in.

## For the frontend

### Starting a study

Send a request shaped like `examples/requests/dev_with_needs.json`.
Call `horn-study capabilities` to learn which frequencies and measurement types the evaluator requires before building the form.
Call `horn-study validate` to pre-check a profile.
A rejected request returns every problem at once and saves nothing:

```json
{
  "accepted": false,
  "issues": [
    {
      "code": "hearing.required_frequency_missing",
      "field": "hearing_profile.measurements",
      "message": "Missing the right ear air conduction threshold at 2000 Hz. Enter it from your existing test results."
    }
  ]
}
```

Request fields that matter:

| Field | Meaning |
| --- | --- |
| `mode` | `personalized` uses the user's own results. `demo` uses a synthetic profile and must be chosen explicitly. |
| `evaluation_mode` | `development_fixture` or `real`. A request for `real` never falls back to the fixture. |
| `start` | The user action that authorizes this one study. `initiated_by` must be `user`. |
| `hearing_profile.measurements[]` | `ear`, `frequency_hz`, `threshold_db_hl` (dB HL), `measurement_type`, `status`. |
| `status` | `measured`, `no_response`, `missing`, or `unreadable`. A marker never carries a numeric threshold. |
| `demo_profile_id` | Name of a synthetic profile from the capabilities. Demo mode only. |
| `needs_profile` | Optional. Without it the study uses the named context `default_everyday_listening`. |
| `budget` | Caps on evaluation cases, parallel evaluations, research calls per agent, retries, plan revisions, and run time. |

Only target-ear measurements of a supported type are used.
Other-ear and unsupported-type values are kept under `retained_but_unused` and never substituted.

`budget.max_evaluation_cases` must fit the smallest study the evaluator accepts: the control and one design in each of its `minimum_scenarios`.
A smaller budget is rejected with the code `budget.below_required_coverage` before anything runs.

### Progress events

Each study appends to `events.jsonl`, one JSON object per line, in strict `sequence` order.
`horn-study run --json` prints the same objects to stdout as they happen.

```json
{
  "study_id": "dev_with_needs_001",
  "sequence": 9,
  "timestamp": "2026-11-14T10:08:25.112173Z",
  "phase": "RESEARCHING",
  "component": "hearing_research",
  "type": "research.finding_added",
  "summary": "A short user-facing sentence.",
  "finding_ids": ["hearing-F1"],
  "hypothesis_ids": [],
  "candidate_ids": [],
  "experiment_ids": [],
  "artifacts": [],
  "trace": {"run_id": "...", "project": "...", "tracing_enabled": true},
  "data": {"source_id": "S1", "source_url": "https://...", "source_title": "..."},
  "replay": false
}
```

Event types: `study.started`, `study.state_changed`, `research.agent_started`, `research.source_read`, `research.finding_added`, `research.agent_completed`, `research.agent_failed`, `hypothesis.created`, `plan.revision_requested`, `plan.frozen`, `experiment.started`, `experiment.retried`, `experiment.completed`, `experiment.failed`, `report.completed`, `study.completed`, `study.failed`, `study.cancelled`.

Events carry summaries and IDs, not model reasoning and not binary assets.

### Artifacts

Each study gets its own directory under `studies/<study_id>/` (override with `--studies-dir` or `HORN_STUDY_DIR`).
An existing study is never overwritten.

| File | Contents |
| --- | --- |
| `request.json` | The original request, its normalized form, the evaluator hearing input, and the study context |
| `capabilities.json` | The evaluator capability snapshot the plan was validated against |
| `research.json` | Branch outcomes, accepted findings, and the sources that were read (URL, title, hash, retrieval time) |
| `plan.json` | The frozen plan: hypotheses, candidates, every experiment spec, selection rule, needs coverage, `plan_hash` |
| `events.jsonl` | Ordered event history |
| `experiment_results.json` | One record per frozen spec: the evaluator's raw result, attempts, cache use, issues |
| `results.json` | The frontend-ready document: state, profile, evidence, plan, per-case results, report, selection |

In `results.json`:

- `selected_candidate_id` is a candidate ID, or `null` when no selection is justified. It is never an array index.
- `selected_candidate` is that candidate's record, with its geometry family and parameters.
- `experiments[]` lists every evaluation case with its `experiment_id`, `candidate_id`, scenario, outcome, metrics, and asset references.
- `report.candidates[]` has the per-candidate aggregates, eligibility, reasons, and rank.
- `report.candidates[].primary_metric_by_scenario[]` has one entry per scenario of the plan, in plan order, for the primary metric.
  Each entry has `scenario_id`, `mean` and `reference_mean` (the candidate's and the reference control's mean over that scenario's cases), `n_completed`, `n_planned`, `difference_from_reference`, and `standing`.
- `difference_from_reference` is signed so that positive means better than the control, whichever direction the metric runs.
  It is `null` unless both the candidate and the control completed every case in that scenario.
- `standing` is `better`, `within_tolerance`, `worse`, or `not_compared`.
  A design with any `worse` scenario is not eligible, and its `ineligibility_reasons` name the scenario and both numbers.
- `plan.selection_rule.scenario_tolerance` is the tolerance behind `standing`, in the primary metric's unit.
- `report.needs[]` sorts each user need into `addressed`, `evaluated_unsuccessfully`, or `untested`.
- `report.follow_up_proposals[]` are suggestions only.
- `result_label` and `fixture_notice` say whether the numbers are fixture output. Show them.

### Follow-ups and replay

```bash
uv run horn-study follow-up dev_with_needs_001 FU1 --study-id dev_refine_002          # print the new request
uv run horn-study follow-up dev_with_needs_001 FU1 --study-id dev_refine_002 --run    # start it
```

The new study has its own ID and directory and links back through `parent_study_id`.
The parent's files are read, not changed.
`horn-study replay <study_id>` re-emits recorded events with `"replay": true` and runs nothing.

## For the evaluator owner

The agents reach numerical code through two calls only:

```python
get_evaluator_capabilities() -> dict        # or EvaluatorCapabilities
evaluate_experiment(spec: dict) -> dict     # or ExperimentResult
```

Point the workflow at the real implementation with `HORN_STUDY_REAL_EVALUATOR=package.module:attribute`.
The attribute can be a module, an object, a class, or a zero-argument factory that provides both functions.
`tests/fake_real_evaluator.py` is a complete minimal example that takes and returns plain dicts.
The team's real evaluator is `horn_study.hornsim_evaluator`, described below.

Capabilities declare the geometry families and parameter bounds, baselines, required hearing frequencies and measurement types, scenarios, metrics with units and direction, canal configurations, the calibration convention, seed support, fidelity levels, output assets, and explicitly unsupported requirements.
See `EvaluatorCapabilities` in `src/horn_study/contracts.py`, or run `horn-study capabilities` for a filled-in example.
The planner can only propose what the capabilities declare.

Capabilities also say what every study must cover and how to spend its budget.
All four fields are optional:

| Field | Meaning | Default |
| --- | --- | --- |
| `required_scenario_tags` | A plan must include at least one scenario carrying each listed tag. Tags are the ones on `scenarios[].tags`. | none |
| `minimum_scenarios` | A plan must include at least this many scenarios. | 1 |
| `planning_notes` | Short sentences the coordinator reads before it plans, such as which of candidates and scenarios is the expensive one. | none |
| `metrics[].resolution` | The smallest difference in that metric that is meaningful, in the metric's unit. | 0 |

A draft that misses the coverage is sent back to the coordinator, with the scenarios it can add, before anything is frozen.
Capabilities whose coverage no plan could meet are rejected when they are read: a required tag that no scenario carries, or a minimum above the number of scenarios.
The primary metric's `resolution` becomes the per-scenario tolerance of the selection rule.
Set it to the metric's run-to-run noise, because a design may fall that far below the unaided control in a scenario and still be selected.

`evaluate_experiment` receives one spec: `experiment_id`, `candidate_id`, `candidate_kind`, `family_id` or `baseline_id`, `parameters`, `hearing_input` (the supplied target-ear measurements, unmodified), `scenario_id`, `canal_config_id`, `ear_mesh_ref`, `seed`, `fidelity`, `calibration_ref`, and `spec_hash`.

The result must echo `experiment_id`, `candidate_id`, and `spec_hash`, and report the same `evaluator_version` and `kind` as the capabilities.
Metrics use the declared names and units.
A result that does not match its spec is recorded as `invalid` and excluded from the comparison.
Extra fields in results and capabilities are preserved.

To request a retry of the identical spec, return `status: "failed"` with `error.transient: true`, or raise `horn_study.evaluator_adapter.TransientEvaluatorError`.
Any other failure is recorded once as a failed case.

The adapter does not normalize levels or rescale outputs.
The amplitude and calibration convention is defined by the evaluator and named by `calibration_ref`.

### The hornsim evaluator

`horn_study.hornsim_evaluator` connects `evaluation_mode: "real"` to the backend's `hornsim` pipeline (see `../backend/HORNSIM.md`).
It builds the 3D aid in the configured ear, models its insertion gain with the 1D acoustic model, applies that gain to the speech clips, and scores them with HASPI v2 using the supplied audiogram.

What the model says about this device, so results are read correctly:
A narrow throat feeding the ear canal is a low-pass filter, so the hornsim default (throat 1 mm^2) sits 10 to 25 dB below the open ear above 500 Hz and scores worse than no device.
Widening the throat is what brings 1 to 4 kHz back, and a wide bore is routed as a short funnel with no vent.
Even the widest buildable bore stays about 6 dB below the open ear at 2 to 4 kHz, because the shell fills the concha and removes its natural boost.
On the template ear with the example sloping loss, the widest bores score above the unaided control for soft speech, about level with it at 65 dB SPL, and below it at 80 dB SPL, where the listener hears the highs unaided and the device cuts them.
Expect the best designs to land near the unaided control, not far above it.

hornsim needs torch and pyclarity, which this environment does not install.
Every numerical step therefore runs in the backend's own interpreter through `bridges/hornsim_bridge.py`, one short process per step, with JSON on stdin and stdout.
The bridge calls hornsim's functions and adds no numerics of its own.

Set it up once:

```bash
git submodule update --init                    # from the repository root
cd backend
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
```

The photo pipeline and its weights are not needed.
If there is no ear mesh from a photo yet, write AudioEar's average ear as a stand-in:

```bash
echo '{"out": "data/template_ear/ear.ply", "height_mm": 62, "side": "right"}' \
  | PYTHONPATH=. .venv/bin/python ../agents/bridges/hornsim_bridge.py template-ear
```

That mesh is a template, not anyone's ear.
A provenance note is saved beside it and repeated in the capabilities and in every result.

Then set these in `agents/.env`:

| Variable | Meaning |
| --- | --- |
| `HORN_STUDY_REAL_EVALUATOR` | `horn_study.hornsim_evaluator` |
| `HORNSIM_BACKEND_DIR` | The repository's `backend/` directory. Required. |
| `HORNSIM_EAR_MESH` | The patient's ear mesh in mm, in AudioEar's 2,800-vertex topology (`ear.ply` from `earrecon`, or the template). Required. |
| `HORNSIM_WORK_DIR` | Where patient contexts and built aids are kept and reused. Required. |
| `HORNSIM_PYTHON` | The backend interpreter. Defaults to `<backend>/.venv/bin/python`. |
| `HORNSIM_EAR_HEIGHT_MM` | Optional. Rescales the mesh to this ear height. Unset means the mesh is used at its own size. |
| `HORNSIM_BRIDGE_TIMEOUT_SECONDS` | Optional. Time allowed per bridge step. Defaults to 1800. |

Relative paths are resolved from the directory the command runs in.
A missing or wrong value stops the run with exit code `3` and names every variable that needs attention.

Run a real study:

```bash
uv run horn-study capabilities --evaluation-mode real
uv run horn-study validate examples/requests/real_with_needs.json
uv run horn-study run examples/requests/real_with_needs.json
```

What it declares, all read from the installed backend each time a study starts:

- One geometry family, `spiral_exponential_horn`, with the parameters and bounds of `AidDesign` in `backend/app/main.py`: throat 0.3 to 31 mm^2, mouth 2 to 200 mm^2, vent 0 to 2.5 mm, wall 0.4 to 2 mm, path 20 to 300 mm, and tip clearance 0.2 to 1.5 mm.
  A vent of 0 means no vent, which a throat above about 3 mm^2 needs because there is no room for a vent beside it in the canal tip.
  The largest throat that passes the canal tip is `pi * (canal diameter / 2 - tip clearance - wall)^2`: 20.4 mm^2 at the defaults and 31 mm^2 with the smallest tip clearance and wall.
  The bounds are what some ear can hold, so a design can be in bounds and still not fit the configured ear.
- One baseline, `unaided`: a flat 0 dB response sent through the same clips, levels, and HASPI call as the designs.
- Scenarios for each clip type (clean speech, speech in babble) at each presentation level in `hornsim/defaults.yaml`.
  Every scenario is the mean over its clips: three clean sentences, or four sentences in babble.
  HASPI on a single two-second clip swings too much with level to rank designs, so per-clip values are kept for inspection only.
- One calibration, `hornsim-reference-at-65-db-spl-v2`: HASPI's clean reference always stands for 65 dB SPL and the presentation level scales only what the listener hears.
  Results made under the earlier `hornsim-reference-rms1-at-level-v1` convention are not comparable at 50 and 80 dB SPL.
- Metrics: `haspi_v2_mean`, `haspi_v2_worst_canal`, `haspi_v2_improvement_over_unaided`, four insertion gain band averages, and `bore_length_mm`.
- Required thresholds at 250, 500, 1000, 2000, 4000, and 6000 Hz, the six frequencies HASPI v2 uses.
  pyclarity would interpolate a missing one, so a request without all six is rejected instead.
  The placeholder audiogram in `defaults.yaml` is never used.
- No seeds.
  hornsim fixes HASPI's internal noise with one seed so that scores repeat.
- `evaluator_version` is `hornsim-<commit>`, the last commit that touched `backend/hornsim`.

What to expect when it runs:

- The patient context is built once per ear mesh and audiogram (about three minutes) and each design once per set of design numbers (about ten seconds), however many scenarios or threads ask for it.
  Both are kept in `HORNSIM_WORK_DIR` and reused by later studies.
- Scoring one scenario takes 20 to 40 seconds.
- A design that cannot be routed in the ear comes back as `status: "failed"` with `error.code: "geometry_does_not_fit"` and hornsim's reason, never as a score.
  The reasons are a throat too wide for the canal tip, no bore route that fits the concha, and a vent that cannot keep the minimum wall to the bore.
- hornsim itself now refuses a vent that would cut into the bore.
  The adapter still checks `vent_wall_to_bore_mm` in `design.json` and reports `error.code: "vent_intersects_bore"` if an older backend lets one through, because the acoustic model assumes separate channels.
- Results carry references to `design.json`, `aid.glb`, `aid_in_ear.glb`, `aid_print.stl`, `acoustics.json`, and `references.json`, plus hornsim's own per-clip scores and its unaided and ceiling references.
- The bridge process does not inherit model or tracing keys.

`tests/test_hornsim_evaluator.py` covers the adapter with the bridge stubbed.
Its last test runs the real pipeline and is skipped unless `HORNSIM_BACKEND_DIR`, `HORNSIM_EAR_MESH`, and `HORNSIM_WORK_DIR` are set.

### The development fixture

`evaluation_mode: "development_fixture"` uses a deterministic placeholder with the same contract.
It is not a simulation.
Its metrics are prefixed `fixture_`, every result carries `provenance.kind = "development_fixture"`, and reports are labeled "Development fixture output. Not simulation results."
It requires at least two scenarios in every study, one tagged `quiet` and one tagged `noise`, and declares a resolution of 0.01 for `fixture_audible_speech_fraction`.

## LangSmith tracing

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` (plus `LANGSMITH_PROJECT`, and `LANGSMITH_ENDPOINT` outside the US region).
Each study is one root trace named `study <study_id>`, with these children:

- `hearing_research`, `use_context_research`, `acoustic_design_research`: each agent run with its model calls and tool calls.
- `synthesize_evidence`, `plan_experiments` (the `study_coordinator` run), `validate_and_freeze_plan`.
- `evaluate_batch`: one `evaluate_experiment` run per attempt, tagged with `experiment_id`, `candidate_id`, `spec_hash`, `plan_hash`, `attempt`, and `evaluator_version`.
- `interpret_results`: the `results_interpreter` run.

The root run ID is in every event's `trace.run_id`.

Traces and model prompts include the supplied hearing thresholds and needs text.
Asset files are passed as references, never as content.

## Research sources

Search queries go to OpenAlex and Europe PMC.
Sources are fetched over HTTP, and PubMed records are read through NCBI E-utilities.
No key is required.
OpenAlex without a key shares a small daily allowance per network, so set `OPENALEX_API_KEY` at an event.
Investigators are told to keep user data out of queries.

Every source is classified, and the tier is saved on each source and finding in `research.json`:

| Tier | Examples | How it is treated |
| --- | --- | --- |
| `scholarly` | Anything a literature index returned, DOI links, PubMed Central, publisher and preprint sites | Accepted as evidence |
| `technical_documentation` | GitHub, PyPI, Read the Docs | At most one finding per investigator. It can establish what the software does, not acoustics or hearing. |
| `other` | General web pages | Counts toward the same one-finding limit |
| `tertiary` | Wikipedia and other encyclopedias, forums, blogs | Refused before a call is spent |

The report's `findings_by_source_tier` gives the counts.
Its limitations say so when findings rest on non-scholarly sources or on abstracts alone.

## Development

```bash
uv run pytest          # no network or keys needed
uv run ruff check .
uv run ruff format .
uv run pyright
```

Tests drive the real workflow with a scripted stand-in model and offline sources.

| Guarantee | Test |
| --- | --- |
| Missing or unusable results are rejected before anything runs | `test_intake.py`, `test_invalid_input_is_rejected_before_anything_is_saved_or_evaluated` |
| No silent demo data, other-ear data, or invented thresholds | `test_intake.py` |
| Three research branches overlap | `test_three_research_branches_overlap_and_return_identifiable_evidence` |
| Findings need a read source and a verbatim passage | `test_research.py` |
| Investigators and the interpreter cannot reach the evaluator | `test_investigators_hold_evidence_tools_only`, `test_the_interpreter_cannot_change_the_selection_or_run_anything` |
| Plans respect capabilities, controls, and budget | `test_planner.py` |
| Plans cover what the evaluator requires of every study | `test_a_plan_missing_a_required_kind_of_scenario_is_rejected_until_it_is_added`, `test_a_plan_without_required_coverage_is_sent_back_before_freezing` |
| The plan is frozen before any result, and only its cases run | `test_the_plan_is_frozen_before_any_result_and_only_its_cases_run` |
| Retries repeat the identical case and are bounded | `test_runner.py`, `test_transient_failures_retry_only_the_identical_case` |
| Failed cases cannot help a design win, and no winner is forced | `test_a_design_with_a_failed_case_cannot_win`, `test_no_winner_is_forced_when_every_design_fails` |
| A design that is worse than the control in any scenario cannot win | `test_a_design_that_loses_to_the_control_in_one_scenario_cannot_win`, `test_nothing_is_selected_when_every_design_loses_somewhere`, `test_reporting.py` |
| Reported numbers are the evaluator's numbers | `test_reported_numbers_are_the_evaluators_numbers`, `test_per_scenario_numbers_in_the_report_are_the_evaluators_numbers` |
| The real evaluator never fills in a threshold, builds each design once, and reports a misfit as a failure | `test_hornsim_evaluator.py` |
| No path from results back to planning or evaluation | `test_nothing_leads_from_results_back_to_planning_or_evaluation` |
| A follow-up runs nothing until requested, and keeps the parent record | `test_a_suggested_follow_up_causes_no_evaluation_until_requested`, `test_a_follow_up_is_a_new_study_and_the_parent_record_is_kept` |
| The trace shows branches, planning, evaluation attempts, and the report | `test_the_trace_exposes_branches_planning_evaluation_and_report` |

## Module map

| Module | Responsibility |
| --- | --- |
| `contracts.py` | Typed request, capability, finding, plan, result, report, and state models |
| `intake.py` | Input validation and normalization against evaluator capabilities |
| `sources.py` | Literature search, source reading, passage selection, quote verification |
| `research.py` | The three investigators, their tools, budget, and evidence ledger |
| `planner.py` | Coordinator prompt, plan validation, deterministic expansion, freezing |
| `evaluator_adapter.py` | Evaluator protocol, real-evaluator loader, labeled development fixture |
| `hornsim_evaluator.py` | The real evaluator: capabilities and results from the backend's hornsim pipeline |
| `bridges/hornsim_bridge.py` | Runs hornsim steps in the backend interpreter. Not part of the package. |
| `runner.py` | Bounded execution, identical retries, result checks, evaluation cache |
| `reporting.py` | Aggregation, selection rule, needs outcomes, interpretation, report |
| `workflow.py` | LangGraph wiring, state machine, artifacts, terminal handling |
| `events.py` | Event schema, ordered event bus, artifact store |
| `followup.py` | Building a user-requested follow-up study from a saved one |
| `llm.py` | Model selection from the environment |
| `cli.py` | Command line entry point |
