# 03 · Wave simulation and viewer

Pipeline stage 3b · status: built, uncommitted · depends on: 01, 02

## Goal

Place a speaker anywhere around the patient's ear, play a sound, and compute how the waves travel to the ear, wrap around their pinna, and enter the ear canal. The same run produces:

1. a **visual**: wavefronts and energy flow around their 3D ear, played back in a viewer;
2. **numbers**: their ear's transfer function for that direction, which every scene in spec 05 uses in place of a generic head filter;
3. **audio**: a speech clip as it arrives at their eardrum from that direction.

## Why waves and not rays

Rays only work when the wavelength is much smaller than the object. Speech wavelengths are 343 mm at 1 kHz, 69 mm at 5 kHz and 34 mm at 10 kHz, against an ear about 62 mm tall. Sound bends around the ear instead of bouncing off it. A ray view would show something physically wrong. The "trajectory" view uses particles that follow the computed sound intensity instead, which is accurate and still shows sound curving around the pinna into the canal.

## Method

3D finite-difference time-domain (FDTD), linear acoustics:

- pressure at cell centres, particle velocity on cell faces (staggered grid), leapfrog in time
- rigid walls: a velocity face is open ONLY between two air cells
- absorbing sponge on all six box faces
- time step at the 3D stability limit: `dt = 0.99 · dx / (c·√3)`
- torch, on the Mac GPU (MPS), CUDA or CPU

## Geometry (all mm, canonical frame from 00)

| Part | Rule |
|---|---|
| Pinna | The AudioEar mesh is the pinna surface as the camera sees it, so it is a height field along x. Cast rays along -x; everything medial of the first hit is solid. |
| Head | Outside the pinna's outline, a flat rigid plane at `x_head` (prototype: the canal opening's x). |
| Canal | A tube carved from the canal opening along the canal axis (from spec 02), 7.5 mm diameter, 25 mm long, closed at the eardrum. Diameter and length are assumptions. |
| Eardrum | The closed end of the canal. Needs a loss term (see Known issues). |

## Inputs

- `ear/ear.ply` (spec 01) and `ear_params` (spec 02)
- speaker directions: azimuth list, elevation list, distance from the canal opening (default 80 mm)
- signals: a click (always; gives the numbers and the pulse animation) and steady tones (default 2, 4 and 8 kHz)
- grid cell size (default 1 mm); speaker distance (default 120 mm, so wavefronts near the ear are close to flat)
- speech clip for the audio output (default `assets/speech/clean_1.wav`)

Each speaker position gets its own simulation box, which keeps every run small.

## Outputs (`waves/`)

| File | Content |
|---|---|
| `ear.json` | mesh, canal point/axis/size, head plane, forward direction, side, assumptions |
| `runs.json` | per position: speaker position, slice planes, transfer functions at the canal entrance and eardrum (dB vs Hz, relative to free field), eardrum peak, and per tone the streamlines and the canal-entrance level |
| `<tag>_<hz>_{h,v,surface}_{re,im}.png` | each tone's complex amplitude on the two slices and at the ear surface, relative to the incoming wave, 16-bit in R/G (no alpha: browsers premultiply it) |
| `<tag>_mask_{h,v}.png` | where each slice cuts tissue |
| `<tag>_pulse_{h,v,surface}.png` | click frames, 8-bit, relative to the click's free-field peak at the canal entrance |
| `free.wav`, `<tag>.wav` | the speech clip in open air, and as it reaches the eardrum from each position, at one shared level |
| `index.html` | the viewer |

## How it connects

- Spec 05 convolves each scene's clip with the eardrum response for the scene's direction. This replaces the spherical-head filter and keeps timing.
- Spec 07 uses the open-ear response as its baseline cross-check.
- Spec 12 embeds the viewer as the demo's first panel. Today the preview at `backend/preview/` embeds it as step 4.
- `app/jobs.py` runs it as the `waves` step after `context`; `POST /api/patients/{id}/waves` reruns it; `GET /api/patients/{id}/waves/{name}` serves it.

## Viewer (`backend/hornsim/wave_viewer.html`)

Styled as a figure, not a product screen: light background, labelled colour bar, 20 mm scale bar, axis arrows, timestamps.

- **3D wavefronts (default display):** the solver also stores each tone's complex amplitude and 60 click frames over the whole box at 2 mm (`<tag>_<hz>_vol_{re,im}.png`, `<tag>_pulse_vol.png`, z-slice tiles; mask in the blue channel). The viewer ray-marches them and draws lit surfaces of equal pressure (+level red; −level blue, off by default) or of equal sound level (louder orange, quieter purple). Rays stop at tissue, so the ear hides the field behind it. Cutaway applies to the field and the ear together.

- **Pressure:** a diverging red/blue scale (ColorBrewer RdBu), linear, ±2 × the incoming wave, with equal-pressure contour lines every 0.5. Tones animate one cycle from the stored complex amplitude, so wavelengths are real and countable.
- **Sound level:** viridis, −20 to +20 dB relative to the incoming wave, contour lines every 3 dB.
- **Energy flow:** streamlines of the time-averaged intensity on the horizontal slice, started around the speaker, with arrowheads.
- **Tissue:** grey where a slice cuts the ear or head. Top and Front presets cut the 3D ear at the slice.
- **Click:** the true transient, from emission to reflection and into the canal. No contour lines, because 8-bit frames would trace rounding noise.
- Side panel: transfer-function chart with the tones marked, canal-entrance levels, the two audio buttons, the model's assumptions.

## Acceptance checks

1. **Free-field arrival.** The click reaches the entrance at distance ÷ 343 m/s. An assert on every run; passes.
2. **Sphere.** A rigid sphere matches the textbook scattering solution within 1 dB up to 8 kHz. **Not run yet.**
3. **Baffle.** A flat rigid plane gives about +6 dB at its surface. **Passes:** +5.3 to +6.8 dB from 500 Hz to 11 kHz; about +4 dB below 300 Hz, as expected for a plate 11 cm wide.
4. **Low frequencies.** With the ear, the entrance transfer tends to the baffle value. **Passes:** +4.0 dB at 200 Hz, +6.0 dB at 500 Hz.
5. **Canal resonance.** **Passes after calibration:** average ear at 90°, 18.3 dB at 2.6 kHz with `EARDRUM_Z = 3.0`.
6. **Runtime.** Measured on the user's ear (patient `d60d88e7550d`): 13–23 s per position, click plus three tones, 88 s for five positions.

## Fixed during the build

- The absorbing sponge reflected long wavelengths, so the box rang like a closed room (+20 dB at 183 Hz). Replaced by impedance boundaries at the box faces, applied implicitly so corners stay stable.
- A rigid, lossless eardrum gave a 40 dB canal peak. The eardrum is now a resistive boundary with ONE calibration constant, `EARDRUM_Z`.
- The first viewer scaled brightness by distance from the speaker. Replaced by honest normalization to the incoming wave.

## Still open

- **Front (0°) peak is 21.6 dB**, slightly above the published 10–20 dB range. At 0° the speaker sits along the flat head wall, which likely exaggerates the boost; a real head shape would fix it.
- **Canal position** inherits the spec 02 issue (posterior concha, posterior axis).

## Limits to state in the demo

- A 1 mm grid cannot resolve the roughly 1 mm horn throat. The wave view shows sound reaching the horn's mouth; the bore interior is spec 07's 1D model.
- Above about 10 kHz a 1 mm grid loses accuracy. Speech and the device sit below that.
- The head is a flat plane; only the pinna is the patient's. The far side (270°) needs a head model and is out of scope.
- Behind the helix is filled solid (the mesh has no back surface).
- The mesh comes from one photo; fine ridges may be smoothed.

## Out of scope

- A full head model, both ears, real rooms.
- Live simulation in the browser. Runs are offline; the viewer plays back.

## Open decisions for the reviewer

- Grid size 1 mm vs 0.5 mm (8× cells, ~16× time, accurate to ~20 kHz).
- Directions to precompute for the demo (proposed: 0°, 45°, 90°, 135°, 180° at 0° elevation, plus 90° at +45°).
- Optional validation: run the solver on one of AudioEar's 112 ground-truth scans and on the photo reconstruction of the same ear, and report the difference. It would show how much photo error changes the sound.
