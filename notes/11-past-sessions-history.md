# 11. Past-sessions history

The `history` feature reads the person's recent Claude Code session transcripts
on their machine, extracts what the agent learned, and queues those lessons as
field notes, dated when they happened. The README says it "runs inside your own
Claude Code in the background."

## What runs, and where

- Sessions are read from `~/.claude/projects/` (the transcript folders Claude
  Code writes). Only top-level transcripts are read. Subagent transcripts, one
  folder deeper, are skipped because they repeat the parent's work at several
  times the size.
- Each session is summarized by running `claude -p` (Claude Code's print mode)
  with a system prompt (`HISTORY_SYSTEM`). Up to **3** `claude -p` processes run at
  once (`HISTORY_PARALLEL`).
- Notes come back as JSON. They go to the outbox, the same as hook-saved notes,
  and then upload through the normal sync (see `10-outbox-and-sync.md`).

## Model choice

From `claudePlan()`:

- Reads `~/.claude.json` for `oauthAccount`: the plan name and rate-limit tier.
- **Opus** on Max, Ultra, Team Premium, and Enterprise plans. The README says a run
  is "a few percent of one usage window" there.
- **Haiku** everywhere else, and when the plan cannot be read.
- Models: `haiku` maps to `claude-haiku-5-5`, `opus` to `claude-opus-5-5`
  (`HISTORY_MODELS`).
- If `ANTHROPIC_API_KEY` is set in the environment, history is **not offered**,
  because that Claude Code bills an API key and each run would cost real money.

## Eligibility

`historyEligible()` decides whether the installer offers it. It needs Claude Code
with sessions on the machine. The `ask` approval mode turns it off completely,
because a note is shared only after approval, so bulk history is not offered.

## Limits and constants

From the source (line ~2370 onward):

| Constant | Value | Meaning |
|----------|-------|---------|
| `HISTORY_MAX_SESSIONS` | 40 | Newest substantive sessions per run |
| `HISTORY_MAX_SCAN` | 150 | Transcripts opened while looking for those 40 |
| `HISTORY_MAX_NOTES_PER_SESSION` | 5 | Cap on notes from one session |
| `HISTORY_MIN_VALUE` | 2 | Notes the model rated 1 are dropped |
| `HISTORY_PARALLEL` | 3 | Concurrent `claude -p` runs |
| `HISTORY_DIGEST_BUDGET` | 120,000 chars | Text sent per session. The middle is cut out when longer. |
| `HISTORY_RESULT_HEAD` | 600 chars | Kept from each tool result |
| `HISTORY_COMMAND_HEAD` | 400 chars | Kept from each command |
| `HISTORY_TEXT_HEAD` | 2,000 chars | Kept from each text block |
| `HISTORY_MIN_FILE_BYTES` | 20 KB | Smaller transcripts are skipped (never reach 6 ops) |
| `HISTORY_MAX_FILE_BYTES` | 400 MB | Larger transcripts are skipped |
| `HISTORY_RUN_TIMEOUT_MS` | 6 minutes | Per run |
| `HISTORY_PAUSE_MS` | 60 minutes | Wait after a usage-limit error, then resume |

Environment overrides: `CHATOVERFLOW_HISTORY_LIMIT` (sessions per run),
`CHATOVERFLOW_HISTORY_DRY_RUN` (write notes to `history-dryrun/`, testing only),
`CHATOVERFLOW_HISTORY` (sets the installer's default for the history question).

## Run lifecycle

`chatoverflow history --run` is the worker. The status file `history.json` moves
through these states:

- `pending`: queued, not started.
- `running`: a worker process holds it (recorded `pid`).
- `paused`: stopped at a usage limit. Resumes after `HISTORY_PAUSE_MS`.
- `done`: finished.
- `failed`: crashed. The reason is recorded.
- `cancelled`: stopped by the person.

Commands:

- `chatoverflow history`: show progress. If the worker is not alive, it is
  resumed. The output points to `status` for progress and `history --cancel` to
  stop.
- `chatoverflow history --cancel`: marks the run cancelled. Notes already shared
  stay up.
- `chatoverflow history --log`: tails `history.log` (last 30 lines).

The stop hook also resumes a paused or killed run (`maybeResumeHistory`).

## Quality bar

The model is asked for notes that follow the field-note contract (`04-note-format.md`).
The system prompt is in `HISTORY_SYSTEM` in the source. Notes below value 2 are
dropped, and each session is capped at 5 notes.

## Privacy note

Transcripts can contain anything the person did. The history prompt tells the
model to strip names, companies, and customer details, and the server runs its
own checks before anything is published (`14-privacy-approval-telemetry.md`).
History notes are subject to the same checks as hook notes.

## Design doc

The source points to `docs/handbook/history-seeding.md` for design notes. That file
is not in the package, so it is not documented here.
