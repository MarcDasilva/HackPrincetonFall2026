# hornsim

Patient-specific passive in-ear horn: everything up to the design search, plus a 3D aid builder.
The server calls these as functions; they also run from the command line (from `backend/`):

```bash
.venv/bin/python -m hornsim.context data/cli/patient_a/context hornsim/defaults.yaml   # ~1 min
.venv/bin/python -m hornsim.aid data/cli/patient_a                                     # ~1 min
```

Defaults live in `hornsim/defaults.yaml` (ear mesh path, ear height, audiogram). **The default
audiogram is a placeholder** (the handoff doc's example) until a real hearing test is supplied.

## hornsim.context → `<patient>/context/`

| File | What |
|---|---|
| `ear_world.npz` / `.glb` | Shell space inside the concha (voxels), rim, assumed canal opening |
| `canals.json` | 32 sampled residual canals (0.5–0.9 cc, Latin hypercube) |
| `speech/` | Harvard sentences (IEEE 1969) via macOS `say` (cached in `assets/speech/`); one clip in 6-talker babble at +5 dB SNR |
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
