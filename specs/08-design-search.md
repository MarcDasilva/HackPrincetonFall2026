# 08 · Design search

Pipeline stage 10 · status: new · depends on: 02, 06, 07

## Goal

Find the five best earpiece designs for this patient: closest to the target, robust to the canal a photo cannot see, and never worse than the open ear where it matters.

## Steps

**A · Size from formulas (no search).**

| Requirement | Formula | Sets |
|---|---|---|
| Lowest band to boost, f_c | `f_c = c·ln(S_mouth/S_throat) / (4π·L)` | bore length |
| Peak gain needed | ceiling ≈ `10·log10(S_mouth/S_throat)` minus estimated bore loss | area ratio |
| Own-voice boom budget | `f_v ≈ 1 / (2π·√(M_vent·C_canal))` | vent diameter and length |
| Open ear's natural peak | `acoustics.open_ear_gain` | place the gain beside it, not on it |

**B · Optimize on the acoustic model.** CMA-ES (`pycma`) from the A sizing, inside spec 02's bounds. Minimize:

```
importance-weighted RMS(G − T) over bands
+ λ_boom · own-voice boom at 250 Hz
+ λ_peak · peak-to-mean ripple
+ λ_harm · Σ max(0, −G) over bands where the target is positive
```

**C · Robust over canals.** Re-optimize B's best few over all 32 canals: mean of B's objective + λ_cvar · average of the worst 20% of canals. Tip depth and vent size settle here.

All λ values live in config.

## Interface

```python
design.size(target, ear_params) -> x0
design.search(target, ear_params, canals, x0, seed) -> {"top": [x1..x5], "cloud": [...], "tradeoff": [...], "sensitivity": {...}}
```

## Outputs (`design/`)

- `candidates.json`: top 5 with parameters, objective breakdown, mean and per-canal gain curves
- `tradeoff.json`: every evaluated design's net gain at the target band vs own-voice boom (the candidate cloud) and the non-dominated front
- `sensitivity.json`: change in objective per unit change of each parameter at the pick; also gain change per ±0.05 mm of throat diameter (print tolerance)

## Acceptance checks

- Two patient profiles (a "restaurant" priority set and a "TV at home" set, same ear) produce different top designs.
- No top-5 design has negative G in a band carrying more than 10% of the weighted deficit.
- Same seed, same result.
- Whole search under a minute.

## Out of scope

- Building geometry (spec 09) and perceptual scoring (spec 10).

## Open decisions for the reviewer

- λ values and the CVaR fraction.
- Whether flare is free-form (3–4 control points) or exponential only for the demo.
