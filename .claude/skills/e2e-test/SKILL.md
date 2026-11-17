---
name: e2e-test
description: Run or extend the real-browser Playwright suite under web/e2e/ — the layer above `npm test`'s pure-math tests that actually drives the React app (HomeScreen, the canvas, Report) in a headless browser. Use when asked to verify a UI change end to end, add browser-level test coverage, or when `npm test`/`npm run build` pass but the actual feature hasn't been exercised in a real browser. Also load this before any one-off headless-Chromium verification of the app (screenshots, manual CDP/Playwright scripts) — it has the gotchas that make those reliable on the first try.
argument-hint: [run | add <flow to cover>]
allowed-tools: Read Edit Write Bash Grep Glob
---

# e2e-test — the real-browser layer (TODO #10)

`npm test` (`web/test/*.test.ts`, node:test) covers pure math — geometry, totals,
the lib functions. It proves nothing about the actual React app: AGENTS.md says
plainly the canvas is "verified by hand." This suite (`web/e2e/*.spec.ts`,
`@playwright/test`) is that hand-verification, checked in instead of
reinvented from scratch under `/tmp/` every time (which is what happened
across several prior sessions — see `docs/specs/unit-testing.md`).

## Running it

```bash
cd web
npx playwright install chromium   # once per machine — see "Browser binary" below
npm run test:e2e                  # headless, list reporter
npm run test:e2e:ui               # Playwright's interactive UI mode — best for authoring/debugging
npx playwright test e2e/onboarding.spec.ts   # a single file
npx playwright show-trace test-results/<test-name>/trace.zip   # inspect a failure after the fact
```

`playwright.config.ts` starts `npm run dev` itself (`webServer`, with
`reuseExistingServer`) — you don't need a dev server running first, though
keeping one open in another terminal makes repeated `test:e2e` runs faster
(no cold Vite boot per run) while you're iterating on a spec.

## Adding a spec

1. Skim the existing specs first — `onboarding.spec.ts` (fresh load → import →
   reload → resume → delete) and `condition-report.spec.ts` (create a
   condition without geometry → Report renders it) are the reference shape.
2. Reuse `e2e/helpers.ts` (`skipTour`, `dismissSignInGate`, `uploadOnHomeScreen`,
   `waitForCanvas`, `wordmark`, `demoPlanFile`) rather than re-deriving them —
   they exist because getting each one wrong once already cost a real
   debugging session.
3. Read the actual component before asserting on its text/attributes — this
   app has no `data-testid` convention, so a locator is either a real
   accessibility role/name, a `data-tip`/`data-tour` attribute already in the
   code for another reason, or a structural fact (element count, disabled
   state). Grep the component in `web/src` first; don't guess at button text.
4. Run it via `test:e2e:ui` and let a real failure correct your locator — that
   loop is faster and more reliable than reasoning about the DOM from source
   alone (ARIA roles and CSS text-transform both change what actually
   matches).

## The gotchas (each cost a real session before this file existed)

- **Two different hidden `input[type=file]`** — `HomeScreen.jsx` (start a
  brand-new project) and `SheetGallery.jsx` (add sheets to an open one).
  `uploadOnHomeScreen` covers the first; scope your own locator for the
  second.
- **The guided tour steals focus/clicks** on a browser with no takeoffs yet.
  `skipTour(page)` must run via `addInitScript` *before* `page.goto` — setting
  the flag after load can lose the race against the app's own first-run
  check.
- **The sign-in gate blocks every fresh load** while it probes
  `/api/google/session`. Plain `vite dev`/`vite preview` never serve
  `/api/*`, so the probe always resolves to "not configured" and the gate
  offers **Continue without signing in** — but not instantly. `dismissSignInGate`
  waits for the button rather than snapshotting visibility once; a same-tick
  check races the probe and is flaky. Never point this suite at `vercel
  dev`/`dev:api` — that reads `web/.env.local`'s real OAuth/Dropbox/S3
  secrets into a running server for no reason this suite needs.
- **The canvas wordmark text also appears inside the sign-in gate's own
  logo** (a `<span>`, not a `<strong>`) — a plain text locator for
  "TakeoffMonkey" can match both while the gate is still tearing down. Use
  `wordmark(page)` (`getByRole("strong", { name: /TakeoffMonkey/i })`), not
  `getByText`.
- **The Report/export button is `disabled` while `conditions.length === 0`.**
  You cannot open Report on a freshly-imported plan with nothing drawn yet.
  `condition-report.spec.ts`'s route around this — "+ New ▸ Condition…"
  (`createTypedCondition` in `TakeoffCanvas.jsx`) creates a condition with
  zero geometry, no drawing required — is the cheap way to get past that gate
  for anything that needs the Report open.
- **Scripting the drawing tools themselves (trace an area, place a count,
  close a polygon) is NOT covered yet.** `TakeoffCanvas.jsx` is >11k LOC and
  its pointer-commit mechanics weren't reverse-engineered for this pass — see
  the Follow-ups in `docs/specs/unit-testing.md`. If you're adding
  that coverage, expect to spend real time reading `onPointerDown`/
  `onPointerUp` in that file first.
- **CSS-uppercased button labels** (e.g. Export) — match case-insensitively
  (`getByRole`'s `name` accepts a regex) rather than the literal JSX casing.
- **Browser binary**: Playwright caches Chromium under
  `~/.cache/ms-playwright`. A fresh machine needs `npx playwright install
  chromium` once; this repo does not run it in `postinstall` (it's a real
  download, not something every `npm install` should pay for).
- **This machine specifically**: pdf.js and the canvas are real CPU/memory
  work. `playwright.config.ts` caps `workers: 2` on purpose — running many
  Chromium instances at once just means them fighting over the same cores to
  parse the same demo PDF. If a run times out with everything else idle, check
  `free -h` before assuming the test is wrong; a loaded desktop (other Electron
  apps, IDEs, etc.) can genuinely push a normally-sub-second PDF parse past a
  test timeout.

## What this suite is not

No CI wiring exists in this repo yet, so `test:e2e` runs locally/on-demand
only — that's what the TODO actually asked for, not a GitHub Actions setup.
