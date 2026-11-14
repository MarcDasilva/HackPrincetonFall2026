# 11 · Agent loop

Pipeline stage 13 · status: extend · depends on: 06, 08, 10

## Goal

After a hearing check, read where the remaining gap is and why, adjust the inputs to the search, and rerun, at most three times. Explain each decision in one line for the screen.

## What exists

`agents/src/horn_study/` runs research → plan → evaluate → interpret, with code (not the model) validating plans, computing aggregates and choosing the selected candidate. That rule carries over unchanged.

## Reads

- remaining weighted gap per band for the pick (spec 10)
- harmed scenes and their conditions
- which constraint rejected most candidates (spec 08 and spec 09 reasons)
- the triage ratio per band (spec 06)

## May propose (validated by code before use)

- raise or lower one band's weight in T(f), within ±50% of its current value
- widen or tighten one design bound, within spec 02's physical limits
- stop with a triage verdict ("powered aid recommended", "partial")

## May NOT

- change any score, the ranking or the pick
- add scenes or change patient data

## Loop

```
round = 0
while round < 3:
    proposal = agent(read(check, design, target))
    if proposal.stop: break
    validate(proposal) or reject with reasons
    rerun spec 08 → 09 → 10 with the change
    round += 1
```

## Outputs (`agent/`)

`rounds.json`: per round, the proposal, the code's validation result, the before/after summary numbers, and a one-line explanation for the screen.

## Acceptance checks

- One round changes T(f) and the pick for a stated reason that matches the numbers.
- An invalid proposal is rejected by code and logged.
- The loop never exceeds 3 rounds.

## Out of scope

- Free-form chat with the user.

## Open decisions for the reviewer

- Model choice (the package defaults to a Claude Sonnet model via `HORN_STUDY_MODEL`).
- Whether the loop runs live in the demo or is precomputed.
