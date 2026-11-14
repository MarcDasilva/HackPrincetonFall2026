---
name: verify-ui-playwright
description: Use when changing anything a user sees or clicks in frontend/ — components, styles, layout, animations, pages, camera or chat behavior — and before saying the change works, moving to the next task, or committing.
---

# Verify UI changes with Playwright

NO UI CHANGE IS DONE UNTIL A PLAYWRIGHT RUN PASSED AND YOU LOOKED AT THE SCREENSHOT. Typecheck and "it compiles" prove nothing about what renders. Do not start the next task first.

## Loop

1. Add or update a spec in `frontend/e2e/` covering the changed behavior (new behavior = new test; fixed bug = test that fails without the fix).
2. Run from `frontend/`: `npx playwright test` (config starts `npm run dev` or reuses it).
3. Take `page.screenshot({ path: "test-results/<name>.png" })` at the end state, then Read the PNG. A green test with a wrong-looking screenshot is a failure.
4. Fix and re-run until green. Report the test result and what the screenshot showed.

## Traps in this repo

- `/dashboard` redirects to `/` without a Supabase session — test `/zz-preview`, which renders the same `Dashboard`.
- Headless Chromium has no webcam — `playwright.config.ts` passes `--use-fake-device-for-media-stream`; keep it for anything touching `getUserMedia`.
- `toBeVisible()` ignores opacity, and the chat/dock fade in via GSAP — wait for computed opacity `"1"` before screenshots or they are blank (see `e2e/capture.spec.ts`).
- Components mount after hydration (`ready` state) — wait for a real element, never assume first paint.
- Prefer role/alt-text/`data-testid` locators; a locator matching two elements (an `<img>` and an `<svg>` both have role img) throws in strict mode — narrow it.

## Red flags — stop, run the test

- "It's only CSS / a small tweak."
- "Typecheck passes, so it works."
- "I'll verify after the next change."
- "The dev server compiled without errors."

All mean: run Playwright now.

## Cannot run it?

Say so explicitly and why (server won't start, browsers missing). Never report the UI change as working.
