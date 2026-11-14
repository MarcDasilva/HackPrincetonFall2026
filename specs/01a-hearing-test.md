# 01a · Hearing test

Pipeline stage 0 · status: new · depends on: nothing (frontend can start day one)

## Goal

Every patient enters the pipeline with an audiogram. If they already have one from a clinic, they enter it. If not, they take a hearing test in the app. Both paths produce the same `HearingProfile`, so everything from spec 01 onward is unchanged.

## Why this changes the current scope

Today the pipeline refuses to start without an existing test, on purpose:

- `agents/README.md`: "The product starts after hearing testing. Nothing here conducts a hearing test."
- `agents/src/horn_study/intake.py:114` rejects personalized mode with "needs results from an existing hearing test".
- `specs/01-intake-and-ear.md` lists "Conducting a hearing test" as out of scope.
- `backend/app/main.py` `POST /api/patients` silently falls back to the example audiogram when the field is blank.

This spec moves that line. The app now **screens** hearing; it still does **not diagnose**. All four places change (see [Changes to existing code](#changes-to-existing-code)).

## The two paths

| Path | Who | What happens | `source` |
|---|---|---|---|
| A. Enter results | Has a clinic audiogram | Types thresholds per ear and frequency, or uploads the report | `user_entered_test_results` / `uploaded_test_report` (exist) |
| B. Take the test | Has none, or it is over a year old | In-app pure-tone test, ~5 minutes | `in_app_self_test` (new) |

The patient chooses on the first screen. Path A is shown first when they say they have a report.

## Where it lives in the app

The dashboard's **Ear profile** dock icon (the audiogram glyph) opens the hearing panel. It follows the Capture Ear pattern: a panel opens above the chat card, and when finished the result becomes a chat attachment chip (a small audiogram thumbnail). Ear photo + audiogram attached = everything intake needs.

## Path B: the test

### 1. Safety questions (before any sound)

Asked first, and a "yes" stops the test with a referral message instead of results:

- Sudden hearing loss or a sudden change in the last 30 days
- Ear pain, discharge or bleeding
- Ringing or loss in ONE ear only
- Dizziness or vertigo with the hearing change

Sudden loss gets an URGENT message ("see a doctor within 72 hours"). These are the standard red flags for a medical referral. NEVER skip them to save time.

### 2. Setup

- **Headphones required.** Wired or Bluetooth over-ear/in-ear; no laptop speakers (both ears hear them, so per-ear results are meaningless).
- **Volume.** Patient sets device volume to the level stored in the calibration profile (e.g. 50%), then plays a reference tone and confirms it is clearly audible but not loud. The browser cannot read the OS volume, so this is an instruction, not a check.
- **Left/right check.** A tone in the left ear, then the right; the patient taps which side. Wrong answer → "your headphones may be on backwards".
- **Quiet room.** Optional: one-second microphone sample (with permission) and a warning above a loudness threshold. Uncalibrated, so it is a hint, not a gate.

### 3. Procedure

> **Built as a ~30 s screening (Nov 14):** 500, 1k, 2k, 4k Hz per ear, a 3-beep halving search over 0–60 dB HL in 10 dB steps, no 1 kHz retest, silent trials ~1 in 12 (`frontend/lib/audiometry.ts`). The full procedure below takes ~6 minutes and stays the reference if accuracy matters more than speed. 250 Hz is not tested, so spec 01's "at least 250 Hz" rule must accept a self-test without it.

Standard modified Hughson-Westlake (the clinical up-down method):

- **Order per ear:** 1000, 2000, 4000, 8000, 500, 250 Hz, then **1000 Hz again** as a reliability retest. Optional 3000 and 6000 Hz (the hornsim placeholder uses 6000; spec 05 bands run to 8 kHz).
- **Start** at 40 dB HL (familiarisation; if not heard, raise in 20 dB steps until heard).
- **Down 10** after each response, **up 5** after each miss.
- **Threshold** = the lowest level heard on 2 of 3 ascending presentations.
- **Stimulus:** three 200 ms pulses (20 ms on/off ramps, no clicks), random 1.5–3.5 s gap before each presentation so the patient cannot learn the rhythm.
- **Response:** "I heard it" button or Space, within 1.5 s of the stimulus end.
- **Catch trials:** ~1 in 8 presentations is silent. A press during one is a false alarm.
- **Ceiling:** the loudest level the calibration allows (depends on headphones, usually 70–80 dB HL). Not heard at the ceiling → `status: no_response`, `no_response_at_db_hl: <ceiling>` (the contract already supports this).
- **Better ear first** if the patient says one ear is better; otherwise right first.

Expected time: 4–6 minutes for both ears.

### 4. Reliability flags

Computed by code, stored with the result, shown to the patient in plain words:

| Flag | Rule |
|---|---|
| `retest_mismatch` | 1000 Hz retest differs from the first by more than 10 dB |
| `false_alarms` | more than 20% of catch trials answered |
| `asymmetry` | left/right differ by 15 dB or more at two adjacent frequencies → referral message |
| `beyond_passive` | any threshold above 40 dB HL at 500–4000 Hz → "a powered hearing aid is likely a better fit; see an audiologist" (matches spec 06's `powered aid recommended`) |

`retest_mismatch` or `false_alarms` → offer a retake before continuing.

## Calibration

This is the hard part and the main open decision. Software turns "dB HL" into a digital level with a per-frequency table:

```
digital_level_dBFS(f, dB_HL) = dB_HL + REF_DBFS[profile][f]
```

`REF_DBFS[profile][f]` is the digital level that equals 0 dB HL at frequency f on one headphone model at the stated volume. Without a correct table, every threshold is shifted by an unknown amount (typically 10–20 dB).

Options, cheapest first:

1. **One reference headphone.** Pick one model (e.g. the team's own wired earbuds) and calibrate it once. Unknown headphones use that table and the result is flagged `calibration: assumed`.
2. **Listener calibration.** Tune the table so two or three team members with known-normal hearing (ideally with a recent clinic audiogram) land at 0 ± 5 dB HL. Cheap and good enough for a demo.
3. **Measured.** Sound level meter or artificial-ear coupler on the reference headphone. Most accurate; needs hardware.

Recommendation for the hackathon: 1 + 2. Keep the table in ONE config file with a version id, written into every result.

## Output

The existing `HearingProfile` contract (`agents/src/horn_study/contracts.py`), with:

- `source: "in_app_self_test"` (new value)
- `measurements`: one `HearingMeasurement` per ear and frequency (`measured` or `no_response`)
- `tested_on`: today
- new `self_test` block (fields under `extra="allow"` today; make them explicit):

```json
{
  "calibration_id": "ref-earbuds-v1",
  "calibration": "assumed | listener | measured",
  "device_label": "AirPods Pro",
  "volume_instruction": "50%",
  "duration_s": 312,
  "catch_trials": { "presented": 9, "false_alarms": 1 },
  "retest_1k_db": { "left": 5, "right": 0 },
  "flags": ["asymmetry"],
  "red_flags_answered": { "sudden": false, "pain": false, "one_sided": false, "dizzy": false }
}
```

The frontend also renders the standard chart (frequency across, dB HL down, O right ear, X left ear) for the attachment chip and the manifest.

## How the rest of the pipeline treats a self-test

- **Spec 04 / 05:** unchanged. They consume thresholds, whatever the source.
- **Spec 06 (target and triage):** a self-test carries wider uncertainty. Run triage on the thresholds **+10 dB** (worse case) as well as as-measured; if the verdicts differ, report the more cautious one and say why.
- **Spec 12 (manifest):** add `ear.audiogram_source` and `ear.self_test_flags`; the result screen labels a self-test "screening result, not a clinical audiogram".
- **Claims:** no output may describe a self-test result as a diagnosis or a degree of hearing loss in clinical terms.

## Changes to existing code

| File | Change |
|---|---|
| `agents/src/horn_study/contracts.py` | Add `"in_app_self_test"` to `HearingSource`; add the `self_test` model |
| `agents/src/horn_study/intake.py` | Accept the new source in personalized mode; update the missing-profile message to point at the in-app test |
| `agents/README.md` | Replace "starts after hearing testing" with the screening-not-diagnosis line |
| `backend/app/main.py` | `POST /api/patients` takes a `hearing_profile` JSON (both ears + source) instead of a single-ear dict; a blank field is rejected in normal use (example audiogram only behind an explicit `demo=true`) |
| `specs/01-intake-and-ear.md` | Remove "conducting a hearing test" from out of scope; point to this spec |
| `frontend/lib/audiometry.ts` (new) | Pure procedure: state machine, threshold rule, catch trials, flags. No audio, so it can be tested without a browser |
| `frontend/lib/calibration.ts` (new) | `REF_DBFS` tables, versioned |
| `frontend/components/HearingTest.tsx` (new) | Panel UI, Web Audio tone generator, safety questions, setup, chart |
| `frontend/app/dashboard/Dashboard.tsx` | Wire the Ear profile icon to the panel; attach the result to the chat |

## Acceptance checks

- **Procedure:** a simulated listener with known thresholds (including a sloping high-frequency loss) is recovered within 5 dB at every frequency, run through `audiometry.ts` with no audio.
- **Guessing:** a simulated listener who presses on every presentation is flagged `false_alarms` and offered a retake.
- **No response:** a listener who never responds at 8 kHz gets `no_response` with the ceiling level, never a number.
- **Red flags:** answering yes to sudden loss shows the urgent referral and produces no audiogram.
- **Tones:** generated tone is within 1 dB of the requested digital level and within 1% of the requested frequency (offline render via `OfflineAudioContext`).
- **Playwright:** run the test end to end with a scripted listener (test hook exposes the current level), see the chart and the attachment chip, screenshot.
- **Contract:** the output validates as `HearingProfile`, and intake accepts it in personalized mode.
- **Calibration:** a team member with a recent clinic audiogram tests on the reference headphones; differences recorded per frequency (target: within 10 dB).

## Out of scope

- Bone conduction and masking (needed to tell conductive from sensorineural loss, and to test a much worse ear properly). Asymmetry is flagged and referred instead.
- Speech-in-noise testing (QuickSIN-style). Useful later to set the C6/C7 weights in spec 05; see `research_notes/Passive horn hearing aid testing/test_metrics.md`.
- Reading an uploaded report automatically (path A upload stays manual entry for now).
- Any claim of clinical accuracy.

## Open decisions for the reviewer

- Reference headphone model, and which calibration option (1, 2 or 3).
- Whether a self-test may run personalized mode, or only a clearly labelled "screening" mode.
- Optional 3000/6000 Hz: adds about a minute.
- Microphone noise check: worth the extra permission prompt?
- The `beyond_passive` threshold (40 dB HL) should match spec 06's triage thresholds once those are set.

## Risks

- **Calibration error** shifts every threshold the same way, which shifts the target in spec 06. The +10 dB triage run limits the damage but does not remove it.
- **Bluetooth headphones** may apply their own processing (volume limits, noise cancellation, "hearing" features on some earbuds). Ask the patient to turn those off; flag the device label.
- **Regulatory framing.** Online hearing screeners exist widely, but wording matters: "screening", "not a diagnosis", referral on red flags.

## Effort

Roughly: procedure + tests ~0.5 day; panel UI + audio ~1 day; contract/intake/API ~0.5 day; calibration session ~1 hour with a reference headphone and one person with a known audiogram.
