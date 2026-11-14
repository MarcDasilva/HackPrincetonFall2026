# 07 · Acoustic model (L1)

Pipeline stage 9 · status: new, **build first** · depends on: 02

## Goal

Given a design, the patient's ear numbers, a canal sample and a direction, return the insertion gain: how much more (or less) sound reaches the eardrum with the earpiece than with the open ear. Fast enough (microseconds) to evaluate thousands of designs × 32 canals.

## Model

A chain of 2×2 transmission matrices, one per part. The open ear is built from the same blocks, so the loss of the ear's own natural resonance is counted automatically.

```
aided:  source × direction(θ) → mouth radiation load → coiled bore (flaring, lossy segments)
        → tip (insertion depth) → residual canal (sample u) → eardrum load         = P_aid
        + vent: series mass + resistance, from outside into the residual canal
open:   source × direction(θ) → concha (depth + opening area from ear_params)
        → open canal (same u) → eardrum load                                       = P_open

G(f) = P_aid / P_open
```

| Block | Model |
|---|---|
| Bore | stack of short conical segments following the flare profile; narrow-tube viscous and thermal losses (Keefe-style lossy wavenumber); length = coiled path length |
| Mouth | radiation impedance of a flanged opening (the faceplate) |
| Vent | lumped acoustic mass `ρL/A` plus resistance, as a side branch |
| Concha | short wide tube with ear_params' depth and opening area |
| Canal | uniform tube, length and volume from the canal sample |
| Eardrum | lumped load; the SAME load in both paths. Calibrate against published open-ear gain and record the constant |
| Direction | multiplies both paths equally, so it cancels in G except where the mouth sits away from the canal opening; from spec 03 when available |

## Interface

```python
acoustics.insertion_gain(x: dict, ear_params: dict, canal: dict, freqs_hz: np.ndarray, theta_deg=0) -> np.ndarray  # dB
acoustics.open_ear_gain(ear_params, canal, freqs_hz) -> np.ndarray   # dB at eardrum vs free field, for checks
```

`x` keys: `throat_mm2, mouth_mm2, length_mm, flare (control points), vent_count, vent_diameter_mm, vent_length_mm, tip_depth_mm, damper (position, resistance)`.

## Acceptance checks

1. A flared horn shows more high-frequency gain than a straight tube of the same length (handoff checkpoint 1).
2. The open-ear gain peaks in the 2.5–3 kHz region at a height within the published 10–20 dB range.
3. With `vent_diameter_mm` large, low-frequency G tends to 0 dB.
4. The exponential-horn cutoff matches `f_c = c·ln(S_mouth/S_throat) / (4π·L)` within the model's resolution (≈453 Hz for 1 mm² → 22.2 mm², 186.8 mm).
5. 1,000 designs × 32 canals × 200 frequencies runs in under a few seconds.

## Go / no-go (report this before anything else is built)

Best coil that fits the average ear, net gain over the open ear:

| Result | Then |
|---|---|
| +5 dB or more somewhere in 1.5–4 kHz | keep the pitch as written |
| 0 to +5 dB | lead with triage and avoiding harm |
| 0 dB or less everywhere | open-fit shell that leaves the concha uncovered, or a triage-only pitch |

`aid.py` already coils up to 130 mm, which puts the lowest boosted frequency near 660 Hz. The cost is loss in a ~1 mm tube that long; this model is what sizes it.

## Out of scope

- 3D effects inside the bore (bends). Spec 13's bench check is the calibration for those.
- Printing roughness (also spec 13).

## Open decisions for the reviewer

- Eardrum load model: a simple published lumped model, or a resistance tuned to match spec 03's calibrated result?
