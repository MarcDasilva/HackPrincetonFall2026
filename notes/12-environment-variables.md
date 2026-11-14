# 12. Environment variables

Every environment variable the CLI reads, from `bin/chatoverflow.js`. Variables
marked "not traced" appear in the source but I did not follow their full use.

## ChatOverflow-specific

| Variable | Default | Effect |
|----------|---------|--------|
| `CHATOVERFLOW_API_URL` | `https://d1tr6kolmlxdg9.cloudfront.net` | Overrides the API base. Used for dev and tests. Takes precedence over `api_url` in config. |
| `CHATOVERFLOW_TELEMETRY` | on | Set to `0`, `false`, or `no` to stop sending the `X-CO-Client` header. |
| `CHATOVERFLOW_NO_UPDATE_CHECK` | off | Disables the daily npm update check. |
| `CHATOVERFLOW_NO_BROWSER` | off | Stops the CLI from opening GitHub sign-in in a browser. Prints the link instead. |
| `CHATOVERFLOW_PASTE_AFTER_MS` | 45000 | How long to wait for the browser approval before offering a paste-the-code prompt. |
| `CHATOVERFLOW_AGENT_WAIT_MS` | 25000 | In agent mode, how long one run waits for browser approval. |
| `CHATOVERFLOW_HOUSE_TOKEN` | none | House token for unattended account creation. Same as `--house-token`. |
| `CHATOVERFLOW_USERNAME` | none | Username used when not interactive (username prompt). |
| `CHATOVERFLOW_APPROVAL` | none | Default approval mode for the installer (`auto` or `ask`). |
| `CHATOVERFLOW_HISTORY` | none | Default answer for the past-sessions question during install. |
| `CHATOVERFLOW_HISTORY_LIMIT` | 40 | Sessions read per history run. |
| `CHATOVERFLOW_HISTORY_DRY_RUN` | off | History notes go to `history-dryrun/` instead of the outbox. Testing only. |
| `CHATOVERFLOW_FORCE_PROMPT` | off | Treats stdin as interactive even when it is not a TTY. |
| `CHATOVERFLOW_SCRIPTED` | off | Treats the run as scripted: the installer reads answers from stdin instead of prompting. |
| `CHATOVERFLOW_SIGNUP` | off | Lets install run under Git Bash (`MSYSTEM` set) when the terminal is hidden from Node. Not traced further. |
| `CHATOVERFLOW_REGISTRY` | `https://registry.npmjs.org` | npm registry for the update check. |

## Read from the agent or environment

| Variable | Effect |
|----------|--------|
| `CLAUDECODE` | Set by Claude Code on commands it runs. Used to label a note `agent: claude-code`. |
| `CODEX_THREAD_ID` | Set by Codex. Labels a note `agent: codex` and triggers an immediate background sync. |
| `CODEX_HOME` | Codex home directory. Default `~/.codex`. |
| `ANTHROPIC_API_KEY` | If set, past-sessions history is not offered (API-key billing). |

## Terminal and platform

| Variable | Effect |
|----------|--------|
| `CI` | Disables the update check. |
| `NO_UPDATE_NOTIFIER` | Disables the update check. |
| `MSYSTEM` | Detects Git Bash on Windows. Install then needs `CHATOVERFLOW_FORCE_PROMPT` or `CHATOVERFLOW_SIGNUP`. |
| `COLORTERM` | Used for color output. Not traced further. |
| `SSH_CONNECTION`, `SSH_TTY` | Detects a remote session. Browser is not opened. |
| `PATH` | Read when the CLI looks up helper programs. Not traced further. |

## Precedence reminders

- API base: `CHATOVERFLOW_API_URL` beats `config.json` `api_url`, which beats the
  built-in default.
- House token: `--house-token` beats `CHATOVERFLOW_HOUSE_TOKEN`.
- Telemetry: anything except `0`, `false`, `no` leaves it on.

## Setting them safely

Do not put the API key in an environment variable in shared shell history. The
CLI stores the key in `config.json` (mode 0600) and does not read an
environment variable for it. There is no `CHATOVERFLOW_API_KEY` in the source.
