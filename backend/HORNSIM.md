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

## hornsim.acoustics → `<patient>/aid/acoustics.json`

One 1D transmission-matrix model of the aid, used by the scorer, the server, the agents and the design search.
It replaces the two models the team had: the profile model on `main` and the dial model on `marc-sim`.
It answers one question: how much louder or quieter is the eardrum with the aid than with the ear open (insertion gain, dB).

```bash
.venv/bin/python -m hornsim.acoustics data/cli/patient_a      # needs aid/design.json; writes aid/acoustics.json
.venv/bin/python -m pytest tests -q                            # or, from the repo root: pytest backend/tests
```

### Two front doors, one engine

| Door | Call | Design | Canal |
|---|---|---|---|
| Profile | `insertion_gain_db(design, canals, freqs)` → `[canals, F]` | `Design`: any bore area profile, vents, dampers, `concha_fill` | `Canal(volume_cc, diameter_mm)` |
| Dial | `insertion_gain(x, ear_params, canal, freqs_hz)` → `[..., F]` | dict of named dials shared with the earpiece builder | `{"length_mm": ...}` |

`Design.from_dials(x)` turns a dial design into a profile design, and `Canal.from_length(mm)` turns a canal length into a `Canal`.
The two doors agree within 0.1 dB on the same design.
In the dial door every value may be an array: designs, canals and frequencies broadcast together, frequency on the last axis.
The direction of the sound (`theta_deg`) cancels in insertion gain, because the aided and the open ear share the same source; it only changes `open_ear_gain`.

### Elements

- Vents: `vent_count` identical vents in parallel with the bore.
  A count, a diameter or a length of zero means no vent.
- Dampers: series resistances in cgs acoustic ohms, as hearing-aid dampers are rated (680, 1500, 2200 ...).
  Dial door: `damper_pos` (0 throat to 1 mouth) and `damper_ohm`, or a `"dampers"` list of `(pos, ohm)` pairs.
  Profile door: `Design.dampers`, a list of `(s_mm from the mouth, ohm)`.
  Slice edges are moved so each damper sits exactly where it was asked for.
- Collector shapes: any area profile through `Design`, or any radius list through `horn()`.

### Settings

Every response function takes `settings=`.
Passing nothing uses `UNIFIED`.
A preset name (`"unified"`, `"legacy_main"`, `"legacy_marc_sim"`) works too.

| Field | Default | Other choices |
|---|---|---|
| `eardrum` | `"rcm"`: resistance + compliance + mass (`eardrum_r`, `eardrum_veq_cc`, `eardrum_m`) | `"resistance"` (`eardrum_rho_c` x ρc / canal area), or a function `freqs_hz -> impedance` |
| `concha` | `"auto"`: the patient's own concha when `ear_params` carries its geometry, else the average resonance bump | `"bump"`, `"tube"`, `"none"` |
| `radiation` | `"piston"`: exact flanged piston | `"low_ka"` |
| `wall_losses` | `"exact"`: Zwikker and Kosten circular tube | `"none"`, `"keefe"` (large-radius expansion, regression only) |
| `air` | 35 C (c 351.9 m/s, ρ 1.146 kg/m³, μ 1.88e-5 Pa s) | `Air.at(temp_c)`, or `settings.with_temperature(temp_c)` |
| `canal_diameter_mm` | `None`: from `Canal` or `ear_params` | a number overrides both |
| `canal_sample_tip_mm` | `None`: each door's own convention (below) | a number: whole canal = sample + that number, in both doors |
| `flare_slices` | `"cones"`: conical slices in the dial door's flare | `"cylinders"` |
| `slice_tol_db` | 0.05: worst-case slicing error the convergence rule allows | `slice_count` or `slice_step_mm` force a fixed slicing |

Canal convention.
Profile door: a `Canal` is the air beyond this design's tip, so the whole canal is residual + `tip_length_mm`.
Dial door: the whole canal is sample + `CANAL_SAMPLE_TIP_MM` (6 mm), and a deeper stem shortens the residual.
Set `canal_sample_tip_mm` to use the second reading in both doors.

Presets.

| Preset | What it is |
|---|---|
| `UNIFIED` | The default: `"rcm"` eardrum, exact wall losses, exact piston radiation, 35 C, slicing by the convergence rule. |
| `LEGACY_MAIN` | `main` before unification: low-ka radiation, bump concha, 0.25 mm stepped tubes. Matches the old numbers to 1e-5 dB. |
| `LEGACY_MARC_SIM` | `marc-sim`'s `acoustics.py`: 20 C, eardrum = 3 ρc / S, Keefe losses, concha tube, 40 stepped segments, 6 mm tip. Matches the old numbers to 1e-5 dB. |

### What changed against each old model

Profile door (was `main`): only the radiation formula and the slicing.
Nothing moves below 1 kHz.
The default coiled aid (22 mm² mouth) moves by at most 0.04 dB per band (0.18 dB at one frequency).
The 150 mm² funnel gains 0.24 dB at 4-8 kHz, and a 450 mm² collector gains 1.7 dB there.
Slicing accounts for less than 0.01 dB of that.

Dial door (was `marc-sim`): almost all of the change is the eardrum, which now has compliance and mass.
A narrow vented coil (1 → 22 mm²) gains 6 to 11 dB below 500 Hz and loses about 1 dB above 1 kHz.
A wide sealed earpiece (27 → 150 mm²) gains 1.7 dB at 1-2 kHz and changes by less than 0.7 dB in the other bands.
Warmer air moves every resonance up by 2.6 %.
Pass `settings=LEGACY_MARC_SIM` to compare against the wave simulation, which still assumes 20 C and a resistive eardrum.

### Bad input

These raise `ValueError` with the offending value: a stem or tip longer than the canal, a mouth smaller than the throat in the dial door, a negative length, a non-positive area or diameter, a negative or out-of-range damper, a non-positive frequency.

### Speed and accuracy

1000 designs x 32 canals x 200 frequencies take about 0.6 s in the dial door (the `main` model needed 94 s, the `marc-sim` model 2.2 s).
The profile door takes about 5 ms per design for 32 canals x 200 frequencies (was 94 ms).
The number of slices follows a rule calibrated against very fine slicing, with a worst case of `slice_tol_db`.
A design gets the same slicing alone or in a batch, and for any set of frequencies up to 8 kHz.
`tests/test_acoustics_unified.py` holds the known answers, and `tests/data/acoustics_golden.json` holds both old models' outputs (written by `tests/golden_acoustics.py`).

## Assumptions to know

- Canal opening position and diameter are assumed (AudioEar meshes stop at the visible ear).
- Gain and cutoff in `design.json` use simple horn formulas.
  The modelled insertion gain (wall losses, vents, dampers, canal and eardrum) comes from `hornsim.acoustics`, described above.
- The eardrum and the concha bump in the acoustic model are simplified averages, not measurements of the patient.
- HASPI uses NumPy's global RNG internally; `scoring.haspi` reseeds before every call.
- HASPI's clean reference always stands for 65 dB SPL (what its ear model expects); the presentation level only scales what the listener hears.
  Scores on one two-second clip still swing with level, so compare designs on the average over a condition's clips.
- The bore is the longest route that fits: a coiled spiral for narrow bores, a short uncoiled funnel for wide ones (`route` in `design.json`).
  A throat above ~3 mm² leaves no room for a vent in the canal tip; build it with `vent_diameter_mm: 0`.
  The throat can be at most π·(canal diameter / 2 − tip clearance − wall)²: 20.4 mm² with the defaults.
- In the acoustic model no bore inside a filled concha reaches the open ear at 2-4 kHz: the shell removes the concha's own boost and the added bore length moves the canal resonance down.
