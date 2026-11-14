# 02 · Ear parameters (L0 fit model)

Pipeline stage 3 · status: extend · depends on: 01

## Goal

Turn the patient's mesh into a small set of numbers every later model uses, including hard bounds on the design, so that every candidate the search produces physically fits this ear.

## What exists

`backend/hornsim/ear_world.py` already computes from the mesh and AudioEar landmarks 35–49 (concha rim):

- shell-space voxels (where a device can go), rim plane and its outward normal
- `bowl_volume_cc`, `shell_volume_cc`, `opening_area_mm2`, `max_depth_mm`
- an **assumed** canal opening: the deepest point of the bowl, pointing inward along the rim normal, 7.5 mm diameter

`backend/hornsim/aid.py` searches spirals for the longest coiled bore that fits.

## Changes

1. Run `aid.py`'s spiral search **once** per ear (not per design) and record the longest coil, the largest mouth area the faceplate fits, and the room left for a vent. Factor the search so it can run without building the full aid.
2. Save one `ear_params` dict in `context/context.json`:

```
ear_params = {
  concha_depth_mm, opening_area_mm2, bowl_volume_cc, shell_volume_cc,
  canal_point_mm: [x, y, z], canal_axis: [x, y, z], canal_diameter_mm: 7.5,   # assumed
  max_coil_mm, max_mouth_mm2, vent_room_mm,
  x_head_mm                                                                   # head plane, see spec 03
}
```

3. Expose `design_bounds(ear_params) -> dict` giving min/max for every design variable in spec 08.

## Interface

```python
ear_world.ear_params(world, mesh, aid_defaults) -> dict
ear_world.design_bounds(ear_params) -> {"throat_mm2": (lo, hi), "mouth_mm2": (lo, hi), "length_mm": (lo, hi), ...}
```

## Acceptance checks

- `context.json` contains `ear_params` for the average ear and for one real reconstruction.
- A design at every corner of `design_bounds` builds in `aid.py` without a wall or clearance failure.
- Runtime stays near today's ~1 minute context build.

## Known issue to decide on

The assumed canal opening is the deepest point of the bowl along the rim normal. On the average ear this lands in the **posterior** part of the concha (z ≈ +2) and the axis points medially and slightly **posterior**. The real canal opens behind the tragus, in the **anterior** concha, and runs medially and **anterior**. Options:

1. Keep it (consistent with today's code; simple).
2. Place the opening near landmarks 36–39 (anterior concha, intertragic notch) and tilt the axis anterior. Better anatomy; needs a rule and a check.

This affects specs 03, 07 and 09 equally, so decide once here.

## Out of scope

- Any acoustics. This spec is geometry only.
