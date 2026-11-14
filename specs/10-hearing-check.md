# 10 · Hearing check and audio

Pipeline stage 12 · status: new · depends on: 04, 05, 07, 08

## Goal

Score the top 5 designs on all 96 scenes with the perception models, pick the winner, and produce audio a judge can listen to.

## Per design, per scene

```
x1 = same signal as the baseline (spec 05)
aided = x1 filtered by G_design(f, canal of this scene)   # insertion gain only, spec 04's rule
score aided vs healthy and vs unaided
```

| Metric | Used for |
|---|---|
| Aided SII − unaided SII | fast confirmation of the search |
| HASPI change, seeded | ranks the top 5; NOT a predicted patient score |
| Gap closed = (aided − unaided) / (healthy − unaided) | comparable across patients |
| Harm rate: % of scenes where aided < unaided | must be near 0 for the pick |
| % bands within ±5 dB of NAL-R | the number an audiologist recognizes |
| Model-predicted speech-in-noise threshold shift (SNR sweep to 50% SII or HASPI) | never called a QuickSIN score |
| HASQI | rejects tinny designs (threshold in config) |

**Pick rule** (code, not the agent): highest weighted gap closed, subject to harm rate ≤ threshold and HASQI ≥ threshold. Thresholds in config.

## Audio

For one showcase scene per condition, three WAVs:

- `healthy.wav`: the scene as a normal ear receives it
- `unaided.wav`: through pyclarity's MSBG hearing-loss simulator with the patient's audiogram
- `aided.wav`: the pick's insertion gain applied, then MSBG

A judge with normal hearing then hears what the patient hears.

## Outputs (`check/`)

- `check.json`: per design × scene, every metric above; per design, the summaries; the pick and the reason
- `audio/<scene>_{healthy,unaided,aided}.wav`
- `neurograms/<scene>_{healthy,unaided,aided}.png` for the showcase scenes

## Acceptance checks

- The pick's harm rate is reported, and C4 and C7 show where the horn does not help.
- Results repeat exactly with the same seeds.
- Run time measured (5 designs × 96 scenes of HASPI is the slow part).

## Out of scope

- Changing the target or designs (spec 11).

## Open decisions for the reviewer

- Harm-rate and HASQI thresholds.
- Whether HASPI runs on all 96 scenes or a stratified subset if it is too slow.
