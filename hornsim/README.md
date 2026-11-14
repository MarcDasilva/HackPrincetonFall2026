# hornsim

Patient-specific passive in-ear horn: everything up to the design search, plus a 3D aid builder.

## Steps

```bash
uv venv -p 3.12 .venv
uv pip install -p .venv pyclarity trimesh scipy numpy matplotlib pyyaml openpyxl pandas soundfile rtree scikit-image manifold3d

.venv/bin/python prepare.py      # patient context (~1 min)
.venv/bin/python build_aid.py    # 3D aid that fits the concha (~1 min)
```

Inputs are set in `config.yaml`: the ear mesh from `photo_to_ear` (default
`../repos/AudioEar/out/my_ear/ear.ply`), ear height, and audiogram. **The audiogram is a placeholder**
(the handoff doc's example) until a real hearing test is supplied.

## prepare.py → `out/<id>/context/`

| File | What |
|---|---|
| `ear_world.npz` / `.glb` | Shell space inside the concha (voxels), rim, assumed canal opening |
| `canals.json` | 32 sampled residual canals (0.5–0.9 cc, Latin hypercube) |
| `speech/` | Harvard sentences (IEEE 1969) via macOS `say`; one clip in 6-talker babble at +5 dB SNR |
| `references.json` | HASPI v2 (Kates & Arehart 2021, via pyclarity): healthy check, unaided floor, ceiling = best linear prescription (NAL-R, half-gain, full-gain) |
| `summary.png` | One-page overview |

## build_aid.py → `out/<id>/aid/`

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
