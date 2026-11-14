# 06 · Target and triage (L3)

Pipeline stage 8 · status: new · depends on: 02, 05, 07

## Goal

Turn 96 baseline deficits into one target gain curve T(f) for the design search, and decide up front whether a passive device can help this patient at all.

## Approach

1. **Target.** For each band: weighted mean of the importance-weighted deficit across scenes (weights from spec 05), capped at NAL-R gain for that band (spec 04). Bands with no meaningful deficit get target 0 dB, not negative.
2. **Reach.** Using spec 07 and spec 02's bounds, compute the best net gain over the open ear any design in bounds can reach in each band (a quick sweep on the formula-sized designs from spec 08 step A is enough).
3. **Feasibility ratio** per band = target ÷ reach.
4. **Triage verdict**:
   - `passive-suitable`: ratio ≤ 1 in the bands holding most of the weighted deficit
   - `partial`: some of those bands reachable, others not
   - `powered aid recommended`: none reachable; the run stops here
5. **Ear choice** for `side: auto`: run 1–4 per ear and pick the better verdict.

The thresholds that separate the three verdicts are a decision for the reviewer; record them in config, not code.

## Interface

```python
target.build(baseline, scenes, ag, ear_params, reach_fn) -> {
  "freqs_hz": [...18], "gain_db": [...18], "reach_db": [...18], "ratio": [...18],
  "triage": "passive-suitable" | "partial" | "powered aid recommended", "side": "left" | "right"
}
```

## Outputs

`target/target.json` (the dict above).

## Acceptance checks

- The placeholder audiogram gives a verdict and a target concentrated above 1.5 kHz.
- A flat 10 dB HL audiogram gives a near-zero target.
- A 60 dB HL flat audiogram gives `powered aid recommended`.
- A "powered aid" verdict stops the pipeline and is shown as a result, not an error.

## Out of scope

- Any design search.

## Open decisions for the reviewer

- Verdict thresholds.
- Whether to cap at NAL-R or at half-gain.
