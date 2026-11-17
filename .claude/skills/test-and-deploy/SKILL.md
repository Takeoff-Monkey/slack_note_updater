---
name: test-and-deploy
description: Test the recent changes for real, then ship them. Always asks dev (default) or production BEFORE running anything, scopes the change set to what actually changed, runs typecheck + the node:test math suite + the Playwright e2e suite, and deploys via scripts/ship.sh only if they pass. Use when asked to test and deploy, ship what's on dev, push the current work, or promote to production.
argument-hint: [dev | prod] — omit and you'll be asked
allowed-tools: Bash Read Grep Glob AskUserQuestion Skill TodoWrite
---

# test-and-deploy — the suites are the gate, `ship.sh` is the door

Two things this repo already has, wired together in the right order: the test
suites (`npm test`, `npm run test:e2e`) and the deploy verbs
(`./scripts/ship.sh`, documented in [`docs/DEPLOY.md`](../../../docs/DEPLOY.md)).
Nothing here reinvents either. What it adds is the discipline between them —
**tests run before the push, and a red suite stops the deploy.**

```
0. Ask: dev or production?      ← ALWAYS first, before any test runs
1. Scope: what actually changed, given that answer
2. Run the gates, cheapest first
3. Read the failures honestly (this sandbox has a known false red)
4. Deploy — dev, or dev-then-promote
5. Verify the deployment landed
6. Report
```

---

## Step 0 — Ask dev or production. Always. Before testing.

This is the first thing the skill does, ahead of any test command. Use
`AskUserQuestion`:

- **Dev site (Recommended)** — `dev` branch → https://takeoff-monkey-git-dev-takeoff-monkey.vercel.app,
  Takeoff Monkey team only. The default; say so.
- **Production** — `monkey-takeoff` → https://takeoff-monkey.vercel.app, public.

The only time you skip the question is when the invocation itself already
answered it (`/test-and-deploy prod`). Then echo the target back in one line
and carry on — don't ask twice.

Ask *first* because the answer changes what "recent changes" means, and
therefore what you test:

| Target | The change set under test |
|---|---|
| **dev** | local `dev` vs `origin/dev` — your unpushed commits **plus** the working tree |
| **prod** | `origin/monkey-takeoff..origin/dev` — everything staged on dev, which may include commits from other sessions you have never seen |

Promoting is not "deploy my change." It ships **everything** sitting on dev.
Read that list before you trust a green run.

---

## Step 1 — Scope the change

```bash
git rev-parse --abbrev-ref HEAD      # expect: dev
git status --short
git fetch origin --quiet
git log --oneline origin/dev..dev            # dev target: unpushed commits
git log --oneline origin/monkey-takeoff..origin/dev   # prod target: what would go live
git diff --stat origin/dev..HEAD             # + `git diff --stat` for the dirty tree
```

Then pick the gates from the paths that actually changed:

| Changed under | Run |
|---|---|
| `web/src`, `web/api`, `web/public`, `web/index.html`, `web/vite.config.*` | the full web gate (Step 2) |
| `web/e2e`, `web/playwright.config.ts` | the full web gate — `typecheck:src` covers `e2e/` too |
| `mcp/` | `cd mcp && npm run typecheck && npm test` |
| `capture/` | `python3 capture/capture_server.py selftest` |
| only `*.md`, `TODO.md`, `docs/` | nothing to test — say that plainly and go to Step 4 |

When in doubt, run the full web gate. It's a few minutes, and it is the only
thing standing between a typo and a public URL.

---

## Step 2 — Run the gates, cheapest first

```bash
cd web
npm run typecheck:src   # BLOCKING — src + e2e, clean today, CI blocks on it too
npm test                # node:test over the pure math + the guard tests
npm run build           # Vite does not flag undefined JSX identifiers; the build does more
npx playwright test     # slowest, so last
```

Order matters: a 2-second `tsc` failure should never cost you a 3-minute
Chromium run.

What a healthy full run looks like here (measured 2026-09-03 on a clean `dev`):
`typecheck:src` silent, `npm test` **997 pass / 0 fail** in ~11s, `build`
clean, e2e **19 passed / 0 failed** in ~2 min.

> **Baseline changed 2026-09-03.** It used to be `996` and `15 passed / 3
> failed`, and the three reds were a sandbox fault to be waved through. Later
> Features #11 fixed the helper that caused them, so **zero failures is now the
> pass mark** — see Step 3.

Notes that will save you a wrong conclusion:

- **`npm run typecheck` (no `:src`) is NOT a gate.** It also covers `web/test/`,
  which carries ~335 pre-existing strict-mode fixture errors (TODO 15). CI
  deliberately reports that as a count instead of failing. Use `typecheck:src`.
- **`npm test` includes the guard tests** — `no-native-dialogs`,
  `no-undefined-identifiers`. A failure there is a real convention violation,
  not flakiness.
- **e2e needs the browser once per machine**: `npx playwright install chromium`.
  Already present here (`~/.cache/ms-playwright`).
- **Check port 5173 before starting.** `playwright.config.ts` sets
  `reuseExistingServer: !process.env.CI`. If another project's Vite is already
  on 5173, Playwright happily reuses it and runs the whole suite against **the
  wrong app**. `ss -ltnp | grep ':5173 '` — if it's occupied by something that
  isn't this repo, stop and tell the user rather than trusting the result.
- **Never `pkill -f vite`** to clean up. This machine runs several projects at
  once, and `-f` also matches the Bash tool's own wrapper command line. Kill a
  recorded PID, or leave it alone.
- The suite is local-only on purpose — GitHub CI
  ([`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml)) runs
  typecheck/test/build, **not** e2e. Your run here is the only e2e signal that
  exists before a deploy.

Load the **`e2e-test`** skill if you need to touch a spec, debug one, or drive
the app in a one-off headless session. It carries the locator gotchas; don't
re-derive them.

---

## Step 3 — Read the e2e failures honestly

**Baseline on an untouched `dev` tree — measured 2026-09-03, `npx playwright
test --workers=1`, ~2 min: `19 passed, 0 failed`. Any red is yours.**

That is a change from this skill's original advice, so it's worth knowing why the
old rule existed. This sandbox's Chromium is the "fallback build for
ubuntu24.04-x64", whose accessibility-tree support is broken, so **`getByRole`
queries never resolve** — everything else (the harness, `webServer`, pointer and
keyboard input, `setInputFiles`, `waitForFunction`, `page.evaluate`) works
normally. `helpers.ts`'s `wordmark()` used a role query, so the three specs that
call it timed out at 60s on every run, and this skill told you to wave them
through. Later Features #11 made `wordmark()` a CSS locator
(`page.locator("strong", { hasText: … })`, which draws the same
`<strong>`-not-the-sign-in-gate's-`<span>` distinction), and all three went green.

The underlying fault is still there: **write new specs with CSS/attribute
locators, never `getByRole`.** But there is no longer a known-red allowance, and
keeping one would be actively dangerous — it would wave through a genuine
regression in `condition-report` or `onboarding`.

Two things that will still save you a wrong conclusion:

- **Never run the suite while anything else is writing to `web/src/`.** A run
  during #11 came back `1 passed, 12 failed` across unrelated specs and looked
  catastrophic; it was a concurrent build triggering Vite HMR reloads underneath
  the running pages. A serial rerun on a quiet tree was 19/19. Before believing a
  broad, scattered failure, check nothing else is touching `src/`.
- **To prove a failure isn't yours, don't `git stash`** a large change — use
  `git worktree add /tmp/head-check HEAD --detach`, symlink `web/node_modules`
  into it, and run the spec there. Non-destructive, and it was how #11 confirmed
  the three reds were pre-existing rather than assuming it.

When a failure is real:

- **Do not deploy.** Report it and stop.
- **Do not edit the test to make it green.** If the test is genuinely wrong,
  say why, and fix it as its own visible change.
- If the fix is small, obvious and inside the change you're already shipping,
  fix it and re-run the full gate from the top. Otherwise hand it back.

**Never pipe the run into `tail`/`head` and read the exit code** — the pipeline
reports `tail`'s status, so a 3-failure run "exits 0". Let it print, or capture
with `npx playwright test 2>&1 | tee /tmp/e2e.log; echo "${PIPESTATUS[0]}"`.

---

## Step 4 — Deploy to dev

```bash
git rev-parse --abbrev-ref HEAD    # must be dev
```

**Never commit or push to `monkey-takeoff` directly** (AGENTS.md). If you're on
it, `git switch dev`.

If the tree is dirty, the changes have to be committed before they can deploy.
Show the user what's uncommitted and confirm the message before committing —
this repo's log uses a one-character prefix:

```
+ Added a dev branch, deploy tooling & docs      ← new capability
* Fixed shape snapping to be more robust         ← fix / adjustment
```

Then:

```bash
./scripts/ship.sh push
```

That's it — no deploy command exists. Vercel's git integration builds on push,
`dev` → the dev site, ~1 minute.

**Verifying dev**: the dev URL sits behind Vercel's Standard Protection, so
`curl` gets an SSO redirect, *not* your app — measured, it answers `302`
(production answers `200`). That is the protection working correctly; never
report it as a failed deploy. Confirm the build instead with `vercel ls` from the repo root,
or ask the user to open the URL (they're signed in on the team). If you truly
need automated access to a protected preview, that's the
`vercel:access-protected-vercel-deployment` skill.

---

## Step 5 — Deploy to production

Production is public and it is one fast-forward off dev. Do it in this order.

**5a. Push dev first, always.** Promote merges local `dev` into
`monkey-takeoff`; pushing first keeps `origin/dev` and production honest, and
gets the same build looked at on the dev site.

```bash
./scripts/ship.sh push
```

**5b. Show exactly what is about to go live.**

```bash
./scripts/ship.sh status
```

Print that commit list to the user verbatim. This is the moment to notice that
promoting carries other sessions' commits along with yours.

**5c. Final confirm.** They picked "production" in Step 0, before they'd seen
the test results or that list. Ask once more, with the list in front of them,
unless they've already said not to re-confirm.

**5d. Promote — and mind the stdin trap.**

`ship.sh promote` guards itself with `read -r -p "Type 'promote' to continue: "`.
Under the Bash tool stdin is not a terminal, so `read` fails, the script's
`|| ans=""` kicks in, and it prints **"Aborted."**, switches you back, and exits
1. That is not a bug and not a rejected deploy — it's an interactive prompt with
nobody home. Feed it:

```bash
printf 'promote\n' | ./scripts/ship.sh promote
```

Only after Step 5c. Piping answers the script's own safety question on the
user's behalf, so their confirmation has to be real and already given. If they
haven't confirmed, don't pipe — hand them the command to run in their terminal.

Two more things about `promote`:

- **`gh` is not installed on this machine**, so promote's CI check falls through
  to "Check CI before you answer" and continues regardless. Your Step 2 run is
  the gate. The GitHub verdict, if wanted, is at
  https://github.com/Takeoff-Monkey/openTakeoff-TOM/actions
- It refuses on a dirty working tree, and merges `--ff-only` — which **refuses
  outright** if production holds a commit dev lacks. Don't work around either;
  both are load-bearing.

**5e. Verify production** — it's public, so this one is a real check:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://takeoff-monkey.vercel.app
```

Give the build ~60–90s first. Expect `200`. Vercel serves the previous build
until the new one is ready, so a 200 alone doesn't prove *your* build is live —
cross-check with `vercel ls` if it matters.

---

## Step 6 — Report

```
## test-and-deploy — <dev | production>

**Change set**   3 commits + 2 modified files   (or: origin/monkey-takeoff..origin/dev)
  * Fixed the thing
  + Added the other thing

### Gates
  typecheck:src   pass
  npm test        pass  (997 tests, ~11s)
  build           pass
  e2e             19 passed, 0 failed

### Deploy
  Pushed dev @ 27d4c5b → https://takeoff-monkey-git-dev-takeoff-monkey.vercel.app
  (team-only URL; curl sees the SSO gate by design)
```

Name the failing specs every time, even when they match the baseline. A run
reported as "e2e: pass" when three specs actually timed out is worse than no run
at all — and next session, that list is the only way to tell a familiar failure
from a new one.

---

## If production is wrong after the fact

```bash
./scripts/ship.sh rollback        # or: rollback <deployment-url>
```

Instant Rollback, no rebuild. Two side effects the script prints and people
still get surprised by: **auto-assignment of the production domain switches
off** (later pushes to `monkey-takeoff` build but do not go live until
`./scripts/ship.sh undo-rollback <url>`), and cron jobs plus environment
variables revert to that older deployment's state too. Then fix forward on dev:
`git revert <bad-sha>` → push → look → promote.

---

## Things that will bite you

| Symptom | What's actually happening |
|---|---|
| `promote` prints "Aborted." with no input from you | The interactive `read` got no terminal — Step 5d |
| `condition-report:20` + `onboarding:21`/`:37` time out in `wordmark()` | The known sandbox baseline, not the app — Step 3 |
| An e2e run "exits 0" with failures in the output | You piped it to `tail`; the pipeline returns `tail`'s status — Step 3 |
| The suite passes but tests the wrong app | A foreign Vite on :5173 got reused — Step 2 |
| "I pushed and the site didn't change" | Check the build actually ran (`vercel ls`); env-var changes never apply retroactively |
| dev URL returns 302 / bounces to `vercel.com/sso-api` | Team-only protection working as designed |
| `promote` refuses with a non-fast-forward | Production holds a commit dev lacks — investigate, don't force |
| Dev looks empty after a deploy | dev and production share **no** IndexedDB; local takeoffs are per-origin |

**Related:** [`docs/DEPLOY.md`](../../../docs/DEPLOY.md) (environments, env vars,
what dev cannot prove) · the `e2e-test` skill (writing/debugging specs) ·
[`AGENTS.md`](../../../AGENTS.md) (commit to `dev`, never to `monkey-takeoff`).
