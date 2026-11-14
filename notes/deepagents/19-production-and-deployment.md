# Production and Deployment

The "Going to production" guide and the overview describe two deployment modes, the Agent Server, and the multi-tenancy, security, and observability pieces.

## Two ways to run

1. **Managed Deep Agents**: LangSmith runs the harness, Agent Server, sandboxes, and schedules. Recommended for production in the guide. Public beta on LangSmith Cloud and Bring Your Own Cloud (BYOC). BYOC requires Managed Deep Agents CLI and SDK **v0.10 or later**. You author the agent as a project of files rather than compiling it yourself.
2. **Self-hosted SDK**: run `create_deep_agent` in your own process or container, or run a custom Agent Server. Use `langgraph build` to produce a standalone Docker image.

Choose the SDK path when you need a custom backend, store, or checkpointer, or you want to configure the Agent Server yourself.

## Custom LangSmith Agent Server

For custom application code, custom routes, and advanced auth. It provides:

- threads, runs, a store, and a checkpointer,
- authentication and authorization,
- webhooks and cron jobs,
- observability,
- exposure through MCP or A2A.

`langgraph.json` has three key fields:

- `dependencies`: packages to install.
- `graphs`: maps graph IDs to code locations.
- `env`: path to a `.env` file, set at build time.

## Production checklist (from the guide)

- Choose a deployment path: Managed (recommended) or a custom LangSmith Agent Server.
- Pass **two run-level parameters** on every invocation:
  - a stable `thread_id` for conversation continuity,
  - a `context` object for per-run data such as user ID or feature flags.
- Enforce multi-tenancy with custom auth handlers that tag resource ownership and filter access.
- Scope memory deliberately. User scope is the default. Assistant and organization scopes need stricter write controls.
- Use async throughout: async tools, async middleware hooks (the `a`-prefixed variants), and async graph factories for sandbox lifecycle.
- Pick the execution environment: filesystem backends for file-only work, sandboxes when code execution is needed.
- Keep secrets out of sandboxes.
- Apply guardrails: permissions, fault tolerance, PII handling.
- Configure the frontend for reconnection and high recursion limits.
- Monitor with tracing.

## Invocation and threads

- `thread_id` scopes message history and checkpoints. A new ID starts a fresh conversation.
- `context` carries per-run data, read through `runtime.context`. Define it with `context_schema`.
- The two are independent. Pass either or both.
- The LangGraph SDK manages threads. Create a thread, then pass its ID to each run.

## Multi-tenancy and security

### Three auth layers

1. **End-user auth**: verifying who each user is, through custom authentication.
2. **Agent-acting-as-user auth**: credentials the agent uses on the user's behalf.
3. **Team RBAC**: workspace permissions.

### Authorization handlers

- Tag resources with owner metadata.
- Return filters so users see only their own resources.
- Deny unauthorized operations with HTTP 403.

### Workspace roles

- **Admin**: full permissions, including settings and members.
- **Editor**: create and modify resources, but cannot delete runs or manage members.
- **Viewer**: read-only.
- Custom roles are on Enterprise plans.

### End-user credentials

- **Agent Auth**: managed OAuth 2.0. The agent interrupts for user consent on first use. Tokens are then stored and refreshed automatically.
- **Sandbox auth proxy**: injects authentication headers into outbound sandbox requests, so raw keys never enter the sandbox.
- **Workspace secrets**: shared keys (such as an organization's LLM provider key) available as environment variables at runtime.

### Prompt injection

Shared memory (assistant, user, or organization scope) can carry injected instructions if one user can write to memory another user reads. Make organization-wide policies read-only for the agent. Enforce that with permissions or backend policy hooks.

## Durability

- Deep Agents run on LangGraph, which checkpoints state at each step.
- Interrupted runs resume from the last checkpoint without reprocessing earlier steps. Completed subagent work survives a mid-run failure.
- Checkpointing enables:
  - indefinite human-in-the-loop pauses (minutes or days),
  - time travel (rewind and replay from earlier states),
  - an audit trail and recovery point for sensitive or irreversible actions.
- The Agent Server configures a persistent checkpointer automatically. Self-hosted deployments must set up persistence themselves.

## Memory in production

- Memory is stored as files in a virtual filesystem. By default, files are scoped to one thread.
- Cross-thread memory requires routing a path such as `/memories/` to a `StoreBackend` on the LangGraph Store. A `CompositeBackend` combines thread-scoped scratch space with cross-thread routes.

Scope options:

| Scope | Namespace | Typical use |
|---|---|---|
| User (recommended default) | `user_id` | Personal preferences and context |
| Assistant | `assistant_id` | Shared instructions for one assistant |
| Global / Organization | `org_id` | Read-only policies for everyone |

User-plus-assistant and user-only variants are also shown.

Application code can read and write the store through the Store API. See [15-memory.md](15-memory.md).

## Execution environment

### Filesystem backends

- `StateBackend` (default): thread-scoped. Checkpointed every step, so avoid large files.
- `StoreBackend`: cross-thread, scoped with namespace factories.
- `CompositeBackend`: mixes both.
- `ContextHubBackend`: durable files in a LangSmith Hub repo, with no separate store.
- **Warning**: `FilesystemBackend` and `LocalShellBackend` access the host directly. Don't use them in deployed agents.

### Sandboxes

- Isolated containers that provide a filesystem and an `execute` tool.
- If the agent exhausts memory or crashes, only the sandbox is affected.

Sandbox lifecycle:

- **Thread-scoped (most common)**: each conversation gets its own sandbox, cleaned up when its TTL expires. Sandbox IDs live in thread metadata.
- **Assistant-scoped**: all conversations share one sandbox. It keeps cloned repos and installed packages, but accumulates state. Set a TTL, use snapshots to reset, or add cleanup logic.
- Create sandboxes in **async graph factories** that look up or create them by name.

File transfers: `upload_files()` and `download_files()` seed sandboxes with user files, skill scripts, and memories, and retrieve artifacts and sync memories back. The guide has a custom middleware example using `before_agent` and `after_agent` hooks for this.

Details: [08-sandboxes.md](08-sandboxes.md).

### Secrets

- **Auth proxy (recommended)**: injects credentials based on the destination host, so keys never appear in sandbox code, environment variables, or logs. Secrets are referenced from LangSmith workspace settings.
- Avoid passing secrets through environment variables or file uploads. The agent can read them.

## Guardrails

- **Permissions**: declarative allow and deny rules for reads and writes. First match wins. Useful for isolating the agent to a working directory or enforcing read-only memory. See [09-permissions.md](09-permissions.md).
- **Fault tolerance**: rate limiting, retries, fallbacks, and error handling. Covered on a separate page; see [12-middleware.md](12-middleware.md) for the prebuilt retry and fallback middleware.
- **PII**: `PIIMiddleware` detects sensitive data in inputs. Strategies:
  - `redact`: replace with a placeholder.
  - `mask`: partial masking, such as showing only the last four digits.
  - `hash`: deterministic hashing.
  - `block`: raise an error.
  - Custom detectors can handle domain-specific patterns.

## Async

- Create async tools to avoid threading overhead. LangChain otherwise runs sync tools in a separate thread.
- Implement async middleware hooks (the `a`-prefixed variants).
- Await sandbox creation and MCP server connections. That's why graph factories that provision these resources are async.

## Observability

- LangSmith Cloud deployments send traces automatically to a project named after the deployment.
- Hybrid and self-hosted setups have their own tracing configuration.
- **LangSmith Engine** monitors traces, detects issues, and proposes fixes. The guide recommends setting it up.

## Examples the guide includes (described)

- Context-aware agents across seven model providers, each with thread-based follow-ups.
- Thread-scoped and assistant-scoped sandbox factories, with client-side usage.
- Memory scoping configurations for user, assistant, user-only, and organization namespaces.
- A middleware example that syncs skills and memories across the sandbox boundary.
- PII middleware configuration.
- Auth proxy configuration.
- A frontend `useStream` setup.

## Related

- Managed vs. self-hosted comparison with Claude Agent SDK: [20-comparison-claude-agent-sdk.md](20-comparison-claude-agent-sdk.md)
- Streaming to a frontend: [17-streaming.md](17-streaming.md)
