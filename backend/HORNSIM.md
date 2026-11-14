# hornsim

Patient-specific passive in-ear horn: everything up to the design search, plus a 3D aid builder.
The server calls these as functions; they also run from the command line (from `backend/`):

```bash
.venv/bin/python -m hornsim.context data/cli/patient_a/context hornsim/defaults.yaml   # ~1 min
.venv/bin/python -m hornsim.aid data/cli/patient_a                                     # ~10 s
```

Defaults live in `hornsim/defaults.yaml` (ear mesh path, ear height, audiogram). **The default
audiogram is a placeholder** (the handoff doc's example) until a real hearing test is supplied.

## hornsim.context → `<patient>/context/`

| File | What |
|---|---|
| `ear_world.npz` / `.glb` | Shell space inside the concha (voxels), rim, assumed canal opening |
| `canals.json` | 32 sampled residual canals (0.5–0.9 cc, Latin hypercube) |
| `speech/` | Harvard sentences (IEEE 1969) via macOS `say` (cached in `assets/speech/`); three clean clips and four in 6-talker babble at +5 dB SNR |
| `references.json` | HASPI v2 (Kates & Arehart 2021, via pyclarity): healthy check, unaided floor, ceiling = best linear prescription (NAL-R, half-gain, full-gain) |
| `summary.png` | One-page overview |

## hornsim.aid → `<patient>/aid/`

| File | What |
|---|---|
| `aid.glb` | Aid alone: translucent shell, bore (orange), vent (blue) |
| `aid_in_ear.glb` | Aid seated in the ear |
| `aid_print.stl` | Printable solid with bore and vent cut out |
| `design.json` | Parameters and fit checks (wall thickness, bore length, estimated cutoff/gain) |

## Assumptions to know

- Canal opening position and diameter are assumed (AudioEar meshes stop at the visible ear).
- Gain and cutoff in `design.json` use simple horn formulas; the acoustic model (insertion gain with
  narrow-tube losses, vents, canal and eardrum) is the next step.
- HASPI uses NumPy's global RNG internally; `scoring.haspi` reseeds before every call.
- HASPI's clean reference always stands for 65 dB SPL (what its ear model expects); the presentation level only scales what the listener hears.
  Scores on one two-second clip still swing with level, so compare designs on the average over a condition's clips.
- The bore is the longest route that fits: a coiled spiral for narrow bores, a short uncoiled funnel for wide ones (`route` in `design.json`).
  A throat above ~3 mm² leaves no room for a vent in the canal tip; build it with `vent_diameter_mm: 0`.
  The throat can be at most π·(canal diameter / 2 − tip clearance − wall)²: 20.4 mm² with the defaults.
- In the acoustic model no bore inside a filled concha reaches the open ear at 2-4 kHz: the shell removes the concha's own boost and the added bore length moves the canal resonance down.
