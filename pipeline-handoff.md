# Auris Design Pipeline — Build Handoff

Nov 14, 2026 · @marc

One photo and one audiogram in. One printable earpiece out.

This doc specifies the full pipeline stage by stage: what goes in, what code runs, what file comes out, what the judge sees, and the check that proves it worked. Each stage is marked **exists**, **extend** or **new** against the repo as of today.

It builds on `handoff.md` and corrects it where research disagreed (see [Corrections to handoff.md](#corrections-to-handoffmd)). Sources for the research claims are in `reports/Passive horn hearing aid testing.md` and `research_notes/Passive horn hearing aid testing/`.

## Pitch

> A passive hearing device has a few dB to spend, and the wrong shape gives you less than your own ear. We simulate your ear to decide whether a passive device helps you at all, and if so, which one.

The demo centrepiece is 96 listening scenes, simulated in parallel on one person's ear.

## Corrections to handoff.md

| handoff.md says | Use instead | Why |
|---|---|---|
| "Up to 13.4 dB" (patent) | Do not quote it | It is the lossless area-ratio limit (10·log10 22.2) for a 186.8 mm horn feeding a microphone, not a measured in-ear result |
| ~15 dB of gain to spend | A few dB, up to about 10 dB, in roughly 1.5–4 kHz, **measured against the open ear** | The open ear already gives 10–20 dB of natural gain near 2.7–3 kHz, and a device in the concha removes part of it |
| Mild-to-moderate loss | Mild, high-frequency sloping loss | Moderate loss needs about 25 dB or more |
| Feedback term in the reward | Drop it | A passive device has no amplifier and cannot feed back, so the vent can be as large as the gain target allows |
| 100 experiments = 100 horn shapes | 96 scenes are the demo centrepiece; the horn search runs behind them | Scenes show the personalization; thousands of shapes run on the fast acoustic model |
| Neurogram distance as the main score | SII in the loop, HASPI on finalists, neurograms for display | The nerve model is too slow for the loop and is not a clinical standard |

## Variables

Every model is a function of four kinds of variable. Keeping them apart is what keeps each stage small.

| Kind | Symbol | Contents | Set by |
|---|---|---|---|
| Design | x | throat and mouth area, bore length, flare control points, vent count and diameter, tip insertion depth, damper position | the optimizer |
| Patient | p | audiogram, concha depth, opening area and volume, longest coil that fits, canal opening | measured, fixed during a search |
| Uncertain | u | residual canal volume (32 samples), eardrum load, seating depth | sampled |
| Scenario | s | clip, level, talker angle, noise and its angle, room echo | the 96 scenes, weighted by patient priorities |

```
choose x  to maximize   Σ_s w_s · outcome(x, p, u, s)  −  λ · CVaR_worst over u      subject to  x ∈ fits(p)
```

## Model layers

| Layer | Job | Input → output | Speed |
|---|---|---|---|
| L0 fit | What fits this ear | mesh → concha space → hard bounds on x | once per ear |
| L1 acoustics | What the horn does | x, p, u, angle → insertion gain over the open ear | microseconds |
| L2 perception | What the patient hears | gain + scene → SII (loop); HASPI, HASQI, neurograms (finalists) | ms to seconds |
| L3 target | What the patient needs | L2 with no device, healthy vs impaired → per-band deficit → target T(f) | once per patient |
| Wave view | How their pinna shapes the sound | mesh + speaker angle → animation + their ear's impulse response | offline, per patient |

## The pipeline

```
1 PATIENT          2 NEED                3 DESIGN               4 PROOF              5 OUTPUT
Intake        ─┐   Canal samples         L1 acoustic model      D Build geometry     Prescription card
Ear from photo │   96 scenes        ──▶  A Size from formulas   E Hearing check  ──▶ results.json
L0 fit model   ├─▶ Baseline runs         B Optimize on L1       Agent loop ─┐        aid_print.stl
Hearing model ─┘   L3 target + triage    C Robust over canals ◀─────────────┘        Bench check (optional)
Wave view ───────▶ (feeds scenes)                               reweight T(f), ≤ 3 rounds
```

The only loop is the agent sending the search back with a corrected target, at most three times.

### Phase 1 · The patient

#### 1. Intake — exists · `agents/src/horn_study/intake.py`

- **In:** ear photo with a coin beside the ear for scale; audiogram for both ears, 250 Hz–8 kHz in dB HL; up to 5 priority situations picked from the 8 scene conditions; which ear to fit, or "choose for me".
- **Runs:** validation of the hearing data. Code decides if it is usable, not a model.
- **Out:** `request.json`
- **On screen:** photo and audiogram side by side.
- **Check:** missing frequencies are rejected all at once. The placeholder audiogram in `backend/hornsim/defaults.yaml` is never used for a real patient.

#### 2. Ear from photo — extend · `backend/earrecon/reconstruct.py`

- **In:** photo, ear box, coin diameter.
- **Runs:** SAM 2 cuts the ear out; AudioEar returns a 2,800-vertex pinna mesh. **New:** measure ear height from the coin instead of the 62 mm default.
- **Out:** `ear.ply`, `ear.glb`
- **On screen:** the photo turns into a rotatable 3D ear.
- **Check:** scale comes from the coin. A wrong scale means the shell will not fit.

#### 3. L0 fit model and ear parameters — extend · `backend/hornsim/ear_world.py`

- **In:** scaled mesh, AudioEar landmarks 35–49 (concha rim).
- **Runs:** already computes shell-space voxels, concha depth, opening area, bowl volume and an assumed canal opening. **New:** run `aid.py`'s spiral search once to get the longest coil that fits, the largest mouth, and room for a vent.
- **Out:** `ear_world.npz`, `ear_params` in `context.json`
- **On screen:** translucent ear, orange shell space, blue canal marker, ghost of the longest coil.
- **Check:** bounds land in the design search, so no candidate can fail to fit. Context build takes about 1 minute today.

```
ear_params = { concha_depth_mm, opening_area_mm2, bowl_volume_cc, shell_volume_cc,
               canal_diameter_mm: 7.5 (assumed), max_coil_mm, max_mouth_mm2, vent_room_mm }
```

#### 3b. Wave view — new · `backend/hornsim/wavesim.py`

Turn a speaker on and watch the sound reach their canal. A 3D finite-difference time-domain (FDTD) simulation steps sound pressure forward in time on a grid built from their ear mesh. The wavefront travels to the ear, wraps around the pinna, pools in the concha and runs down the canal. One run gives both the animation and the numbers the scenes use.

**Waves, not rays.** Rays only work when the wavelength is much smaller than the object. Speech wavelengths are 343 mm at 1 kHz, 69 mm at 5 kHz and 34 mm at 10 kHz, against an ear about 62 mm tall, so sound bends around the ear instead of bouncing off it. The "trajectory" view uses particles carried along the computed sound intensity instead, which curve around the pinna and into the canal.

| Part | Choice |
|---|---|
| Method | 3D FDTD: pressure and particle velocity on a staggered grid |
| Code | torch, already installed for ear reconstruction; runs on the Mac GPU |
| Geometry | their ear mesh voxelized as a rigid solid; a flat baffle for the side of the head; a 7.5 mm × 25 mm canal closed at the eardrum (assumed) |
| Grid | 1 mm cells · 160 × 160 × 160 mm box = 4.1 M cells · time step 1.7 µs (stability limit) · about 1,200 steps for 2 ms |
| Edges | absorbing layer so waves leave instead of reflecting back |
| Source | a small speaker at each scene angle, driven by a click or tone burst |
| Recorded | pressure at the canal entrance and eardrum, giving their ear's impulse response per direction; slice and surface frames for the viewer |
| Into the scenes | stage 7 convolves each clip with that impulse response |
| Storage per direction | 128 × 128 slice × 150 frames as bytes ≈ 2.5 MB; ear surface 2,800 points × 150 frames ≈ 0.4 MB |
| Live or cached | run offline per patient; the viewer plays back cached frames |

**On screen:**

- speakers around the head at the scene angles; click one to turn it on
- a see-through slice through the canal axis, red for compression and blue for rarefaction
- pressure painted on the 3D ear surface
- energy-flow particles running into the canal
- the eardrum pressure trace and spectrum building up
- click or tone burst; toggle between the open ear and the ear with the shell

**Checks:**

- in open air, the pulse reaches a point at distance ÷ 343 m/s
- a rigid sphere matches the textbook scattering solution
- the closed canal resonates near c ÷ 4L, adjusted for the open end
- the open-ear response agrees with the 1D acoustic model where both apply
- time one direction before planning the rest

**Limits:**

- a 1 mm grid cannot resolve the roughly 1 mm horn throat; the view shows sound reaching the horn mouth and the bore interior stays in the 1D model
- the grid gets too coarse above about 10 kHz; speech and the device sit below that
- the head is a flat baffle, so only the pinna is theirs
- the mesh comes from one photo; fine ridges may be smoothed out

**Fallback:** a spherical-head filter for direction, if the wave simulation is not ready.

#### 4. Hearing model: the two ears — extend · `backend/hornsim/scoring.py`

- **In:** audiogram.
- **Runs:** healthy ear = 0 dB HL audiogram; impaired ear = theirs (exists, for HASPI). NAL-R target (exists). **New:** SII with the standard band-importance table. **New:** audiogram → `cohc`/`cihc` per frequency for the nerve model, porting the Bruce–Zilany fitting routine (about two-thirds of the loss on outer hair cells). Check whether `brucezilany` exposes it first.
- **Out:** two ear models for every later stage; NAL-R gain per band.
- **On screen:** audiogram with the NAL-R target over it.
- **Check:** a speech clip through both ears shows a gap that looks like the loss you put in.
- **Check (level calibration):** a 1 kHz tone near normal threshold barely registers in the healthy ear, and the same holds at the patient's threshold in the impaired ear. If either is off by more than a few dB, the level convention is wrong; confirm what pyclarity's HASPI input level refers to before trusting any absolute number.

### Phase 2 · What they need

#### 5. Canal samples — exists · `backend/hornsim/context.py`

- **Runs:** Latin hypercube, 32 samples of residual volume 0.5–0.9 cc, seed 0; length from volume ÷ area.
- **Out:** `canals.json`. The design search uses all 32; the scene grid uses 4, one per quartile.
- **On screen:** canal uncertainty band in the ear profile panel.

#### 6. Scene grid — new · `backend/hornsim/context.py · scenes()`

8 conditions × 3 clips × 4 canals = 96 scenes. Each condition maps to a situation people rate on standard hearing questionnaires (APHAB subscales, COSI situations), so the patient's priorities become the weights.

| # | Condition | Level | Talker | Noise | Why it is in the grid |
|---|---|---|---|---|---|
| C1 | Soft speech | 50 dB | 0° | none | where a passive horn helps most |
| C2 | Conversation | 65 dB | 0° | none | the design target |
| C3 | Talker on aided side | 65 dB | 90° | none | best case |
| C4 | Talker on far side | 65 dB | 270° | none | head shadow; the horn cannot fix it |
| C5 | Echoey room | 65 dB | 0° | reverb | reverberation subscale |
| C6 | Restaurant | 65 dB | 0° | babble 0°, +5 dB SNR | background-noise subscale |
| C7 | Noise on aided side | 65 dB | 0° | babble 90°, +5 dB SNR | the horn amplifies the noise; harm check |
| C8 | Loud speech | 80 dB | 0° | none | a passive horn cannot limit loud sound |

- **Out:** `scenes.json`: id, condition, clip, level, talker angle, noise, canal id, weight.
- **Check:** weights sum to 1 and come from the patient's priorities. Equal defaults (12.5% per condition) are a starting point, not evidence.

#### 7. Baseline runs: healthy vs impaired, no device — new · `backend/hornsim/runner.py`

This is the launch the judge watches. Each scene runs on its own worker in a process pool.

```
per scene s:
  x0  = clip at level L, + babble at SNR (from noise angle), + reverb if C5
  x1  = x0 ∗ HRIR_their_ear(θ)        # impulse response from the wave view, same for both ears
  healthy  = ear(audiogram = 0 dB HL)(x1)
  impaired = ear(their audiogram)(x1)
  deficit[s, band] = audibility gap, impaired vs healthy, × SII band importance
  record: SII, HASPI (seeded), neurogram pair for one showcase scene per condition
```

- **Out:** `baseline.json` (deficit per scene and band, unaided scores); PNG neurograms for 8 showcase scenes.
- **On screen:** the 96-tile grid (8 rows × 12 tiles) fills live. Each finished tile shows its deficit. Click a tile to see its two neurograms.
- **Check:** time a full run before demo day. If it is not done in a few seconds on stage, the frontend replays a cached run with its real timings.

#### 8. L3 target and triage — new · `backend/hornsim/target.py`

- **In:** deficits, scene weights, NAL-R, L0 bounds.
- **Runs:** T(f) = weighted importance deficit across scenes, capped at NAL-R. Feasibility ratio = needed gain ÷ what a horn within the L0 bounds can reach, per band.
- **Out:** `target.json`; triage verdict: passive-suitable, partial, or powered aid recommended.
- **On screen:** the target curve drawn over the patient's own open-ear curve.
- **Check:** a "powered aid" verdict stops the run and is shown as a result, not an error.

### Phase 3 · The design

#### 9. L1 acoustic model — new, build first · `backend/hornsim/acoustics.py`

A chain of 2×2 transmission matrices, one per part of the earpiece. The open ear is built from the same blocks, so losing the ear's own resonance is counted automatically.

```
aided:  source × their ear (wave sim, θ) → mouth radiation load → coiled bore (flaring, lossy segments)
        → tip (depth in x) → residual canal (sampled u) → eardrum            = P_aid
        + vent: mass + resistance branch from outside into the canal
open:   source × their ear (wave sim, θ) → their concha (from ear_params) → open canal (same u) → eardrum = P_open

insertion gain  G(f) = P_aid / P_open
```

Only G(f) goes into the hearing model. Passing P_aid directly counts the ear's natural boost twice, because dB HL is already relative to a normal ear.

- **Out:** `insertion_gain(x, ear_params, canal, θ) → G(f)`
- **Check (go/no-go):** a flared horn beats a straight tube at high frequencies, and the best coil that fits the default ear shows positive net gain over the open ear somewhere in 1.5–4 kHz.

| Net gain over open ear, best coil that fits | Then |
|---|---|
| +5 dB or more somewhere in 1.5–4 kHz | keep the pitch as written |
| 0 to +5 dB | lead with triage and avoiding harm |
| 0 dB or less everywhere | open-fit shell that leaves the concha uncovered, or a triage-only pitch |

The coiled bore matters here: `aid.py` already coils up to 130 mm, which puts the lowest boosted frequency near 660 Hz instead of 2–4 kHz for a straight concha-length horn. The cost is friction loss in a ~1 mm tube that long, which only this model can size.

#### 10. Design search: A size, B optimize, C robust — new · `backend/hornsim/design.py`

| Step | What it does | Model |
|---|---|---|
| A · Size | lowest frequency to boost → bore length: `f_c = c·ln(S_mouth/S_throat) / (4π·L)`; gain needed → area ratio, ceiling `10·log10(S_mouth/S_throat)` minus bore loss; boom budget → vent from `f_v ≈ 1 / (2π·√(M_vent·C_canal))`; place the gain beside the ear's natural peak, not on it | formulas |
| B · Optimize | CMA-ES from the A sizing, inside the L0 bounds; minimize importance-weighted error between G(f) and T(f), plus penalties for own-voice boom at 250 Hz, sharp peaks, and any band where G < 0 dB while the deficit is positive | L1 only |
| C · Robust | re-optimize over all 32 canals: mean error + worst-case average (CVaR); tip depth and vent size settle here | L1 × 32 |

Sanity check: the exponential-horn formula gives about 453 Hz for the patent's numbers, close to its quoted 459 Hz.

- **Out:** top 5 designs x; gain-vs-boom tradeoff curve; parameter sensitivities.
- **On screen:** candidate cloud (net gain vs own-voice boom) with the tradeoff curve lit; for the pick, a fan of 32 gain curves, one per canal.
- **Check:** a "restaurant" patient and a "TV at home" patient get different designs.

#### 11. D · Build geometry — extend · `backend/hornsim/aid.py`

- **In:** each top-5 x as `overrides`.
- **Runs:** coiled bore along a spiral, exponential flare, vent route, shell with tip, boolean cut. **Change:** bore length comes from x instead of "longest that fits", and the `est_*` formula values are replaced by L1 output.
- **Out:** `aid.glb`, `aid_in_ear.glb`, `aid_print.stl`, `design.json`
- **On screen:** the horn snaps into the 3D ear.
- **Check:** if a wall is too thin or the coil too tight, shrink that L0 bound and rerun from B. About 1 minute per design today.

### Phase 4 · The proof

#### 12. E · Hearing check — new · `backend/hornsim/runner.py · check()`

The same 96 scenes with each top-5 design's G(f) applied. Audio for the listening buttons runs through pyclarity's hearing-loss simulator (MSBG), so a judge with normal hearing hears what the patient hears.

| Metric | Used for |
|---|---|
| Aided SII − unaided SII | fast confirmation of the search |
| HASPI change, seeded | ranks the top 5; not a predicted patient score |
| Gap closed = (aided − unaided) / (healthy − unaided) | comparable across patients |
| Harm rate: % scenes worse than unaided | must be near 0 for the pick |
| % bands within ±5 dB of NAL-R | the number an audiologist recognizes |
| Predicted speech-in-noise threshold shift | called "model-predicted", never QuickSIN |
| HASQI | rejects tinny designs |

- **Out:** scores per design per scene; neurogram triplets (healthy, unaided, aided) for showcase scenes; three WAVs per showcase scene.
- **On screen:** the grid recolors: improved, no change, worse. C4 and C7 show where the horn cannot help.

#### 13. Agent loop — extend · `agents/src/horn_study/`

- **Reads:** remaining gap per band, the list of harmed scenes, which constraint rejected most candidates.
- **Decides:** raise a band's weight in T(f), widen or tighten a bound, or stop with a triage verdict. At most 3 rounds of B → E.
- **Cannot:** change a score or the selection. Code computes every number and the pick, as the agents package already enforces.
- **On screen:** a short log of its reasoning, one line per round.

### Phase 5 · The output

#### 14. Prescription card, manifest, print file — new · `backend/hornsim/manifest.py`

Prescription card fields (values filled by the run):

```
triage            passive-suitable | partial | powered aid recommended
target band       f_low – f_high Hz, from T(f)
net gain          dB at peak over open ear · canal worst-case dB
bore              throat mm² · mouth mm² · length mm · coil turns · flare
vent              count × diameter mm · boom at 250 Hz · low-frequency cost at 500 Hz
print tolerance   throat ± mm keeps gain within ± 1 dB
personalized      parameters with high sensitivity · standard: the rest
harm rate         n / 96 scenes · gap closed: weighted mean, worst-case
```

`results.json` v2 adds scenes, target, triage, card and wave-view assets, and keeps the v1 fields:

```json
{
  "ear":      { "mesh": "ear.glb", "audiogram": [], "params": {}, "canal_band": {} },
  "waves":    [ { "deg": 0, "slice": "waves/000_slice.bin", "surface": "waves/000_surface.bin",
                  "eardrum_trace": "waves/000_trace.json", "frames": 150 } ],
  "scenes":   [ { "id": 12, "condition": "C6", "clip": "babble_1", "level_db": 65, "talker_deg": 0,
                  "noise": { "type": "babble", "deg": 0, "snr_db": 5 }, "canal": 3, "weight": 0.031,
                  "deficit_db": [[500, 0], [1000, 0], [2000, 0], [4000, 0]],
                  "sii": { "unaided": 0, "pick": 0 }, "haspi": { "unaided": 0, "pick": 0 },
                  "harm": false, "neurograms": { "healthy": "", "unaided": "", "aided": "" } } ],
  "target":   { "freqs_hz": [], "gain_db": [], "triage": "passive-suitable" },
  "designs":  [ { "id": 3, "params": {}, "mesh": "horn_003.glb",
                  "gain_curves": { "mean": [], "canals": [] },
                  "harm_rate": 0, "gap_closed": 0, "score": 0 } ],
  "pick": 3,
  "card": {}
}
```

Zeros and empty arrays are placeholders for shape only.

#### 15. Bench check — optional

Print a canal tube about 7.5 mm wide and 25–30 mm long with a cheap lavalier or MEMS mic at the closed end (not a phone mic, which auto-adjusts its level). Record the same speaker in three conditions: open tube, tube with the printed horn, tube with a solid plug of the same shape. The differences are measured gain and blocking loss on this simulator. It is the only measured number in the project, and no published measurement of a passive in-ear device exists.

## Demo storyboard

1. **Photo becomes an ear** (stages 1–3). The ear rotates. Turn a speaker on: the wave wraps around their pinna and runs down the canal.
2. **Launch** (stage 7). 96 tiles fill. Click one: healthy and impaired neurograms side by side.
3. **The target appears** (stage 8). A curve lands on the audiogram: this is where the gain has to go.
4. **The search** (stage 10). Candidate cloud, the tradeoff curve, the pick lights up.
5. **The horn snaps in** (stage 11). The coiled bore appears inside their ear.
6. **Proof** (stage 12). The grid recolors. Play healthy, unaided, aided for one scene.
7. **Second patient.** Same pipeline, different ear and audiogram, different earpiece. That shows the personalization.

## Build order

Riskiest first; the screen is built early against a hand-written manifest.

| # | Build | Done when |
|---|---|---|
| 1 | `acoustics.py` with the open-ear chain | go/no-go answered |
| 2 | `ear_params` in `ear_world.py`; coin scale in `earrecon` | bounds saved in `context.json` |
| 2b | `wavesim.py`: sphere test, then their open ear at 0°, 90°, 270° | checks pass; frames and impulse responses cached; run time measured |
| 3 | scene grid, runner, SII, baseline deficit, level calibration check | 96 scenes finish; run time measured |
| 4 | freeze `results.json` v2; build the frontend against a hand-written copy | all panels read only the file |
| 5 | `target.py` + triage | the default audiogram gives a verdict |
| 6 | `design.py` A → B → C | two patient profiles give two designs |
| 7 | `aid.py` takes x; hearing check; audio through the loss simulator | harm rate and gap closed computed for the pick |
| 8 | agent loop on top | one round changes T(f) and the pick for a stated reason |
| 9 | neurogram port, bench check, recorded fallback | demo runs from the cached manifest with the network off |

Setup note: this checkout has no backend virtualenv, no `backend/data/example/` mesh, and an empty `backend/third_party/AudioEar` submodule. Run `git submodule update --init` and create the backend environment before starting 2b.

## Claims

**Say**

- We predict acoustic and neural performance for this ear; in-ear verification is still required.
- For mild loss that gets worse at high frequencies.
- Every benefit is measured against the patient's own open ear.
- The design holds up across 32 canals a photo cannot see.
- It tells some patients they need a powered aid.
- 96 simulations in parallel; thousands of shapes on the fast acoustic model.
- The simulation is built for choosing between designs, not for promising an exact result.

**Don't say**

- "Up to 13.4 dB".
- "Mild-to-moderate loss".
- "Clinically validated", or a QuickSIN score.
- "Helps in noisy restaurants": a linear horn amplifies the noise too.
- WHO's 430 million: it counts losses over 35 dB in the better ear.
- "Thousands of cochlea simulations": only finalists reach the nerve model.
- "Biocompatible device": resin certifications hold only for the validated printer, settings, wash and cure.

## Open assumptions

| Assumption | Status |
|---|---|
| Canal opening position and 7.5 mm diameter | assumed; AudioEar meshes stop at the visible ear; handled as a sampled range |
| One ear simulated | the far-side scene (C4) shows the limit; the other ear is not modeled |
| Direction filtering | from the wave simulation on their pinna with a flat baffle for the head; spherical-head filter as fallback |
| Scene weights | equal defaults until the patient's priorities replace them |
| Level calibration | unverified until the stage 4 tone check passes; affects absolute audibility, target and triage, not design ranking |
| Printed bore losses | layer roughness likely adds loss beyond the smooth-tube model; only the bench check can tell |
| Mesh-based insertion gain above 4 kHz | no published validation found |

## Regulation note

Under 21 CFR 800.30, a hearing aid is any wearable device offered to help impaired hearing, electronic or not. Marketing a passive horn for hearing loss most likely makes it a Class I, 510(k)-exempt air-conduction hearing aid (874.3300). The OTC output limits do not matter for a passive device; the OTC rule's 250 Hz–5 kHz bandwidth requirement could.
