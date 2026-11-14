# 13 · Bench check (optional)

Pipeline stage 15 · status: optional · depends on: 09

## Goal

One measured number: how much the printed horn adds, and how much a plug of the same shape blocks, on a simple ear simulator. No published measurement of a passive in-ear device exists, so this is the project's strongest evidence.

## Setup

- Print a canal tube about 7.5 mm inner diameter and 25–30 mm long, closed at one end.
- Mount a small lavalier or MEMS microphone flush at the closed end. Not a phone mic: phones adjust their level automatically.
- Mount the tube in a flat plate (stands in for the head) with the opening flush.
- One speaker at a fixed distance and angle (match one of spec 03's directions, e.g. 90°, 80 mm).
- Play a sine sweep or a click, same level each time.

## Conditions

1. Open tube.
2. Printed horn (the pick from spec 09) seated in the tube.
3. Solid plug with the same outer shape as the horn.

## Results

- Horn − open = measured insertion gain on this simulator.
- Plug − open = blocking loss.
- Compare both with spec 07's prediction for the same canal length and with spec 03's open-tube result.

## What it cannot show

Absolute eardrum level, own-voice boom, speech benefit on a person.

## Acceptance checks

- Three recordings per condition, repeatable within 1 dB.
- Plot of measured vs predicted insertion gain.

## Open decisions for the reviewer

- Worth the print time this weekend, or after the demo?
