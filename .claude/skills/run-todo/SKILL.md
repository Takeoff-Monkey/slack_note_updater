---
name: run-todo
description: Implement one specific entry from TODO.md, end to end. Use when the user points at a todo and wants it built ("do todo 7", "implement the XLSX export item", "run-todo zones legend"). Indexes TODO.md by heading and docs/specs/ by filename, reads only the target's spec file(s) — never the whole specs directory — then skims the other todo titles to place the work in the bigger picture, so it doesn't polish a surface another todo is about to overhaul, and asks about ordering when a different item should land first. Then reads the real code, implements, verifies, and logs one line in TODO.md with the detail in the matching docs/specs/ file.
argument-hint: <todo number, or a phrase that identifies it — e.g. "7" or "xlsx export formatting">
allowed-tools: Read Edit Write Grep Glob Bash AskUserQuestion TodoWrite Agent Skill
---

# run-todo — implement one TODO entry, in context of all the others

Take one entry out of the TODO file and actually build it. Two things separate
this from just reading a ticket and typing:

1. **You work from a brief.** Before touching code you write down what "done"
   means, and you keep checking back against it once you're deep in a 3000-line
   component. Otherwise the implementation drifts into whatever the code in front
   of you suggested.
2. **You place the work in the bigger picture first.** The user holds the whole
   roadmap in their head; the single entry you were handed doesn't. A neighboring
   todo may be about to rewrite the exact surface you're working on — building
   carefully there is wasted effort, and nobody will tell you that unless you go
   look.
3. **You navigate by filename, not by reading a monolith.** The detail behind
   `TODO.md`'s one-line asks lives in `docs/specs/` — one small file per
   feature/area, not one ever-growing file with a section per item. `ls
   docs/specs/` tells you what exists; you read the one or two files that
   actually apply and grep for the rest. Context spent on someone else's
   finished feature is context not spent on the code you're changing.
4. **You triage on titles before you triage on content.** The very first pass —
   matching the user's ask to an entry, and spotting which *other* entries or
   spec files might be related — is done by a small, cheap model that sees
   **titles and filenames only**, never file bodies. Only what it flags as
   plausibly relevant gets read in full, and only then does real work (and the
   full-price model) start.

## Flow

```
0. Header scan (lightweight model)   (TODO.md titles + docs/specs/ filenames, before any other step runs)
1. Resolve the target                (which entry; confirm it back before working)
2. Pull in the flagged spec files    (target's spec file(s), read in full)
3. Write the brief                   (from TODO.md + the target's spec file, or from scratch if none exists)
4. Decide order and depth            (act on what the header scan flagged → ASK if it changes plans)
5. Read the real code                (verify the entry's notes are still true)
6. Implement                         (dependency order; additive + back-compat)
7. Verify                            (tests, grep new identifiers, e2e-test skill by default, load the app)
8. Log it                            (1 line in TODO.md, detail in docs/specs/<slug>.md, + docs)
9. Report                            (what's done, what was left deliberately minimal + why)
```

---

## Step 0 — Header scan, with a lightweight model, before anything else

The todos live in **two places**. `docs/TODO.md` (root `TODO.md` in other
repos) is the human-readable list of asks — short. `docs/specs/` is the
verbose agent-facing detail — one file per feature/area, holding briefs and
build records. Most of it is other people's finished work; usually one or two
files are yours.

**Never read `TODO.md` end to end for its bodies, and never open every file
under `docs/specs/`**, and never let the full-price model do the first pass.
The triage that decides *which* entry the user means and *which spec files
might be related* only needs titles and filenames — so it runs on a small,
cheap model first, before any spec file is opened and before any code is
touched.

**a. Build the raw index** (bash, no model needed for this part):

```bash
wc -l docs/TODO.md
grep -nE '^[0-9]+\. |^# ' docs/TODO.md        # item titles, with line numbers
ls docs/specs/                                # every spec filename — the whole map
```

That's a couple dozen lines of output — titles and filenames, no bodies.

**b. Hand that output to a lightweight-model agent, not your own reasoning.**
Spawn it with the `Agent` tool, `model: "haiku"`, and give it nothing but: the
two outputs above, the user's raw argument (e.g. `"7"` or `"xlsx export
formatting"`), and this task: *identify the target entry (or the ambiguous
candidates if it can't tell), and separately list any spec filenames under
`docs/specs/` that plausibly cover the same surface, area, file, or feature as
the target — by filename alone, no bodies read — plus any other `TODO.md`
titles that look related.* Ask it to report back structured and terse: the
resolved target's heading + line number, the ambiguous set if any, and a short
list of `{spec filename or TODO title, one-clause reason it might be related}`
for candidates worth a closer look. Run this in the foreground — the next step
needs its answer before anything else can happen.

This is the whole point of the split: the cheap model spends its context on
titles and filenames only, decides what's *worth* pulling in, and the
expensive model never even sees the rest of `docs/specs/`.

---

## Step 1 — Resolve the target

Take the lightweight agent's answer as the resolution, then apply the same
judgment calls on top of it:

- **Ambiguous or matches several** — ask which one. Don't guess and burn an hour
  on the wrong item.
- **Whole item already `~~struck through~~`** — it's done. Say so and ask whether
  they meant its remaining live bullets or the `Follow-ups` in its spec file.
- **Partially struck through** — implement only the live sub-bullets.
- **Huge item** (the sort with three levels of sub-bullets and several
  independent deliverables) — propose splitting it: name the slice you'd do now,
  and get a nod before starting.

State the resolved target in one line before moving on, so a
misresolution gets caught immediately.

---

## Step 2 — Pull in the flagged spec files (and only those)

Now, and only now, read actual content — scoped to exactly what Step 0 flagged:

- Skim [`docs/specs/README.md`](../../../docs/specs/README.md) once, at the
  start of a session that hasn't already read it — it's short (the naming
  rule and the per-file shape), not a coverage map to maintain.
- **The target's own spec file(s)**, if the lightweight agent matched one by
  filename — `Read` the whole file; these are small by design, not a section
  offset into a giant one.
- your target's bullets in `TODO.md` — plus, if the whole file is under ~200
  lines, just read it (it's cheaper than several greps and Step 4 wants the
  titles anyway).
- for each spec filename or `TODO.md` title the lightweight agent flagged as
  plausibly related: just note the name for now. Step 4 decides whether any of
  those earn a full read; most won't.

Everything else in `docs/specs/` is reached by **targeted grep**, never by
opening files one by one: when you need to know whether anything else touches
a seam, grep the seam (Step 4), not the directory.

**No existing spec file matches the target?** That's expected for an item
that's never been built — derive the brief in Step 3 and create
`docs/specs/<slug>.md` for it before you start coding, rather than trying to
find where it "should" already be.

If `docs/specs/` doesn't exist at all in a given repo, everything lives in
`TODO.md` and you create the directory (with a `README.md` copied from this
repo's) the first time you write a spec file.

---

## Step 3 — Write the brief (before any code)

Your brief is the **`Brief` section in the target's spec file** under
`docs/specs/` — the one file you read in full in Step 2. If it exists, restate
it compactly (5–10 lines) in your response so it's in front of you:

- **Done =** the user-visible behavior, phrased so you could verify it by hand.
- **Acceptance checks** — the concrete things you'll confirm in Step 7.
- **Files/functions** it names, and the pattern it says to copy.
- **Data model** change, if any.
- **Seams** that need to stay threaded.
- **Out of scope** — so you can point at it later.

If Step 2 found **no** spec file for this item (an older or hand-written entry
that's never been briefed), derive the brief from the `TODO.md` bullets plus a
quick read of the code, and **write it into a new `docs/specs/<slug>.md`**
before you start — pick the slug from the feature/area, not the `TODO.md` item
number (numbers get renumbered; filenames shouldn't have to move when they
are). That's the whole purpose of the directory: the next agent shouldn't have
to re-derive it, and it shouldn't matter what number this item has by then.

Then load the subtasks into `TodoWrite` in dependency order, so progress stays
visible and nothing silently drops.

Two kinds of bullet are **blocking**, and both come from how these entries get
written:

- **`Open question:`** — unresolved by design. Resolve it with the user (batch
  into the Step 4 question call) before coding the part it governs.
- **`Assumption:`** — someone's guess, recorded so it could be challenged.
  Sanity-check it against the code in Step 5; if it's wrong, surface it rather
  than quietly building on it.

`Related (not asked for):` bullets are **not** in scope. Leave them alone unless
the user says otherwise.

**The brief is your anchor.** Re-read it when you're deep in the weeds and again
before you call the work done. If what you're building no longer matches it,
stop and say so — either the brief was wrong or you drifted, and both are worth
a sentence to the user.

---

## Step 4 — Decide order and depth from what Step 0 flagged

One question: **does any other entry change how, how deeply, or whether I should do
this one now?** This is the step that gives you the developer's mental model
instead of a ticket's tunnel vision — and you answer it from the lightweight
agent's candidate list and targeted greps, not by reading every spec file or
all of `TODO.md`.

**a. The lightweight agent's candidates.** Step 0 already did the title/filename
pass and handed you a short list of `{spec filename or TODO title, reason}` —
most items were already dismissed as unrelated by that pass and never entered
this model's context at all. Expand only those two or three candidates, by
reading them now (their `docs/specs/` file, if Step 2 didn't already pull it
in). If the lightweight agent's list looks wrong once you see the actual
target's brief (Step 3), re-scan: a fresh `grep -nE '^[0-9]+\. |^# '
docs/TODO.md` plus `ls docs/specs/` is a fine fallback, still title/filename-only.

**b. Then grep the seam, not the directory.** Once Step 5 tells you which files
and identifiers you'll actually touch, that's your search key — it finds the
interactions a title never would:

```bash
grep -niE 'totals\.js|worksheet|export' docs/TODO.md            # live asks on this seam
grep -rniE 'totals\.js|worksheet|export' docs/specs/ | head -40  # finished build records on this seam
```

A hit in `TODO.md` is a live item to classify below. A hit in `docs/specs/` is
usually a finished build record — read the ±30 lines around it in that one
file, and only then the whole file, if it says something about your seam you
didn't know. A grep that returns nothing is a real answer: nobody else is on
this surface.

**c. The `## Questions for team:` section** — it's a dozen lines at the end of
`TODO.md`; read it. An unanswered question there that bears on your entry is worth
raising before you build around it.

If a scan tempts you into opening a dozen spec files "just to be safe", stop:
the thing you're protecting against is *another live item rewriting your surface*,
and live items are in `TODO.md`, which is short. A spec file describing shipped
work can't supersede anything — it already shipped.

### Classify the ones that touch your work

| Relationship | Signal | What it means for you |
|---|---|---|
| **Supersedes** | another item rewrites/overhauls the surface you'd build on (UI overhaul, export rewrite, storage migration) | anything you polish there is throwaway — go minimal, deliberately |
| **Prerequisite** | your item is much cheaper, or only correct, after that one lands | flag it and **ask** about ordering |
| **Shared seam** | both items touch the same file, field, or exporter | build so both can land: don't hardcode what the other needs to vary |
| **Overlapping** | the two items are partly the same work | say so before coding; maybe they should merge |
| **Downstream** | another item consumes what you're building | leave the hook, don't build their half |

### The ordering decision

**Interrupt and ask** (single batched `AskUserQuestion`, *before* writing code) when:

- the other item is a genuine prerequisite and doing yours first means real
  rework, or
- doing yours first produces substantial throwaway work in a surface the other
  item rewrites, or
- the two overlap enough that one of them should probably absorb the other.

Give them the actual trade-off: what you'd build now, what gets redone later,
roughly how much. Offer the concrete options — do the prerequisite first, do this
one minimally, do this one fully anyway.

**Go minimal, then report** (don't interrupt) when:

- the overlap sits in a layer that's cheap to redo — styling, polish, copy — and
  ordering is preference rather than correctness.

The user's example is the canonical case: a new panel, with a UI overhaul sitting
in another todo. Don't spend the afternoon on that panel's chrome. Either ask
whether they want the overhaul first, or build the panel functional-and-plain and
tell them why at the end.

### What "minimal" means here

Minimal is a scope choice, never a quality excuse:

- **Fully functional.** Every behavior in the brief works. Minimal ≠ half-wired.
- **Maximally conventional.** Reuse the existing components, tokens, and layout
  primitives rather than inventing anything — then the later overhaul sweeps your
  code up for free instead of having to unpick it.
- **No bespoke anything** in the superseded layer: no one-off CSS, no custom
  widget where a standard one fits.
- **Recorded.** One `Minimal:` line in the entry naming the todo you deferred to
  (format in Step 8), and raise it in the Step 9 report as an offered follow-up.

Never silently do a half job, and never silently expand into another todo's
scope. Both are the failure modes this step exists to prevent.

---

## Step 5 — Read the real code before editing it

The entry's notes were written at some point in the past; the code has moved
since. Open the files it names and confirm its claims — the function still
exists, the gap is still the gap, the pattern it says to copy is still the
pattern.

If the notes are **stale or wrong**, fix them as part of the work — the `Brief` in
the spec file is usually where the wrong detail lives, so correct it there and
leave `TODO.md` alone unless the *ask itself* changed. Tell the user what changed.
A todo that lies is worse than one that's thin.

Skim [`AGENTS.md`](../../../AGENTS.md) ("Where things live" + "Conventions")
if it isn't already in context.

---

## Step 6 — Implement

Work the `TodoWrite` list in dependency order — data model, then logic, then UI,
then the other consumers of that data. Land it in coherent pieces rather than one
sprawling edit.

Non-negotiables in this repo:

- **Additive and back-compat.** New persisted fields must be optional; a project
  saved before your change must still load, with the old behavior when the field
  is absent.
- **Single-source shared logic.** Anything the canvas *and* an exporter both need
  goes in `web/src/lib/*.js` once, and both call it. Copy-pasting the math is how
  the canvas and the PDF end up disagreeing.
- **No native dialogs.** `dialog.alert/confirm/prompt` from
  `web/src/components/Dialog.jsx` for blocking prompts, `setCommitMsg(...)`
  toasts for transient status. A test fails the build otherwise.
- **Canvas performance.** Cursor-following UI writes to the DOM directly
  (`moveCrosshair`); never add React state that updates per mousemove.
- **Don't re-theme user data.** Condition colors and palettes belong to the user.
- **UI chrome conventions.** `data-tip` + `TooltipLayer` (not `title=`),
  `SelectMenu` (not native `<select>`), colors from `web/src/styles/tokens.css`.
  SVG presentation attributes need literal colors, not CSS vars.
- **Localize every string you add or touch.** Any user-facing text a UI change
  introduces or edits — button/menu labels, column headers, tooltips
  (`data-tip`), `aria-label`s, placeholders, empty states, toast/dialog text
  (`setCommitMsg`, `dialog.*`), Settings/Help copy — gets a `t("...")` key, never
  a hardcoded string in JSX or in a config object's `label:`/`help:`/`title:`.
  Wire it with `useI18n()`'s `t`; a plain module or class component with no hook
  access threads a `t` callback in from its caller instead of hardcoding (see
  `web/src/lib/activity.js`'s `tr()` helper for the pattern). Concretely, in the
  same edit that adds or changes the string:
  - Add the key to `web/lang/en.json` under that page/panel/component's own
    section (`components.<Name>.*`, matching neighbors already there), and the
    **same** key with a real translation — never a copy of the English — to
    every other `web/lang/*.json` file. A key in one file and not the others is
    localization silently drifting; treat it as a bug in your own change, not a
    follow-up.
  - Reuse the app's existing terms for reused concepts (check a few sibling
    keys before inventing new phrasing — e.g. this repo's Spanish glossary
    settled on "toma de datos" for takeoff, "cronograma" for schedule, "IA" for
    AI) rather than translating the same word two different ways.
  - Short, direct UI (buttons, menu items, column headers) gets a literal,
    1:1 translation; longer prose (help text, explanatory tooltips) can be
    sentiment-based rather than word-for-word.
  - Never change the wording of a key that already exists unless the user
    asked for that wording change, or you're fixing a genuine wiring bug (the
    key and its translations already exist but nothing calls `t()` on it yet).

Thread the seams the brief listed. The usual suspects: persistence
(`web/src/lib/store.js`), the canvas overlay
(`web/src/pages/TakeoffCanvas.jsx`), the schedules→groups→conditions and
zones hierarchies, `web/src/lib/totals.js`, every export channel in scope (CSV,
JSON, XLSX, report PDF, marked-set PDF, Bluebeam PDF+FDF), Bluebeam import
(`web/src/lib/bluebeam.js`), the MCP surface (`mcp/`), the keybind registry
(`web/src/lib/keybinds.js`), and Settings if it's toggleable.

If you hit something that makes the entry's plan unworkable, stop and say so with
the reason — don't quietly substitute a different feature.

---

## Step 7 — Verify

```bash
cd web && npm test          # pure geometry + totals math, and the no-native-dialogs guard
npm run build               # catches import-level breakage
```

Then, because **Vite does not flag undefined identifiers in JSX**: grep every new
identifier you introduced to confirm it's defined and imported where it's used.
This repo has been bitten by exactly that.

If the entry touched any UI, also verify localization stayed in sync — every
`web/lang/*.json` file must carry the exact same set of keys:

```bash
node -e '
const fs = require("fs");
const dir = "web/lang";
const files = fs.readdirSync(dir).filter((f) => f.endsWith(".json"));
const flat = (o, p = "") => Object.entries(o).flatMap(([k, v]) =>
  v && typeof v === "object" ? flat(v, p + k + ".") : [p + k]);
const sets = files.map((f) => new Set(flat(JSON.parse(fs.readFileSync(`${dir}/${f}`, "utf8")))));
const [base] = sets;
let ok = true;
files.forEach((f, i) => {
  if (i === 0) return;
  const missing = [...base].filter((k) => !sets[i].has(k));
  const extra = [...sets[i]].filter((k) => !base.has(k));
  if (missing.length || extra.length) { ok = false; console.log(f, "missing:", missing, "extra:", extra); }
});
console.log(ok ? "lang files in parity" : "LANG FILES OUT OF SYNC");
'
```

A `missing:` entry means a new string never made it into that language file; an
`extra:` entry usually means a key got added straight to a translation file
without also landing in `en.json` (the authoring source). Fix either before
calling the item done — re-read the "Localize every string" bullet in Step 6,
don't just copy English text over to satisfy the parity check.

Also skim any file you touched for `data-tip="…"`, `aria-label="…"`,
`placeholder="…"`, or JSX text that's a literal string rather than a `t("...")`
call — the parity check above only catches a key that's missing everywhere, not
one that was never created in the first place.

Add tests to `web/test/*.test.ts` for any new pure math.

### Browser tests via the `e2e-test` skill — on by default

**Unless the user explicitly said they don't want tests run** (e.g. "skip the
tests", "no e2e", "don't run tests" in the prompt that invoked this skill), invoke
the `e2e-test` skill (`Skill` tool) for any entry that adds or changes a feature
with user-visible or persisted behavior, and follow it. It carries the gotchas
that make headless runs reliable here. Use it to:

- **Extend the suite** — add or update a checked-in spec under `web/e2e/` covering
  the brief's acceptance checks for the new/changed feature (CSS-only selectors;
  see the reference spec the skill names).
- **Run it** — the new/changed spec(s) plus the neighbouring specs on the surface
  you touched. Run the whole suite when the change is cross-cutting (canvas
  store, persistence, hooks, shared chrome).

Failures go in the report with their output; fix them, or say plainly why a
failure is pre-existing/unrelated. Don't weaken a spec to make it pass.

Skip this only when the user opted out, or the change is purely non-behavioral
(docs, copy-only, pure `lib/` math already covered by `npm test`). If you skip,
say so and why in the Step 9 report. An explicit opt-out is honored for this run
only; don't carry it to later runs.

Then check whatever the specs can't reach by hand against the brief's acceptance
list. The fastest end-to-end path is the bundled sample plan ("Load sample
plan"): load it, press `A`, trace a room, open Report. If verifying needs the
running app, the `run` skill covers launching it.

Report failures as failures, with the output. Do not describe unverified work as
done.

---

## Step 8 — Write the log: one line in `TODO.md`, the detail in `docs/specs/<slug>.md`

Two files, two audiences. Get this backwards and the TODO file becomes a wall of
text a human stops reading.

| | `docs/TODO.md` | `docs/specs/<slug>.md` |
|---|---|---|
| for | the human, at a glance | you, next time |
| budget | **1 line**, +1 if you deferred something | as long as it needs to be |
| holds | what works now, and where | why, how, what you tested, what you rejected |

### `TODO.md` — mark done, then one line

- `~~Strike through~~` the sub-bullets you finished; leave the rest live.
- Strike the item title only when the whole thing is done. Never strike anything
  you couldn't verify.
- A finished sub-bullet needs **no** note. The strikethrough *is* the log.
- Then add **one** line, ≤ ~160 chars, ending in a spec link:

```
    - DONE: `lib/thing.js` — <what works now, one clause>. [spec](specs/<slug>.md)
```

- Add a **second** line only if Step 4 left something deliberately plain:

```
    - Minimal: <what's plain> — deferring to #<n>
```

- Genuine remaining work becomes a **live sub-bullet in the user's own voice** —
  terse, unstruck, indistinguishable from a bullet they'd write. Do *not* write a
  `Follow-ups:` prose line; if it's real work say it as work, and if it's merely
  context it belongs in the spec file.

That's the whole `TODO.md` writeback. Two lines, worst case.

### What never goes in `TODO.md`

Cut it if a reader could get it from the struck text or by opening the file you
named — that's most of what wants to be written. Specifically banned:

- **Testing and validation notes.** "Validated round-trip against a real Revu
  export", "opens in LibreOffice", "tests pass". → spec file.
- Function/constant names, seam-by-seam accounting, how it works internally.
- Rejected alternatives and reasoning. → spec file.
- Dates, "successfully", "I implemented", line counts, restating the subtasks.

Style for the one line that survives: telegraphic. Fragments, `→ + ; w/`,
backticked paths, no sentences.

### `docs/specs/<slug>.md` — the detail

Follow the shape documented in [`docs/specs/README.md`](../../../docs/specs/README.md)
(`Status` / `Brief` / `Built` / `Validation` / `Follow-ups`, omitting empty
headings). If the file already exists (you read it in Step 2), `Edit` inside it
rather than starting a second file for the same feature/area — you don't need to
re-read it to write to it. If this is genuinely a new feature/area with nothing
existing to extend, create `docs/specs/<slug>.md` fresh, named for the
feature/area, not the `TODO.md` item number.

Everything you wanted to write in `TODO.md` goes here instead — decisions,
rejected options, what you tested and how, the follow-up detail a one-liner
can't carry.

- Pick the slug from what the feature *is* (`legend-column-presets`, not
  `todo-16`) — that's what makes it grep-and-guessable next time, and it means
  the file never needs renaming when `TODO.md` gets renumbered or re-filed
  around it.
- Write for grep: name the real files, functions and fields in the prose,
  because a targeted grep is how the next agent will find this file at all.
- A feature that accumulates several passes over time keeps living in the one
  file — extend `Built`/`Validation`/`Follow-ups` in place rather than
  appending a second "pass 2" file for the same area.
- No coverage table, no archive step to move a "finished" file into — the
  filename already says what it is, and a spec file describing shipped work
  doesn't need relocating just because `TODO.md` dropped its bullet.

### Good vs. bad

```
BAD  - DONE (one column spec, five consumers): `WORKSHEET_COLUMNS` in `web/src/lib/totals.js` is now
       the single column model — `Item · Notes · Qty 1–3/UOM 1–3 · Shapes · Waste % · Tag` (Tag off by
       default) — and the on-screen table, the XLSX, the JSON, the CSV builder and the marked-set PDF's
       worksheet page all render from it via `walkWorksheet`/`worksheetColumns`/... [+9 more lines]
     - Deliberately minimal: the **Item** column can't be switched off (a row with no identity is...
     - Notes: the TOTAL row only sums what totals honestly — the shape count, and a Qty slot whose...
     - Follow-ups (not blocking): a per-section subtotal row (the demo has none); a second XLSX...

GOOD - DONE: `totals.js` `WORKSHEET_COLUMNS` = one column spec → table + XLSX + JSON + CSV + marked-set PDF; new `lib/xlsx.js` writer matches the demo format. [spec](specs/import-export.md)
     - per-section subtotal row; a second XLSX sheet per zone; column choice into the Bluebeam legend
```

Nothing was lost — every clause of the BAD version now lives in
`docs/specs/import-export.md`, where it's still one click away and doesn't cost
a human anything to skip.

Apply the same brevity to any entry you correct in Step 5 and to the `Minimal:`
line from Step 4.

### Docs

Sync what the change touches — `README.md` (Features / What's in the box),
`docs/USER_GUIDE.md` (shortcuts + the relevant section) — then cut a new
version (below). Don't commit or push unless the user asks.

### Cut a version: `docs/CHANGELOG.md` — the ONLY place this lives

Every run-todo ships as its own version — there's no `Unreleased` bucket to
add to, and (since 2026-09-01) no separate version field or highlights file
either: `web/src/lib/changelog.js` derives *everything* the app shows — the
version number and the sign-in screen's highlight bullets — by parsing this
one file's newest (topmost) `## ` entry. `web/package.json`'s `version` is
not read by anything and does not need touching. This is deliberate: the bug
that made this the rule was a version number frozen on the sign-in screen
while `docs/CHANGELOG.md` kept gaining new entries above it, because the
displayed version came from a second place (`package.json`) that this step
used to also require bumping, by hand, in lockstep — and didn't. One file,
one edit, nothing to keep in sync.

0. **Same day = same entry, by default.** Check the date on the current top
   entry first. If it's today's date, this change ships inside that entry
   rather than as a new one — even if today's earlier work was on something
   unrelated. Random, unconnected changes made the same day still bundle
   together; a user sitting down to read the changelog cares about "what's
   different since yesterday," not how many separate sessions produced it.
   Cut a genuinely new entry instead only when:
   - the user explicitly said, in the prompt that invoked this skill, that
     they want this to bump to a new version (theirs always wins, either
     direction), or
   - this change is MASSIVE on its own — the sweeping, major-bump kind (a UI
     overhaul, a rethink of how a whole feature works) — big enough that
     burying it inside today's existing entry would undersell it.

   Otherwise merge into the existing top entry: leave its version and date
   as they are, fold this change into whichever subsection it belongs to
   (`### Added` / `### Changed` / `### Fixed`, adding one if the entry
   doesn't have it yet), and re-derive `### Highlights` from the entry's
   *entire* bullet list as it now stands — not just today's newest bullets —
   since an earlier highlight can go stale once a later same-day change
   supersedes it. If folding this in pushes the entry's overall content past
   its current tier (a patch-only entry picks up its first real `### Added`
   bullet, say), bump the version the way step 1 below describes; otherwise
   leave the version untouched. Skip straight to step 2 having edited in
   place rather than prepended.
1. **Decide the bump** (new entry only). Semver, and it's your call unless
   the user stated one in the prompt that invoked this skill (theirs always
   wins): **patch** — pure bugfix, nothing new to use; **minor** — a real
   added or changed capability, the normal case; **major** — a sweeping
   change (a UI overhaul, a rethink of how a whole feature works). Read the
   current version straight off the existing top entry's header and bump
   whichever part that tier calls for (reset the parts below it to `0`,
   standard semver).
2. **Prepend one entry to `docs/CHANGELOG.md`** (new entry only), right
   after the file's one-line preamble, above whatever is currently the top
   entry:
   ```
   ## v<version> — <YYYY-MM-DD> — <short title>

   ### Highlights
   - one-liner with its **focus word or phrase bolded**
   - another one-liner, same treatment
   ### Added
   - ...
   ### Changed
   - ...
   ### Fixed
   - ...
   ```
   Only include the subsections you actually have content for. **This file
   is user-facing, not a dev log** — an average estimator using the app is
   the entire audience:
   - Plain language: what changed, in terms of a button, menu, shortcut, or
     behavior the user sees. No function/file/variable names, no "seam",
     no data-model field names, no `TODO #N`, no test/validation notes, no
     reasoning about why one technical approach beat another. That
     content belongs in the spec file, not here.
   - One bullet, one thought, **bold** lead-in phrase naming the actual
     feature/control, plain sentence after. If a deployer-only detail
     matters (a new env var, an IAM change), it goes in
     `web/api/README.md`, never in a `docs/CHANGELOG.md` bullet.
   - This is the same voice the rest of the file was condensed into on
     2026-08-31 — skim a couple of entries above yours before writing if
     you haven't touched this file before.
   - **`### Highlights` goes first, and only on a minor or major bump** — a
     patch-only bugfix session skips it entirely (`currentHighlights()`
     then just returns nothing, and the sign-in screen's "what's new"
     section hides itself, which is correct: there's nothing worth telling
     that user about). Two or three bullets, rarely more than five — the
     handful of changes in this version an average user would actually
     notice and care about, not a re-list of every `### Added`/`### Changed`
     bullet below it. Every one still needs its own `**bold**` span (a
     control name, a number, the feature itself): both this group and the
     rest of the entry render through the same `InlineMd` markdown
     (`components/ChangelogModal.jsx`), so a plain unbolded line here reads
     as a visible inconsistency, not a style choice.

`web/src/lib/changelog.js` reads this file at build time (`?raw` import) —
the sign-in gate's "what's new" panel and the full changelog viewer both
render straight from it, so nothing else needs wiring, and nothing else can
drift out of sync with it.

---

## Step 9 — Report

Close with:

1. **What now works** — the acceptance checks, and how each was verified (test,
   build, e2e spec, by hand in the app). Failures stated plainly. If e2e was
   skipped (user opt-out or non-behavioral change), say so.
2. **Files changed**, as clickable links.
3. **What was left deliberately minimal, and why** — naming the todo you deferred
   to. Then ask whether they want that follow-up done now. This is the whole
   point of Step 4; don't let it evaporate into the diff.
4. **Anything the entry got wrong** that you corrected, and any `Assumption:` you
   found to be false.
5. **Any other todo this newly unblocks or collides with** — cheap to say, and
   it's the roadmap context they're holding in their head anyway.
