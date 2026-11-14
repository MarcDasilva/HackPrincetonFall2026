# 09 · Geometry build

Pipeline stage 11 · status: extend · depends on: 02, 07, 08

## Goal

Turn each top-5 design into a printable earpiece that fits this ear, and report back when a design cannot be built.

## What exists

`backend/hornsim/aid.py` `build(context_dir, out_dir, overrides)`:

- searches spiral radius, turns and height for the longest bore that fits
- exponential flare throat → mouth, riser to the faceplate, tip down the canal
- shell = smoothed shell space + canal tip; vent routed for the most wall to the bore
- writes `aid.glb`, `aid_in_ear.glb`, `aid_print.stl`, `design.json`
- `design.json` gain and cutoff use simple horn formulas (`est_*`)

## Changes

1. **Length from the design.** Take `length_mm` from x and find a spiral whose path length matches it (within 2 mm), instead of the longest that fits.
2. **Flare from the design.** Use x's flare profile instead of a fixed exponential.
3. **Real acoustic numbers.** Replace the `est_*` fields with spec 07's insertion gain (mean and worst-case over canals).
4. **Feedback, not silent failure.** If a wall is too thin, the coil too tight or the vent will not route, return a structured reason (`{"bound": "length_mm", "max_ok": 104.0}`) so spec 08 can shrink that bound and rerun.
5. Output into `aid/<design_id>/`.

## Acceptance checks

- Each of the top 5 builds, or returns a reason that spec 08 acts on.
- `aid_print.stl` is watertight for every built design.
- Bore length in `design.json` is within 2 mm of x's `length_mm`.
- About 1 minute per design (today's speed) is acceptable; only 5 designs are built.

## Out of scope

- Materials and printer settings. Note in the output that resin biocompatibility holds only for a validated printer, settings, wash and cure.

## Open decisions for the reviewer

- Minimum wall (today 0.6 mm) and minimum channel diameter for the printer you will actually use.
