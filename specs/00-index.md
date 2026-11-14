# Auris pipeline specs

Nov 14, 2026 · @marc · status: **draft for review, nothing here is approved to build**

The pipeline in `pipeline-handoff.md`, split into one spec per part so each can be reviewed and handed to a separate owner. Each spec states its inputs, outputs, interface, acceptance checks, what is out of scope, and the decisions still open for the reviewer.

## Specs

| # | Spec | Pipeline stages | Code | Status in repo | Depends on |
|---|---|---|---|---|---|
| 01a | [Hearing test](01a-hearing-test.md) | 0 | `frontend/lib/audiometry.ts`, `frontend/components/HearingTest.tsx`, contract in `agents/` | new | none |
| 01 | [Intake and ear from photo](01-intake-and-ear.md) | 1, 2 | `agents/.../intake.py`, `backend/earrecon/` | exists, extend | none |
| 02 | [Ear parameters (L0 fit model)](02-ear-params.md) | 3 | `backend/hornsim/ear_world.py` | extend | 01 |
| 03 | [Wave simulation and viewer](03-wave-sim.md) | 3b | `backend/hornsim/wavesim.py` | built, uncommitted | 01, 02 |
| 04 | [Hearing model: the two ears](04-hearing-model.md) | 4 | `backend/hornsim/scoring.py` | extend | 01 |
| 05 | [Scenes and baseline runs](05-scenes-and-baseline.md) | 5, 6, 7 | `backend/hornsim/context.py`, `runner.py` | partly exists | 03, 04 |
| 06 | [Target and triage (L3)](06-target-and-triage.md) | 8 | `backend/hornsim/target.py` | new | 02, 05, 07 |
| 07 | [Acoustic model (L1)](07-acoustic-model.md) | 9 | `backend/hornsim/acoustics.py` | new, **build first** | 02 |
| 08 | [Design search](08-design-search.md) | 10 | `backend/hornsim/design.py` | new | 02, 06, 07 |
| 09 | [Geometry build](09-geometry.md) | 11 | `backend/hornsim/aid.py` | extend | 02, 07, 08 |
| 10 | [Hearing check and audio](10-hearing-check.md) | 12 | `backend/hornsim/runner.py` | new | 04, 05, 07, 08 |
| 11 | [Agent loop](11-agent-loop.md) | 13 | `agents/src/horn_study/` | extend | 06, 08, 10 |
| 12 | [Manifest and frontend](12-manifest-and-frontend.md) | 14 + screen | `backend/hornsim/manifest.py`, `frontend/` | new | contract only; fake data first |
| 13 | [Bench check](13-bench-check.md) | 15 | hardware | optional | 09 |

## Build order

1. **07 Acoustic model** with the open ear. Its go/no-go result can change the pitch, so nothing else is worth finishing before it.
2. **02 Ear parameters** and the coin scale in **01**.
3. **03 Wave simulation**: sphere test, then the open ear at 0°, 90°, 270°.
4. **04 Hearing model**, including the level calibration check.
5. **05 Scenes and baseline**.
6. **12 Manifest v2 frozen**; frontend built against a hand-written copy (can start in parallel from day one).
7. **06 Target and triage**, then **08 Design search**, then **09 Geometry**.
8. **10 Hearing check and audio**.
9. **11 Agent loop**.
10. **13 Bench check** and a recorded fallback of the demo.

Specs 07, 12, 04 and 01a have no dependency on each other and can start in parallel. 01a must land before any real patient runs: without it, a patient with no clinic audiogram cannot enter the pipeline.

## Shared conventions (every spec follows these)

**Coordinate frame.** AudioEar canonical frame, millimetres: +x lateral (out of the head), +y up, **-z forward for a right ear**. `earrecon` mirrors z for a left ear, so forward is +z there. Verified on the average ear: helix-root landmark 0 sits at z ≈ -10 and the lobe attachment at z ≈ -17, both anterior.

**Units.** Lengths in mm, areas in mm², volumes in cc, frequency in Hz, levels in dB SPL, hearing thresholds in dB HL, gains in dB.

**Band grid.** All per-band quantities (deficit, target T(f), insertion gain summaries, SII) use the 18 one-third-octave SII bands, 160 Hz–8 kHz. Full-resolution curves may be stored alongside.

**Angles.** Azimuth 0° = in front, 90° = straight out from the aided ear, 180° = behind, 270° = far side. Elevation positive upward.

**Patient folder.** Everything for one patient lives under `DATA_DIR/patients/<id>/`:

```
hearing.json          01a  HearingProfile (clinic results or in-app self-test)
request.json          01
ear/                  01   ear.ply, ear.glb, photo, mask
context/              02, 04, 05   context.json (incl. ear_params), ear_world.npz, canals.json, speech/
waves/                03   per-direction frames, impulse responses, viewer
scenes/               05   scenes.json, baseline.json, neurograms/
target/               06   target.json
design/               08   candidates.json, tradeoff.json
aid/<design_id>/      09   aid.glb, aid_in_ear.glb, aid_print.stl, design.json
check/                10   check.json, audio/, neurograms/
agent/                11   rounds.json
results/              12   results.json + every asset the frontend loads
```

**Determinism.** Every random draw takes a seed from config. HASPI is reseeded before every call (`scoring.haspi` already does this).

**Who decides numbers.** Code computes every score, the ranking and the pick. Models (the agent) may only explain results and propose changes to inputs, as `agents/` already enforces.

**Claims discipline.** Every spec's outputs are predictions from simulation. Nothing is presented as measured on a real ear except spec 13's bench numbers.

## Corrections every owner should know

- Do not quote the patent's "up to 13.4 dB": it is the lossless area-ratio limit for a 186.8 mm horn feeding a microphone.
- Benefit is ALWAYS gain over the patient's open ear, never the horn's own transfer gain.
- Target population is mild, high-frequency sloping loss, not mild-to-moderate.
- No feedback term: a passive device cannot feed back.

Sources: `reports/Passive horn hearing aid testing.md`.
