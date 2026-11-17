---
name: fix-merge-conflicts
description: Safely pulls the latest remote changes into the local branch. Stashes or commits any local work, pulls/rebases, resolves conflicts intelligently, restores local work, then pushes if the branch is ahead of origin.
argument-hint: [optional: "push" to auto-push after merge, "stash" to force-stash even if work could be committed]
allowed-tools: Bash Read Glob Grep Edit Write Agent
---

# Fix Merge Conflicts — Pull, Resolve, Restore, Push

You are a merge-conflict resolution skill. Your job is to safely integrate the
latest remote changes into the current branch without losing any local work.

## Overall flow

```
1. Snapshot local state (status + diff)
2. Preserve local work (stash or commit)
3. Pull remote changes (rebase preferred)
4. Resolve any conflicts intelligently
5. Restore local work (stash pop)
6. Push if branch is ahead of origin (and "push" arg given or branch was already ahead)
7. Report clearly
```

---

## Step 1 — Snapshot local state

Run these to understand what we're dealing with:

```bash
git status
git log --oneline -5
git log --oneline origin/$(git rev-parse --abbrev-ref HEAD)..HEAD   # local commits ahead of remote
```

Classify the workspace into one of these states:

| State | Condition |
|-------|-----------|
| **Clean** | No modified/staged/untracked files, branch is behind origin |
| **Dirty-only** | Modified/untracked files, no unpushed local commits |
| **Ahead-only** | Unpushed local commits, working tree clean |
| **Ahead+Dirty** | Both unpushed commits AND modified files |
| **Diverged** | Local commits AND remote commits both exist (non-fast-forward) |

---

## Step 2 — Preserve local work

Choose the preservation strategy based on workspace state:

### If state is Clean
Nothing to preserve. Skip to Step 3.

### If state is Dirty-only or Ahead+Dirty (has uncommitted changes)
Always stash first — this is the safest option regardless of `$ARGUMENTS`:

```bash
git stash push -m "fix-merge-conflicts auto-stash $(date +%Y%m%dT%H%M%S)"
```

Save the stash ref output — you'll need it to verify the pop in Step 5.

### If state is Ahead-only (unpushed commit, clean tree)
No stash needed. The rebase in Step 3 will replay the commit cleanly.

---

## Step 3 — Pull remote changes

Always use rebase to keep history linear:

```bash
git config pull.rebase true   # set repo default (non-destructive)
git pull --rebase
```

**If git complains about divergent branches** and refuses without a strategy:
```bash
git pull --rebase origin $(git rev-parse --abbrev-ref HEAD)
```

Capture the full output. If the pull exits 0 with no conflict markers, skip to Step 5.

If the pull exits non-zero, conflicts exist. Proceed to Step 4.

---

## Step 4 — Resolve conflicts

### 4a. Find all conflicted files

```bash
git diff --name-only --diff-filter=U
```

For each conflicted file, read its full contents to see the conflict markers:

```
<<<<<<< HEAD          ← your local version (what you had)
...local content...
=======
...remote content...
>>>>>>> <commit hash>  ← remote version (what's coming in)
```

### 4b. Resolution strategy per file type

Apply the right strategy for each file:

#### `.env` / `.env.*` (environment files)
These almost always conflict because both sides add new keys.
**Strategy: Union merge** — keep ALL keys from BOTH sides. Never drop a key.

```
Resolution rule:
- Keep every unique key from HEAD (local)
- Keep every unique key from remote
- If the same key appears with different values, prefer the LOCAL value
  (it's likely the developer's active credentials)
- Remove conflict markers completely
- Ensure exactly one newline at end of file
```

#### `.env.example` / `*.example` (template files)
**Strategy: Union merge** — include all placeholder entries from both sides.
Local additions (new keys) should appear after remote additions.

#### `package.json` / `package-lock.json`
**Strategy: Remote wins for lock file** — the remote lockfile reflects the
correct dependency tree after `npm install` on that branch.
For `package.json`, do a manual line-by-line union of `dependencies` and
`devDependencies`.

After resolving, run `npm install` to reconcile the lockfile:
```bash
npm install
```

#### `*.tsx` / `*.ts` / `*.js` / source files
**Strategy: Inspect and merge manually**
- Read the local change (HEAD block) and remote change (remote block)
- Understand the intent of each side
- If they edit different parts of the same function: keep both
- If they're logically equivalent changes: keep remote (it's newer)
- If they conflict semantically: prefer LOCAL (the developer was working on it)
  and add a `// TODO: reconcile with remote change` comment above it

#### `*.md` / documentation files
**Strategy: Union merge** — append or interleave sections from both sides.
Never silently drop a section.

#### `.expo/` / `dist/` / `*.lock` files tracked in git
**Strategy: Remote wins** — generated/lock files should match the remote tree.
Just checkout the remote version:
```bash
git checkout --theirs -- <file>
```

### 4c. Mark conflicts as resolved

After editing each file to remove `<<<<<<<`, `=======`, `>>>>>>>` markers:

```bash
git add <file>
```

Verify no remaining conflict markers in source files:
```bash
grep -rn "^<<<<<<< " . \
  --include="*.ts" --include="*.tsx" --include="*.js" \
  --include="*.json" --include="*.md" --include=".env*"
```

This should return no results before continuing.

### 4d. Continue the rebase

```bash
GIT_EDITOR=true git rebase --continue
```

If git says "nothing to commit" for a particular step (the commit was a
pure duplicate of the remote), skip it:

```bash
git rebase --skip
```

If the rebase becomes hopelessly tangled after 3+ skip/continue cycles, abort
and fall back to a merge:

```bash
git rebase --abort
git merge origin/$(git rev-parse --abbrev-ref HEAD) --no-edit
```

Then re-resolve conflicts using the same Step 4b strategies above.

---

## Step 5 — Restore local work (stash pop)

If you stashed in Step 2:

```bash
git stash pop
```

If this also causes conflicts (the stashed changes conflict with the freshly-pulled
code), resolve them using the same Step 4b strategies — they'll be in the working
tree (not staged), so edit the files and verify manually.

After restoring, verify the working tree is sensible:
```bash
git status
git diff --stat
```

---

## Step 6 — Push (conditional)

Push only if:
1. The `$ARGUMENTS` contains "push", **OR**
2. The branch was already ahead of origin BEFORE this skill ran (meaning the user
   had unpushed commits they presumably intended to push).

```bash
git push
```

If push is rejected (non-fast-forward again, meaning someone pushed while we
were resolving), repeat from Step 3. Cap at 2 retry attempts before stopping
and reporting.

---

## Step 7 — Report

Print a clear summary:

```
## Merge-Conflicts Results

**Branch:** main
**Before:** local was X commits behind, Y files modified
**After:**  branch is up to date with origin/main

### Files resolved
- `.env`         — union merge (kept local credentials + 2 new remote keys)
- `.env.example` — union merge (added TWILIO_API_KEY from remote)
- `app/login.tsx` — auto-merged cleanly (no conflict)

### Local work restored
- Stash `stash@{0}` popped cleanly
- 1 file still modified: `app/login.tsx` (your uncommitted edits are intact)

### Push status
- Pushed  ✓   (or: Not pushed — run `git push` when ready)
```

---

## Safety rules

- **Never run `git push --force`** or any destructive force-push. If push is
  rejected, always pull again.
- **Never drop local changes silently.** If a stash pop fails, stop and report
  exactly what conflicted so the user can decide.
- **Never reset or clean uncommitted work** without explicit user confirmation.
- **Prefer union merges for config files** — it is almost always wrong to drop
  a key from `.env` or `.env.example`.
- **Verify no conflict markers remain** before marking resolution complete.
- **If in doubt about a source-file conflict**, leave the local version intact,
  add a `// TODO: review merge` comment, and flag it in the report.

---

## Common failure modes and fixes

| Symptom | Fix |
|---------|-----|
| `Need to specify how to reconcile divergent branches` | Run `git config pull.rebase true` then pull again |
| `error: Terminal is dumb, but EDITOR unset` | Use `GIT_EDITOR=true git rebase --continue` |
| `.expo` path ignored by .gitignore during `git add` | Run `git checkout .expo/...` to discard, then continue |
| `Updated 0 paths from the index` on `git checkout` | The file doesn't exist in that tree; skip it |
| Rebase loops with "nothing to commit" on every step | Use `git rebase --skip` for each empty step |
| Push still rejected after pull | Another push landed during resolution; loop back to Step 3 |
