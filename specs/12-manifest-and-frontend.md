# 12 · Manifest and frontend

Pipeline stage 14 + the demo screen · status: new · depends on: contract only (build against fake data first)

## Goal

One file, `results.json`, that holds everything the demo shows, and a frontend that reads only that file. No backend at demo time, nothing to time out.

## Manifest v2

Written by `backend/hornsim/manifest.py` from specs 01–11. Keeps the v1 fields from `handoff.md`; adds the rest.

```json
{
  "version": 2,
  "patient": { "side": "right", "scale_source": "coin", "is_average_ear": false },
  "ear":      { "mesh": "ear.glb", "audiogram": [[250, 15]], "params": {}, "canal_band": {} },
  "waves":    { "ear": "waves/ear.json", "runs": "waves/runs.json", "viewer": "waves/index.html" },
  "scenes":   [ { "id": 12, "condition": "C6", "clip": "babble_1", "level_db": 65, "talker_deg": 0,
                  "noise": { "type": "babble", "deg": 0, "snr_db": 5 }, "canal": 3, "weight": 0.031,
                  "deficit_db": [], "sii": { "unaided": 0, "pick": 0 }, "haspi": { "unaided": 0, "pick": 0 },
                  "harm": false, "neurograms": { "healthy": "", "unaided": "", "aided": "" },
                  "audio": { "healthy": "", "unaided": "", "aided": "" } } ],
  "baseline_timeline": [ { "scene": 12, "t_ms": 0 } ],
  "target":   { "freqs_hz": [], "gain_db": [], "reach_db": [], "triage": "passive-suitable" },
  "designs":  [ { "id": 3, "params": {}, "mesh": "aid/3/aid_in_ear.glb",
                  "gain_curves": { "freqs_hz": [], "mean": [], "canals": [] },
                  "harm_rate": 0, "gap_closed": 0, "score": 0 } ],
  "tradeoff": { "cloud": [], "front": [] },
  "agent":    [ { "round": 1, "line": "" } ],
  "pick": 3,
  "card": {}
}
```

Empty values above show shape only. Freeze this before spec 05 finishes, and commit a hand-written `results.json` with fake but plausible values, clearly marked fake, for frontend work.

## Screen (in demo order)

| Beat | Panel | Reads |
|---|---|---|
| 1 | Photo → rotatable ear; speaker on, waves wrap the pinna into the canal | `ear.mesh`, `waves.*` |
| 2 | Launch: 96 tiles fill in real timing; click a tile for its two neurograms | `scenes`, `baseline_timeline` |
| 3 | Target curve lands on the audiogram over the open-ear curve | `target`, `ear.audiogram` |
| 4 | Candidate cloud, tradeoff front, the pick lights up; fan of 32 canal curves | `tradeoff`, `designs` |
| 5 | The horn snaps into the ear | `designs[pick].mesh` |
| 6 | Grid recolors improved / no change / worse; play healthy, unaided, aided | `scenes[*].harm`, `.audio` |
| 7 | Second patient: different ear, different earpiece | a second manifest |

Agent lines appear under beat 4–6 from `agent`.

## Prescription card

Fields (values from the run): triage · target band · net gain at peak and canal worst-case · bore (throat, mouth, length, turns, flare) · vent (count × diameter, boom at 250 Hz, low-frequency cost at 500 Hz) · print tolerance · personalized vs standard parameters · harm rate · gap closed.

## Frontend constraints

- Lives in `frontend/` (Next.js). The repo rule applies: **every UI change is verified with Playwright** (`verify-ui-playwright` skill, `npx playwright test` from `frontend/`, read the screenshot) before moving on.
- three.js for the ear, horn and waves (new dependency; pin an exact version).
- The wave viewer from spec 03 can be embedded or re-implemented as a React component reading the same files.
- If the live launch takes more than a few seconds, replay `baseline_timeline`.

## Acceptance checks

- Every panel renders from the fake manifest with no network.
- Swapping in a real manifest needs no code change.
- The average ear is labelled as such whenever `patient.is_average_ear` is true.
- Playwright screenshots exist for each beat.

## Open decisions for the reviewer

- Does the demo live inside the existing dashboard or on its own route?
