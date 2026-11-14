# Memory

Memory in Deep Agents is **filesystem-backed**. The agent reads and writes memory as files, and you choose where those files live through **backends**. This note covers **long-term** memory (across conversations).

Short-term memory (conversation history and scratch files within one session) is handled automatically as part of agent state. The context engineering material is in [18-context-management.md](18-context-management.md).

## The `memory=` parameter

```python
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=backend,
    memory=["/memories/AGENTS.md"],
)
```

- `memory` is a `list[str]` of file paths.
- Example paths from the page: `/memories/AGENTS.md`, `/memories/preferences.md`, `/policies/compliance.md`.
- Memory files are **always loaded**, unlike skills, which load on demand.
- Requires that the files exist in the backend before the agent is created.

## AGENTS.md

- `/memories/AGENTS.md` is the canonical agent-scoped memory file, passed to `memory=`.
- OpenWiki generates a repository wiki that coding agents discover through `AGENTS.md`. OpenWiki is referenced on the docs pages; its details are not in these notes.

## How the agent reads memory

- Memory files can be loaded **into the system prompt at startup**, or read **on demand** during the conversation.
- Skills use on-demand loading: only descriptions load at startup, and a full skill file is read when it matches a task. This keeps the context lean.

## How the agent updates memory

- The agent uses its built-in `edit_file` tool to update memory files when it learns something new.
- Updates happen in one of two modes:
  - **During the conversation** (the default, "hot path").
  - **Between conversations**, in the background ("background consolidation").
- Changes persist and are available in the next conversation.
- Developer-defined skills and organization policies are usually read-only.

## Backends for memory

Memory needs a backend that persists across threads. The page's examples use a **`CompositeBackend`** that routes path prefixes:

- `default`: typically `StateBackend`. Ephemeral, per thread.
- `routes`: map `/memories/` and `/skills/` to a **`StoreBackend`**, which persists to a LangGraph store.

Setup:

- `StoreBackend` requires a store. Examples use `InMemoryStore` locally, and say to use the platform store when deploying to LangSmith.
- Pass the store with `create_deep_agent(store=...)`.
- **Path stripping**: `CompositeBackend` removes the route prefix before forwarding. Seed data must use backend-relative keys, such as `/AGENTS.md`, not `/memories/AGENTS.md`.
- Seed files with the `create_file_data` helper from `deepagents.backends.utils`.
- The store `put` call takes a **namespace tuple**, a key, and the file data.

See [07-backends.md](07-backends.md).

## Scope patterns and namespaces

### Agent-scoped (shared across users)

- Namespace: `(assistant_id,)`, read from `rt.server_info.assistant_id`.
- Every conversation for this agent reads and writes the same files.
- The agent builds a persona, accumulated knowledge, and learned preferences over time.
- It can also learn and update skills if it has write access.

### User-scoped (isolated per user)

- Namespace: `(user_id,)`, read from `rt.server_info.user.identity`.
- Each user gets an isolated copy, so one user's preferences never leak into another's conversations.
- Per-user skills can live in a user-scoped backend too.

### Organization-level

- Namespace based on `rt.context.org_id`, applied to a route such as `/policies/`.
- Used for policies or knowledge shared across all users and agents.
- Typically read-only. Populated from application code with the store client's `put_item` method.
- Can be combined with user-scoped memory in the same agent's `memory=` list.

### Multiple agents in one deployment

- Combine `assistant_id` and user identity in the namespace for per-agent, per-user isolation.
- Use `assistant_id` alone for per-agent isolation without per-user scoping.

Version note: `rt.server_info` requires `deepagents>=0.5.0`. On older versions, read the assistant ID from the config metadata.

The production guide's scope table:

| Scope | Namespace | Typical use |
|---|---|---|
| User (recommended default) | `user_id` | Personal preferences and context |
| Assistant | `assistant_id` | Shared instructions for one assistant |
| Global / Organization | `org_id` | Read-only policies for everyone |

## Cross-thread memory

- Each conversation is a separate **thread**, persisted through checkpointers.
- Store-backed memory persists **across threads**. The page's example has one thread save a user preference, and a second, separate thread read and apply it.
- **Episodic memory** (recalling past conversations) is built on checkpointed threads. A tool can search past threads with the LangGraph SDK, filtering by metadata such as `user_id` or `org_id`, then fetch each thread's history. The page notes this suits multi-step tasks, such as a coding agent revisiting a past debugging session.
- The user ID comes from the **runtime context**, not from a tool parameter.

## Background consolidation ("sleep time compute")

- A separate **consolidation agent** reviews recent conversations, extracts key facts, and merges them into memory.
- It runs on a **cron schedule** and is registered alongside the main agent in the deployment config.
- Its search tool looks back over a time window using an `updated_after` filter.
- **Critical constraint**: the cron interval must match the lookback window. Running more often reprocesses conversations. Running less often drops memories.
- Cron schedules are interpreted in **UTC**.
- Cadence should follow real usage. Consolidating more often than users converse wastes tokens.

Trade-offs from the page:

| Approach | Pros | Cons |
|---|---|---|
| Hot path | Immediately available, transparent | Adds latency; agent multitasks |
| Background | No user-facing latency; synthesizes across conversations | Not available until the next conversation; needs a second agent |

## Read-only vs writable memory

- **Read-write (default)**: user preferences, agent self-improvement, learned skills. The agent updates files with `edit_file`.
- **Read-only**: organization policies, compliance rules, shared knowledge bases, developer-defined skills. Populated by application code or the Store API.

Enforce read-only with:

- **Permissions**: deny writes to specific paths. See [09-permissions.md](09-permissions.md).
- **Policy hooks**: custom validation such as rate limiting, audit logging, or content inspection. See [07-backends.md](07-backends.md).

Security guidance from the page:

- Default to user scope unless sharing is needed.
- Use read-only memory for shared policies.
- Add human approval (interrupts) for writes to sensitive paths.
- **Shared writable memory is a prompt-injection risk**: one user's writes can influence another user's agent.

## Concurrency

- Multiple threads can write to memory in parallel.
- Concurrent writes to the **same file** can cause **last-write-wins** conflicts.
- Mitigations:
  - user-scoped memory (conflicts are rare),
  - background consolidation (serialized writes),
  - separate files per topic (less contention).
- The LLM can often retry or recover from a failed write, so one lost write is not catastrophic.

## Six dimensions of memory (from the page)

- **Duration**: short-term vs long-term.
- **Information type**: episodic (past experiences), procedural (skills and instructions), semantic (facts).
- **Scope**: user, agent, or organization.
- **Update strategy**: during conversation or between conversations.
- **Retrieval**: loaded into the prompt, or on demand.
- **Agent permissions**: read-write or read-only.

## Observability

LangSmith tracing can audit memory writes. Each file write appears as a tool call in the trace.

## Related

- Skills (procedural memory): [14-skills.md](14-skills.md)
- Backends: [07-backends.md](07-backends.md)
- Production memory guidance: [19-production-and-deployment.md](19-production-and-deployment.md)
