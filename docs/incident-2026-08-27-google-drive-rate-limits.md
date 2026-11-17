# Incident: Google Drive/Docs rate-limit failures in slack-note-updater and takeo-reviewer

**Date:** 2026-08-27
**Bots affected:** `slack-note-updater` (Slack `#feedback!` logging), `takeo-reviewer` (AI job review pipeline)
**Status:** Fixed and deployed to both.

## What went wrong

Heroku logs for the `slack-note-updater` worker showed:

```
Feedback handling failed: <HttpError 403 when requesting
https://www.googleapis.com/drive/v3/files?q=name+contains+%2767202+%7C%27...
returned "User rate limit exceeded.". Details: "[{'message': 'User rate
limit exceeded.', 'domain': 'usageLimits', 'reason': 'userRateLimitExceeded'}]">
```

A customer's `#feedback! #67202!` message hit a transient Google Drive API rate limit while the bot was looking up the job's Google Doc. The bot had no retry logic for this, so the error propagated straight up, the whole handler aborted, and the customer's feedback was silently dropped (they only saw `:x: Could not process feedback for job #67202.`).

## Investigation detour: the bot's source wasn't where it looked like it should be

This session started in the `slack_note_updater` git repo (Heroku app `slack-help-bot`), which is documented as also hosting the newer Help Bot (`app2.py`). Its `Procfile` still declares a `worker: python app.py` process, and `app.py` was originally the old note-updater bot.

Digging in, `app.py` did not exist anywhere in that repo — not on disk, not at `HEAD`, not in any commit reachable from `main`/`origin/main`/`heroku/main`. It had been unintentionally deleted (344 lines, unmentioned) in commit `213a7c5` ("Link Sources to publicly hosted skill HTML", 2026-05-22) — a commit that was really about the Help Bot. `git reflog --all` confirmed every push since then, from this machine, kept `origin/main` and `heroku/main` identical to local `main`. So the Heroku app `slack-help-bot` has had no working `app.py` in its deployed slug since that date — its `worker` dyno would be crash-looping if scaled up, not doing what the logs showed.

The user confirmed the logs were actually from a **separate Heroku app**, `slack-note-updater` (https://dashboard.heroku.com/apps/slack-note-updater) — an independent deployment, unrelated to `slack-help-bot`, never sourced from the `slack_note_updater` git repo's history.

This session had no cached Heroku credentials, so the user ran `heroku login` locally first. Then the real source was pulled down with:

```
heroku git:clone -a slack-note-updater slack-note-updater-prod
```

## Root cause 1: slack-note-updater

None of the 10 Google Drive/Docs `.execute()` calls in `app.py` passed `num_retries`. `google-api-python-client`'s `.execute(num_retries=N)` already knows how to retry exactly this class of error — `403` with reason `rateLimitExceeded`/`userRateLimitExceeded`, `429`, and `5xx` — with exponential backoff, but it was never enabled.

Separately, `get_or_create_weekly_feedback_doc()` re-ran a full Drive search **on every single feedback message and every reply in an active feedback thread**, for the entire week, even though the weekly doc only changes once a week. That's avoidable Drive traffic stacking up right when a burst of feedback/replies is most likely to trip the per-user quota.

### Fix (commit `e718b74`, Heroku release v27)

- Added `num_retries=5` to all 10 `.execute()` calls on the Drive/Docs API.
- Added an in-memory cache (`_weekly_feedback_doc_cache`, keyed by the week's doc title) so `get_or_create_weekly_feedback_doc()` hits Drive once per week instead of once per message/reply.

## Root cause 2: takeo-reviewer

The user asked to check whether the AI Reviewer Bot (`takeo-reviewer`) had the same problem. It wasn't visible under the `takeoffmonkey-dev` Heroku team at first (checked all 14 apps, no match). It turned out to have been hosted on Tommy's personal account and had just been migrated to the team account as `takeo-reviewer` (https://dashboard.heroku.com/apps/takeo-reviewer). Cloned locally the same way:

```
heroku git:clone -a takeo-reviewer takeo-reviewer-prod
```

This codebase (`reviewer/drive_client.py`) already had hand-rolled retry loops (`_query_files`, `_docs_get_with_retry`), but they only matched HTTP status `500`/`503` — never `403`/`429` — so a transient rate limit still wasn't retried. On top of that:

- Two raw `self.service.files().get(...).execute()` calls in `find_job_folder` (marker-file path and fuzzy-fallback path) had no retry at all.
- `customer_folder_from_job`'s `files().get()` call had no retry either, and its `except Exception` swallowed the error and returned `None` silently — a rate limit there would quietly skip loading the customer's `_CLAUDE_INSTRUCTIONS_`/Requirements doc for that review, no error surfaced.
- `doc_builder.create_review_doc` (used by the live pipeline) creates the review doc and does a final content `batchUpdate` with zero retry on either call.

### Fix (commit `6107ee4`, Heroku release v109)

Added `num_retries=5` to all 7 live-path `.execute()` calls across `reviewer/drive_client.py` and `reviewer/doc_builder.py`. Deliberately left untouched:

- `reviewer/milestone2/` and `reviewer/milestone3/` — old snapshots of `drive_client.py`/`doc_builder.py`, confirmed via grep to not be imported anywhere from `app.py`/`orchestrator.py` (dead code).
- `test_connections.py` and `scripts/audit_requirements_docs.py` — offline diagnostic scripts, not part of the live request path.

## Lessons / follow-ups

- **Prefer the client library's built-in retry over a hand-rolled status-code allowlist.** takeo-reviewer's custom retry loops were a reasonable idea but under-scoped (500/503 only); `google-api-python-client`'s own `num_retries` already retries the exact right set of transient reasons and needs no allowlist to maintain.
- **The `slack_note_updater` repo's `Procfile` still has a dead `worker: python app.py` line** with no backing file — worth removing once the Help Bot/old-bot consolidation actually happens, so it stops looking like it's the old bot's source.
- **Bots hosted on personal accounts are hard to find and fix.** `takeo-reviewer` wasn't discoverable under the team's Heroku account until it was migrated — worth auditing for any other bots still living outside `takeoffmonkey-dev`.
- Both fixes are narrowly scoped to adding retries (and, for slack-note-updater, caching one redundant lookup) — no behavior changes beyond making transient Google API errors survivable.
