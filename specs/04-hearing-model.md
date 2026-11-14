# 04 · Hearing model: the two ears

Pipeline stage 4 · status: extend · depends on: 01

## Goal

Give every later stage two listeners: a healthy ear and this patient's impaired ear, each able to score a sound (SII, HASPI, HASQI) and, for display, produce a neurogram.

## What exists

`backend/hornsim/scoring.py`:

- `audiogram()` builds a pyclarity `Audiogram`
- `haspi()` runs HASPI v2 and reseeds before every call
- `prescription_gain()` gives NAL-R, half-gain and full-gain targets
- `score_gain()` applies a gain curve and scores it

`context.py` already scores healthy, unaided and prescription ceilings at 50/65/80 dB.

## Changes

1. **SII** (ANSI S3.5): band levels of speech and noise, the patient's thresholds, the 18 one-third-octave band-importance values. Pure numpy, fast enough for the optimizer loop.
2. **HASQI** wrapper next to `haspi()`, same seeding.
3. **Nerve model inputs.** `audiogram -> (cohc, cihc)` per characteristic frequency for `brucezilany`. First check whether the package exposes the Bruce–Zilany fitting routine (`fitaudiogram2` in their MATLAB release); otherwise port it. Convention: about two-thirds of the threshold shift on outer hair cells.
4. **Neurogram** helper: clip + ear → PNG heatmap. Display only; never in the optimizer loop.
5. **Level calibration check** (below).

## Interface

```python
scoring.sii(speech, noise, fs, ag, level_db) -> float                  # 0..1
scoring.band_audibility(speech, noise, fs, ag, level_db) -> np.ndarray  # dB per band, 18 bands
scoring.haspi(ref, proc, fs, ag, level_db, seed) -> float              # exists
scoring.hasqi(ref, proc, fs, ag, level_db, seed) -> float
scoring.hair_cells(ag, cfs_hz) -> (cohc, cihc)
scoring.neurogram(x, fs, cohc, cihc, level_db, cfs_hz) -> np.ndarray   # (CF, time)
```

Healthy ear = 0 dB HL at every frequency.

## The rule that prevents double counting

Only the **insertion gain** (aided ÷ open ear, spec 07) is applied to a signal before scoring. Never apply the raw pressure at the eardrum: dB HL is already relative to a normal ear, which includes the ear's own natural boost.

## Level calibration check

Every audibility number depends on agreeing where "65 dB SPL" is measured (open air at the head, or at the eardrum). A mismatch shifts results by about the open ear's natural gain, 10–20 dB in the speech band.

1. A 1 kHz tone at a level near normal threshold barely registers in the healthy ear.
2. The same holds at the patient's threshold in the impaired ear.
3. Confirm in pyclarity's documentation what HASPI's `level1` refers to, and write it in `scoring.py`'s module docstring.

If either tone check is off by more than a few dB, the convention is wrong. Design ranking is unaffected by this (both sides shift equally); absolute audibility, the target and triage are not.

## Acceptance checks

- A speech clip through both ears shows a gap that looks like the loss you put in (handoff checkpoint 2).
- SII of clean speech at 65 dB for a 0 dB HL ear is near 1; for the placeholder audiogram it is lower, and lower still at 50 dB.
- The calibration check passes and its result is recorded.
- HASPI and HASQI return identical values on repeated calls with the same seed.

## Out of scope

- Nonlinear prescriptions (NAL-NL2): a passive horn has the same gain at every level.

## Open decisions for the reviewer

- Neurogram resolution for display: ~100 CFs, all three fiber types, as the handoff proposed, or fewer for speed?
