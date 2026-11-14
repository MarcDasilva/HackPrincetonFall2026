# 05 · Scenes and baseline runs

Pipeline stages 5–7 · status: canal sampling exists, rest new · depends on: 03, 04

## Goal

Build 96 listening scenes from the patient's life, run each through a healthy and an impaired ear with no device, and measure the gap. This is the demo's launch moment: 96 tiles filling as scenes finish.

## Canal samples (exists)

`context.py` draws 32 residual canal volumes, 0.5–0.9 cc, Latin hypercube, seed 0, length = volume ÷ area. The scene grid uses 4 of them, one per quartile; the design search (spec 08) uses all 32.

## Scene grid (new)

8 conditions × 3 clips × 4 canals = **96 scenes**.

| # | Condition | Level | Talker | Noise | Why it is in the grid |
|---|---|---|---|---|---|
| C1 | Soft speech | 50 dB | 0° | none | where a passive horn helps most |
| C2 | Conversation | 65 dB | 0° | none | the design target |
| C3 | Talker on aided side | 65 dB | 90° | none | best case |
| C4 | Talker on far side | 65 dB | 270° | none | head shadow; the horn cannot fix it |
| C5 | Echoey room | 65 dB | 0° | reverb | reverberation subscale |
| C6 | Restaurant | 65 dB | 0° | babble 0°, +5 dB SNR | background-noise subscale |
| C7 | Noise on aided side | 65 dB | 0° | babble 90°, +5 dB SNR | the horn amplifies the noise; harm check |
| C8 | Loud speech | 80 dB | 0° | none | a passive horn cannot limit loud sound |

Conditions map to APHAB subscales and COSI situations, so the patient's priorities (spec 01) become weights.

**Weights.** Default equal (12.5% per condition). With priorities, ranked conditions get weights in proportion `5, 4, 3, 2, 1` for ranks 1–5, unranked conditions share a 10% floor. The reviewer should confirm this rule; it is a starting point, not evidence.

**Clips.** The 3 clean Harvard sentences and 1 babble mix in `assets/speech/` (macOS text-to-speech voices). C6 and C7 use the babble talker clip with babble noise.

**Reverb (C5).** Synthetic: exponentially decaying noise, RT60 0.6 s, seed fixed. Simple and labelled synthetic.

**Far side (C4).** Spec 03 cannot model the far side (flat head plane). Use a spherical-head filter for 270° and say so.

## Baseline run per scene (new, `hornsim/runner.py`)

```
x0  = clip at level L, + babble at SNR, + reverb if C5
x1  = x0 ∗ HRIR_their_ear(θ)          # spec 03 eardrum impulse response, as insertion gain context
healthy  = ear(0 dB HL)(x1)
impaired = ear(their audiogram)(x1)
deficit[s, band] = audibility gap, impaired vs healthy, × SII band importance
record: SII, HASPI (seeded); neurogram pair for ONE showcase scene per condition
```

Each scene runs on its own worker in a process pool, so tiles finish independently.

Note on x1: the direction filter is applied identically to both ears, so it changes audibility (how much speech reaches the ear) without being double counted (see spec 04's rule).

## Outputs (`scenes/`)

- `scenes.json`: `{id, condition, clip, level_db, talker_deg, noise: {type, deg, snr_db}, canal, weight}` ×96
- `baseline.json`: per scene, `deficit_db[18]`, `sii_unaided`, `haspi_unaided`, `haspi_healthy`
- `neurograms/<scene>_{healthy,impaired}.png` for 8 showcase scenes
- a progress stream (one line per finished scene) the frontend can follow live; spec 12 replays it if the live run is slow

## Acceptance checks

- 96 scenes finish; total time measured and recorded.
- Weights sum to 1.
- Deficit is largest at high frequencies for the placeholder audiogram, and larger in C1 than C2.
- C4's deficit exceeds C3's (head shadow).
- Re-running gives identical numbers.

## Out of scope

- Any device. This spec measures need only.

## Open decisions for the reviewer

- The weight rule above.
- Real recorded speech instead of text-to-speech voices.
- Whether 96 is the right count for the demo, or 8 × 12 tiles is fine as is.
