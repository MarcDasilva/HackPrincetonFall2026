# Sandboxes

Sandboxes are backends that run the agent's work in an isolated environment. They give the agent the standard filesystem tools plus **`execute`**, a shell command tool. The sandbox is passed as `backend=`.

## Why use one

- Isolate agent-generated code, file access, and shell commands from your host system, credentials, and network.
- Common uses: coding agents (shell, git, cloning repos, Docker-in-Docker for builds and tests) and data analysis agents (installing libraries, running calculations, producing outputs such as presentations).

## Providers

| Provider | Class | Package |
|---|---|---|
| LangSmith | `LangSmithSandbox` (`deepagents.backends.langsmith`) | `langsmith` |
| AgentCore | `AgentCoreSandbox` | `langchain-agentcore-codeinterpreter` |
| Databricks | `DatabricksSandbox` | `databricks-langchain[deepagents]>=0.22.0` |
| Daytona | `DaytonaSandbox` | `langchain-daytona` |
| E2B | `E2BSandbox` | `langchain-e2b` |
| Modal | `ModalSandbox` | `langchain-modal` |
| NVIDIA OpenShell | `OpenShellSandbox` | `langchain-nvidia-openshell` |
| Runloop | `RunloopSandbox` | `langchain-runloop` |
| Vercel | `VercelSandbox` | `langchain-vercel-sandbox` |

Provider setup, authentication, and lifecycle details are in the sandbox integrations docs.

## Basic usage pattern

1. Install the provider package.
2. Create a sandbox with the provider's SDK.
3. Wrap it in the provider's backend class.
4. Pass the backend to `create_deep_agent`, with a model and optional system prompt.
5. Invoke the agent.
6. Shut the sandbox down in a `finally` block.

Teardown calls by provider:

| Provider | Teardown |
|---|---|
| LangSmith | `client.delete_sandbox(name)` |
| Daytona | `sandbox.stop()` |
| E2B | `sandbox.kill()` |
| Modal | `sandbox.terminate()` |
| Runloop | `devbox.shutdown()` |
| Vercel | `sandbox.stop()` |
| AgentCore | `interpreter.stop()` |
| OpenShell | Context manager with `delete_on_exit=True` |

## Lifecycle patterns

### Thread-scoped (most common)

- Each conversation gets its own sandbox.
- The first run creates it. Later turns on the same thread reuse it.
- Map the thread ID to a sandbox name, for example `thread-{thread_id}`, and look up existing sandboxes before creating new ones.
- Set an **idle TTL** (the example uses 3600 seconds) so idle environments are cleaned up.
- Sandbox IDs are stored on thread metadata.

### Assistant-scoped

- All threads on one assistant share a sandbox.
- Files, packages, and cloned repos persist across conversations.
- Name it from the assistant ID, for example `assistant-{assistant_id}`.
- The docs warn that in-sandbox state accumulates. Use a TTL, periodic snapshots, or cleanup logic.

### General rules

- Sandboxes cost money until shut down. Tear them down when they're no longer needed.
- Create sandboxes in **async graph factories** that look up or create them by name. The production guide says graph factories that provision sandboxes or MCP connections should be async.

## Integration patterns

### Sandbox as tool (used in most examples)

- The agent runs on your machine or server and calls sandbox tools (`execute`, `read_file`, `write_file`), which hit the provider's APIs.
- Pros: instant agent code updates; API keys stay outside the sandbox; sandbox failures don't lose agent state; parallel sandboxes are possible; you pay only for execution time.
- Cons: network latency on each execution.

### Agent in sandbox

- The agent runs inside the sandbox, usually from a custom image with `deepagents-code` installed. You talk to it over the network.
- Pros: closely mirrors local development.
- Cons: API keys must live inside the sandbox; image rebuilds for updates; you need a WebSocket or HTTP communication layer.

Guidance from the docs: use agent-in-sandbox when the provider's SDK handles communication and you want production to mirror development. Use sandbox-as-tool to iterate quickly, keep keys outside, or separate concerns.

## How sandboxes work internally

### `execute` is the only required method

- A provider must implement only `execute()`, which runs a shell command and returns its output.
- `BaseSandbox` builds the other file operations (`read`, `write`, `edit`, `delete`, `ls`, `glob`, `grep`) on top of `execute()`, by running scripts inside the sandbox.
- Adding a provider means implementing `execute()`.

### The `execute` tool is conditional

On each model call, the harness checks whether the backend implements `SandboxBackendProtocol`. If not, the `execute` tool is filtered out and the agent never sees it.

When the agent calls `execute`, it provides a `command` string and gets back combined stdout/stderr, the exit code, and a truncation notice if the output is too large.

Direct calls to `backend.execute(...)` return an object with `.output`. The output ends with a status line. For example, exit code 127 means the command wasn't found.

Very large output is saved to a file, and the agent is told to read it incrementally with `read_file`, to avoid overflowing its context.

### Two planes of file access

| Plane | Who calls it | Mechanism |
|---|---|---|
| Agent tools (`read_file`, `write_file`, `edit_file`, `delete`, `ls`, `glob`, `grep`, `execute`) | The LLM during a run | Routed through `execute()` inside the sandbox |
| File transfer (`upload_files()`, `download_files()`) | Your application code | Provider's native transfer APIs, not shell commands |

File transfer details:

- `upload_files()` seeds source code, config, data, or dependencies before the run. Paths are absolute, contents are `bytes`.
- `download_files()` retrieves artifacts after the run. Each result has `path`, `content` (bytes, or `None` on failure), and `error`.

## Security model

### What sandboxes protect

- The host filesystem, environment variables, and processes.

### What sandboxes do NOT protect

- **Context injection**: an attacker who controls part of the input can direct the agent to run any command inside the sandbox.
- **Network exfiltration**: unless network access is blocked, data can leave over HTTP or DNS. Some providers support blocking it (for example, `blockNetwork: true` on Modal).

### Secrets

- **Never put secrets inside a sandbox.** That includes environment variables, mounted files, and the `secrets` option, even with short-lived or scoped credentials. If the agent can read it, an attacker who injects instructions can too.
- Recommended approach: define tools that run on your host, handle authentication there, and never expose credentials to the agent.
- Some providers offer **network proxies** that attach credentials to outgoing requests, so the agent never sees the secret. Support is not yet widespread.
- If you must inject secrets (not recommended):
  - Require human approval for all tool calls ([16-human-in-the-loop.md](16-human-in-the-loop.md)).
  - Block or restrict sandbox network access.
  - Use the narrowest scope and shortest lifetime.
  - Monitor outbound traffic.
  - Even then, a determined injection attack can get past output filtering and review.

### General practices

- Review sandbox outputs before acting on them.
- Block network access when it isn't needed.
- Use middleware to filter or redact sensitive patterns in tool outputs.
- Treat everything the sandbox produces as untrusted input.

## Deep Agents Code and sandboxes

Deep Agents Code has built-in sandbox support through `--sandbox`, with `--sandbox-id` and `--sandbox-setup` options.

## LangSmith sandbox extras

The LangSmith sandbox includes an auth proxy, so end users can call third-party APIs without per-user credential provisioning. The auth proxy injects headers into outbound requests so raw keys never enter the sandbox (see [19-production-and-deployment.md](19-production-and-deployment.md)).

## Interpreters (not sandboxes)

An **interpreter** is a lighter option, distinct from a sandbox:

- `CodeInterpreterMiddleware` from `langchain_quickjs` adds an `eval` tool.
- It runs JavaScript in a scoped QuickJS runtime.
- It has **no shell, package install, or filesystem/network access**.
- Use for loops, batching, deterministic transforms, and programmatic tool calling.
- It is also how dynamic subagent dispatch works ([10-subagents.md](10-subagents.md)).

Rule of thumb from the docs: sandbox `execute` when you need a real environment with installs and tests; interpreter `eval` when you only need to orchestrate or transform data.
