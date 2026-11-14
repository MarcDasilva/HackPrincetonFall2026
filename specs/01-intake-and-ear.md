# 01 · Intake and ear from photo

Pipeline stages 1–2 · status: exists, extend · depends on: 01a (the audiogram)

## Goal

Turn what the patient gives us (one ear photo, an audiogram, their priorities) into a validated request and a correctly scaled 3D pinna mesh.

## What exists

- `agents/src/horn_study/intake.py` validates hearing data and rejects every problem at once.
- `backend/earrecon/reconstruct.py`: SAM 2 cuts the ear out of the photo, AudioEar returns a 2,800-vertex pinna mesh in the canonical frame, scaled so the ear is `height_mm` tall (default 62).
- `backend/app/main.py` `POST /api/patients` takes `photo`, `box`, `side`, `ear_height_mm`, `audiogram`.
- Uncommitted: `reconstruct.mean_ear(out, height_mm)` writes the AudioEar model's average ear, for testing before a photo exists. It is NOT anyone's ear and must be labelled as such wherever it is shown.

## Changes

1. **Coin scale.** The photo includes a coin held beside the ear. Detect it (Hough circle or a SAM 2 box prompt on a second user-drawn box), measure its diameter in pixels, and compute `height_mm` from the ear mask's pixel height. Replace the 62 mm default.
2. **Both ears' audiograms.** Request carries `audiogram_db_hl.left` and `.right`, 250 Hz–8 kHz. Keep accepting a single ear.
3. **Priorities.** Up to 5 condition ids from spec 05's list (C1–C8), ranked.
4. **Ear choice.** `side: left | right | auto`. `auto` is resolved later by spec 06 (the ear with the better passive feasibility).

## Inputs

| Field | Type | Notes |
|---|---|---|
| `photo` | image | side view of the ear, coin in frame |
| `box` | `[x0, y0, x1, y1]` px | around the ear |
| `coin_box` | `[x0, y0, x1, y1]` px | optional; around the coin |
| `coin_diameter_mm` | float | default 24.26 (US quarter); user can change |
| `audiogram_db_hl` | `{left?: {Hz: dB}, right?: {Hz: dB}}` | at least 250, 500, 1k, 2k, 4k |
| `priorities` | `["C6", "C2", ...]` | up to 5, ranked |
| `side` | `left | right | auto` | |

## Outputs

- `request.json` (validated request, `ear_height_mm` filled in, `scale_source: coin | default`).
- `ear/ear.ply`, `ear.obj`, `ear.glb`, `mask.png`, `overlay.jpg`, `params.npz` (unchanged format).

## Acceptance checks

- A request missing required audiogram frequencies is rejected with every missing field listed.
- With a coin in frame, `ear_height_mm` comes from the coin and `scale_source` says so. Without one, the request still runs but `scale_source: default` is surfaced to the user.
- The placeholder audiogram in `backend/hornsim/defaults.yaml` is never used for a real patient (assert in `run_full`).
- Mirroring: a left-ear photo produces a mesh whose forward direction is +z (see conventions in 00).

## Out of scope

- Conducting the hearing test: see [01a](01a-hearing-test.md). Interpreting one clinically stays out of scope everywhere.
- Reconstructing the ear canal (impossible from a photo).

## Open decisions for the reviewer

- Coin detection method: automatic circle detection, or ask the user to draw a second box? The box is more reliable and cheaper to build.
- Is the US quarter the right default coin?

## Risks

- AudioEar's accuracy on real photos is unmeasured here. Its 112 ground-truth scans could be used to measure it (see spec 03, optional validation).
