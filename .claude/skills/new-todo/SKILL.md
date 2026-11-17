---
name: new-todo
description: Turn a rough feature idea, bug report, or change request into a fully fleshed-out, implementation-ready todo — the terse ask in TODO.md, the full brief in a docs/specs/ file. Use when the user wants to record work for later ("add a todo for…", "new todo:", "write this up in TODO.md", "I want the app to eventually do X"). Reads the pertinent code first to pin down the real gap and the scope boundary, asks clarifying questions when the request is still ambiguous, surfaces adjacent gaps the user didn't mention, then reports exactly where to read it.
argument-hint: <rough description of the feature, bug, or change to write up>
allowed-tools: Read Edit Write Grep Glob Bash AskUserQuestion
---

# new-todo — write a rough idea up as an implementation-ready TODO

The user's own TODOs are hand-written shorthand: correct about intent, thin on
detail. Your job is to take a rough prompt and expand it into an entry in
`TODO.md` (or alternatively `docs/TODO/` if that doesn't exist) that a coding
agent (probably you, later, with little/no memory of this conversation) can
pick up and implement, ideally **without asking any follow-up questions**.

The notes live in **two places**, and you write both: the terse human-facing ask in
`TODO.md`, and the full implementation brief in a file under `docs/specs/`, named
for the feature/area rather than the item number (numbers get renumbered and
re-filed over time; a spec file's name shouldn't have to move when they are).

**You are writing notes, not code.** Do not implement anything, do not touch
files under `web/`, `server/`, or `mcp/`. The only files you edit are `TODO.md`
and the one `docs/specs/<slug>.md` file. If the user's prompt seems to also ask
for implementation, write the notes first, report them, and ask whether they
want you to start.

## Flow

```
1. Read TODO.md                 (always, in full — format + what's already there)
2. Read the pertinent code      (the files this lands in — find the real gap + the boundary)
3. Check docs/specs/            (does a file already cover this feature/area?)
4. Clarify with the user        (AskUserQuestion, one batched call, only if it matters)
5. Draft the entry              (terse ask for TODO.md + full brief for the spec file)
6. Write both files             (append TODO.md as next number; create or extend the spec file)
7. Report where to read it      (mandatory — see Step 7)
```

---

## Step 1 — Read the TODO file first

Locate it before reading — root `TODO.md` first, then `docs/TODO.md`
(`ls TODO.md docs/TODO.md 2>/dev/null`; in *this* repo it lives at
`docs/TODO.md`). If both exist, use the one with real content and say which you
picked. If there's genuinely none, ask the user where it should go rather than
inventing a location. Everything below writes it `docs/TODO.md` — read that as
"whichever file you found."

Read the whole file before anything else. You need it for three reasons:

- **Format.** Match the existing style exactly (see Step 5).
- **Duplicates.** The idea may already be item 7 in a thinner form. If so,
  **expand that item in place** instead of adding a new one — and say so in your
  report. Watch for `~~strikethrough~~` items: those are done — a `DONE:` line with
  a `[spec]` link means the detail is in a `docs/specs/` file, so read that file
  before adding to the item. A follow-up to a done item becomes a new live
  sub-bullet under it.
- **Adjacency.** Related items tell you what the user already cares about and
  what vocabulary they use for it.

Also skim [`AGENTS.md`](../../../AGENTS.md) ("Where things live" + "Conventions")
if you don't already have it in context — the subtasks you write should respect
those conventions.

---

## Step 2 — Read the code the todo lands in

This step is not optional and it is not just a name-lookup. **Actually open and
read the relevant code**, so you understand what already exists before you write
about what should exist. A todo written without reading the target file describes
an imagined feature; one written after reading it describes a diff.

Two things you get only by reading, and both change the entry:

- **What the user IS asking for.** Their shorthand assumes context they already
  have in their head. Reading the file recovers it — the real prop/state names,
  what's already half-built, what the "obvious" place to hook in actually is.
- **What they are NOT asking for.** Reading shows you the boundary. Half of a
  good todo is a correct `out of scope` list, and you can't write one without
  knowing what's adjacent.

### How to scope the reading

Pertinent files and blocks only — never a whole-codebase sweep, and don't read a
2000-line file front to back when the feature touches one component in it. A
reasonable pass:

1. **Locate** — Grep/Glob for the feature's vocabulary (the panel's title text, a
   label, a condition field, a tool name) to find the owning file(s).
2. **Read the owning code properly** — the component or function that owns the
   behavior today, plus enough of its surroundings to see how it gets its data
   and who renders it. If the user says "add X to the zones panel," go read the
   zones panel component; don't infer it from its filename.
3. **Follow one hop out** — where its state is persisted, and where the same data
   is re-consumed (the exporters, `totals.js`, the MCP surface). One hop is
   usually enough; stop when you're reading things the feature can't touch.
4. **Stop.** You're done when you could point at the lines that would change.

Read directly with Read/Grep/Glob. Use the Agent tool for recon **only** if the
user explicitly asks for it.

### What to come out with

- The file(s) and, where you can, the **specific functions/lines** that would
  change — cite them as `path:line` in the entry.
- **The gap, precisely.** Not "the panel needs column toggles" but "the panel
  already maps over a `cols` array at `LegendPanel.jsx:88` but hardcodes
  visibility — the toggle has nowhere to persist to yet."
- The existing pattern this should copy. This repo has strong precedents — a new
  shared-geometry concern goes in `web/src/lib/*.js` and gets consumed by the
  canvas *and* every exporter, same as `lib/countmark.js` / `lib/legendbox.js`.
- Whether the persisted document model needs a new field.
- **Anything already done.** If part of the ask exists, don't write a subtask for
  it — note it as already handled and cite the line. If *all* of it exists, stop
  and tell the user instead of writing the todo.

### Adjacent findings

Reading the code will surface things the user didn't mention but probably wants:
a sibling control with the same gap, a second call site that would visibly
disagree if only the first is changed, a stale bit of the same component.

- If it's **load-bearing** for the ask — the feature is broken or inconsistent
  without it — fold it into the subtasks and say why.
- If it's **merely nearby** — real, but a separate piece of work — do not smuggle
  it into scope. Add it to the entry as a `Related (not asked for):` bullet, and
  **call it out to the user in your Step 7 report** so they can decide whether to
  promote it, split it into its own item, or drop it.

Keep this honest and short. Two or three genuine adjacent findings are useful; a
list of ten is a code review the user didn't ask for.

If recon reveals the request is already implemented, or is blocked by something
structural, say so in the report rather than silently writing a TODO for work
that can't happen.

---

## Step 3 — Check `docs/specs/` for an existing file on this feature/area

Before drafting anything, find out whether this feature/area already has a spec
file — a feature that shipped once and is getting a follow-up should extend its
existing file, not fork a second one:

```bash
ls docs/specs/
grep -rli '<feature vocabulary>' docs/specs/
```

- **A matching file exists** — read it. Your new entry's brief goes into that
  same file (a new paragraph under `Brief`, or a new dated note if it's already
  `done` and this is a genuine follow-up), not a new file. Say in your report
  which file you're extending.
- **Nothing matches** — you'll create `docs/specs/<slug>.md` in Step 6. Pick the
  slug from what the feature *is* (`legend-column-presets`, not `todo-16`), so
  it's the kind of name a future `grep`/`ls` would actually guess.

If `docs/specs/` doesn't exist yet in this repo, create it in Step 6 with a
`README.md` copied from this repo's (`docs/specs/README.md`) — the naming rule
and the per-file shape below.

---

## Step 4 — Clarify — but only when it changes the entry

Use `AskUserQuestion` when a reasonable implementer could read the prompt two
ways and the two readings produce **materially different code**. Batch all of
your questions into a **single call** (max 4), and put your recommended option
first labelled `(Recommended)`.

Ask **after** Steps 2–3, not before — reading the code answers a lot of what
looked ambiguous in the prompt, and it lets you ask sharper questions ("the
panel already has a `cols` array — do you want per-page overrides or one
project-wide preset?" beats "how should columns work?").

Good reasons to ask:

- **Scope boundary** — "does this apply per-page or project-wide?", "count
  conditions too, or areas only?"
- **Where it surfaces** — condition details panel vs. Settings vs. right-click
  menu vs. header menu.
- **Behavior on existing data** — do saved projects get migrated, or does the
  new thing default off?
- **Which output channels** — this repo has many exporters (CSV, JSON, XLSX,
  report PDF, marked-set PDF, Bluebeam PDF+FDF, MCP); "does this need to show up
  in exports?" is almost always worth asking.
- **Priority** — beta-blocking or not (this decides whether it also goes in the
  top `# Major TODOs for beta:` list).

Do **not** ask about things you can settle yourself: file placement, naming,
whether to follow an existing convention, or anything `AGENTS.md` /
`docs/TODO.md` already answers. Don't ask permission to write the TODO.

**One round, normally.** Ask once, then write. Only ask a second round if the
first answers opened a genuine fork. If the user answers vaguely or says "you
decide," pick the sensible default, write it as a stated assumption in the entry
(see `Assumption:` below), and move on.

If a question is really a **product decision for the team** rather than
something the user can answer alone, don't block on it — append it as a bullet
under the existing `## Questions for team:` section at the bottom of the file,
and reference it from your entry.

---

## Step 5 — Draft the entry

### Format (match the file exactly)

- Top-level items are a numbered list under `## Missing features todos:`.
- An item with subtasks gets a bold title with a trailing colon:
  `16. **XLSX export formatting:**`
- A one-line item skips the bold: `17. Comparisons between revisions`
- Sub-bullets are `- ` at **4-space** indent, +4 spaces per nesting level.
  Nest 2–3 levels deep; deeper than that means you should have split the item.
- Real paths in backticks: `web/src/lib/totals.js`. Reference file:line when you
  know it.
- Never renumber, reword, reorder, or un-strikethrough existing items. Additive
  edits only.

### Voice

Write in the user's register: terse, direct, imperative, lowercase-leaning,
first-person where it's their intent ("I want…", "I made previously"). No
corporate PM phrasing, no "As a user, I would like to…", no estimates, no
emoji, no bold-everything. **Terse ≠ vague** — the whole point is that this is
more specific than the user's shorthand, just not wordier per sentence.

### Two files, two audiences

You write **both**. `TODO.md` stays scannable; the implementation detail that would
bloat it goes in `docs/specs/<slug>.md`, named for the feature/area (Step 3).

| | `docs/TODO.md` | `docs/specs/<slug>.md` |
|---|---|---|
| audience | Konur, at a glance | the agent that implements it |
| holds | **the ask**, fleshed out into clear subtasks, in his voice | how to build it: files, data model, seams, edge cases, scope |
| budget | title + ~4–8 terse bullets, 2 levels deep | as long as it needs |

### `TODO.md` — the ask only

Title plus subtask bullets: the same thing the user would have written, but
complete and unambiguous. What should happen, where in the app, under what
conditions. Someone who doesn't code should be able to read it and know what
they're getting.

Keep out of `TODO.md`: file paths beyond an occasional orienting one, function
names, seam accounting, data-model wording, edge-case enumerations, and your
assumptions/questions. All of that goes in the spec file.

### `docs/specs/<slug>.md` — the brief

Write a `# <Title>` heading (the feature/area, not the `TODO.md` item number)
with `**Status:** not started` and a `**Brief**` covering, in roughly this
order (skip what genuinely doesn't apply):

1. **What "done" looks like** — the user-visible behavior, concretely enough to
   verify by hand, plus the acceptance checks.
2. **Where it lives / what's already there** — the files and functions to touch
   (cite `path:line` from Step 2), what the current code already does, and the
   existing pattern to copy. State the gap as a diff against what you read, not
   as a wish.
3. **Data model** — any new persisted field, plus whether the change is
   **additive/back-compat** (existing saved projects must still load — this repo
   cares a lot about that).
4. **Subtasks** — dependency-ordered, each small enough to be a single commit,
   with the technical detail the `TODO.md` bullets deliberately omit.
5. **Seams to keep threaded** — from the checklist below.
6. **Edge cases / gotchas** — rotated pages, negative/subtractive shapes,
   multi-page docs, imported-from-Bluebeam docs, empty state, unzoned totals,
   zoom/pan interaction, undo.
7. **Out of scope** — what this item deliberately does *not* cover, so the
   implementer doesn't scope-creep. Note any deferred piece as its own future item.
8. **`Related (not asked for):`** — the adjacent findings from Step 2: real gaps
   you saw in the code that the user didn't ask about. Clearly outside the ask.
9. **`Assumption:`** for anything you decided on the user's behalf, and
   **`Open question:`** for anything still unresolved. Those exact prefixes, so
   they're greppable and obviously not settled fact — `run-todo` treats both as
   blocking.

### Seam checklist for this repo

Walk this list and include the ones that actually apply. Missing a seam here is
the main way a TODO turns into a half-finished feature:

- **Persistence** — `web/src/lib/store.js` (IndexedDB, project-scoped); new
  fields must round-trip through save/load/import/export.
- **Canvas** — `web/src/pages/TakeoffCanvas.jsx` (SVG overlay, normalized
  `verts_norm`, direct-DOM cursor writes — no React state per mousemove).
- **Shared math/geometry** — `web/src/lib/` (`geometry`, `totals.js`,
  `oneclick.ts`, `sheets.ts`, `zone.js`, `curves.js`, …). Anything the canvas
  *and* an exporter both need goes here, once.
- **Hierarchy threading** — schedules → groups → conditions, and zones/breakouts.
  New per-condition data usually has to flow through both.
- **Totals** — `web/src/lib/totals.js` (waste applies in the report only, never
  to live measured numbers).
- **Exports** — CSV / JSON / XLSX / report PDF / marked-set PDF (resumable
  embedded JSON) / Bluebeam PDF+FDF. Say explicitly which ones are in scope.
- **Bluebeam import** — `web/src/lib/bluebeam.js`, if the feature has anything to
  round-trip.
- **MCP** — `mcp/`, so the tool stays fully drivable.
- **Keybinds** — `web/src/lib/keybinds.js` registry (+ auto-generated Help) for
  any new action; every button is supposed to get a shortcut.
- **Settings** — if it's toggleable, it needs a tabbed Settings home.
- **UI conventions** — `data-tip` + `TooltipLayer` (not `title=`), `SelectMenu`
  (not native `<select>`), theme tokens in `web/src/styles/tokens.css`, and
  **never** `window.alert/confirm/prompt` — use `dialog.*` / `setCommitMsg`
  toasts (a test enforces this).
- **Tests** — `web/test/*.test.ts` for anything that's pure math.
- **Docs to sync** — `README.md`, `docs/USER_GUIDE.md`, `docs/CHANGELOG.md`.

### Shape to aim for

`docs/TODO.md` — the ask, nothing else:

```markdown
16. **Per-page legend column presets:**
    - legend column on/off state should be remembered per project — set it once, every new page's legend matches
    - "reset to defaults" on the legend right-click menu
    - a page that already has a legend keeps its own choices; this only seeds new ones
```

`docs/specs/legend-column-presets.md` — everything an implementer needs:

```markdown
# Per-page legend column presets

**Status:** not started

**Brief**

- **done =** legend column on/off state is remembered per project, so a user sets it
  once and every new page's legend matches
- **already there:** `buildLegendRows` in `web/src/lib/legendbox.js:41` already maps
  over a `cols` array, but visibility is hardcoded at the call site and nothing
  persists — so this is a persistence + seeding change, not a rewrite. Follow
  the pattern `legends[]` already uses for its normalized x/y.
- **data model:** add `legend_prefs` to the project doc (additive — absent means
  today's defaults, so old saves keep loading)
- **subtasks:**
    - persist the checkbox state to `legend_prefs` in `store.js` on toggle
    - seed a new page's legend from `legend_prefs` instead of the built-in default
    - "reset to defaults" in the legend right-click menu
- **seams:** marked-set PDF and Bluebeam PDF both draw the legend via
  `drawLegendBox` — they read the same prefs or they'll disagree with the canvas
- **edge cases:** rotated pages (legend stays upright); a Bluebeam import that
  already has a legend stamp
- **out of scope:** per-page overrides of the preset — separate item if we want it
- Related (not asked for): the legend's collapse state isn't persisted either — same
  missing seam, one line next to this
- Assumption: prefs are per project, not global across projects
- Open question: should a collapsed legend still export? (see `## Questions for team:`)
```

Same information as one bloated entry would carry — but the file Konur reads went
from 17 lines to 3, and the brief lives in a file named for what it is, not for
where it sits in a list that's going to get renumbered.

---

## Step 6 — Write both files

In `docs/TODO.md`:

- Insert as the **next sequential number** at the end of the numbered list under
  `## Missing features todos:` — i.e. immediately **before** the `## Questions for
  team:` section, preserving the blank lines around it.
- Use `Edit` (not `Write`) so you can't clobber the file.
- If the user said it blocks beta, **also** add a matching one-line bullet to the
  `# Major TODOs for beta:` list at the top.
- If you're expanding an existing item instead, edit that item in place and leave
  its number alone.
- One prompt → one item. If the prompt is genuinely two unrelated features, write
  two numbered items and report both.

In `docs/specs/`:

- **Matching file found in Step 3** — `Edit` inside it: extend `Brief` with the
  new ask, or add a dated note if the file's `Status` is already `done` and this
  is a genuine follow-up. Don't create a second file for the same feature/area.
- **Nothing matched** — `Write` a new `docs/specs/<slug>.md`, following the shape
  in [`docs/specs/README.md`](../../../docs/specs/README.md) (create that file
  too, copied from this repo's, if the directory doesn't exist yet).
- Don't cross-link every item back from `TODO.md` to the spec file's contents —
  the shared vocabulary (the slug, the feature name) *is* the link. (`run-todo`
  adds a `[spec](specs/<slug>.md)` link only on the `DONE:` line.)

---

## Step 7 — Report where to read it (always)

Get the real line number, then close with it:

```bash
grep -n '^16\.' docs/TODO.md
```

Your final message must include, in this order:

1. **The pointer, first**, as a clickable markdown link with the line anchor —
   `TODO.md` is the one they should read; mention the spec file second, as
   optional:
   > Written up as item **16** in [docs/TODO.md:92](docs/TODO.md#L92) — read it over before I start and tell me what to change. The full brief is in [docs/specs/legend-column-presets.md](docs/specs/legend-column-presets.md) if you want it.
2. A short summary — 3–6 bullets naming the subtask headings, so the user knows
   what's in there without opening the file.
3. **What reading the code changed** — one or two lines, when it applies: part of
   the ask already exists, the gap was narrower or wider than the prompt implied,
   or the obvious-looking file wasn't the right one. This is the part the user
   can't get from their own shorthand.
4. **Adjacent findings, explicitly.** List the `Related (not asked for):` bullets
   and ask whether to pull any into scope, split them into their own items, or
   drop them. Don't bury these in the file — they're the main reason reading the
   code was worth it.
5. Any `Assumption:` / `Open question:` bullets you left in, plus anything you
   added to `## Questions for team:`.
6. That you have **not** started implementing, and an offer to.

Never end this skill without the file pointer. That's the whole handoff.
