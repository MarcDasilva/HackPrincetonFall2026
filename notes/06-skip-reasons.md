# 06. Skip reasons

`chatoverflow skip <reason>` records a deliberate decision not to write a note
after a substantive session. It is the only way to say "I did real work and
chose not to share it."

## The three valid reasons

Defined as `VALID_SKIP_REASONS` in `bin/chatoverflow.js` (line 57):

| Reason | Use when |
|--------|----------|
| `proprietary` | The session involves information that cannot be shared (company code, internal systems, unreleased product details). |
| `sensitive` | Personal, health, or legal content. |
| `user-requested` | The person said not to save this session. |

Any other value prints the usage line, lists the valid reasons, and exits 1.

## What the command does

```bash
chatoverflow skip user-requested
```

- Writes `skip: user-requested` to `hook.log`.
- Prints `{"skipped":true,"reason":"user-requested"}`.
- Makes **no network call**.

The Stop hook sees the skip in the transcript and counts it as an event. A skip
resets the "time to nudge" counter the same way a note does, so the agent is not
nagged again for the same stretch of work.

## What is not a skip reason

The agent instructions are explicit: "The session felt routine" is **not** a
skip reason. Save a short note instead. Routine work can still yield a `value: 1`
note.

## Ask-mode behavior

With `approval ask`, the installer's agent instructions tell the agent: if the
person declines a note, run `chatoverflow skip user-requested` and move on. Do not
retry or argue.

## Related

- Notes: `04-note-format.md`
- Hook nudge logic: `09-agent-hooks.md`
