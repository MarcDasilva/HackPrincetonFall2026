# Backends

A **backend** decides where the agent's files live and how the filesystem tools read and write them. Pass one instance as `backend=` to `create_deep_agent`. It must implement `BackendProtocol`.

Default: `StateBackend()`.

## Built-in backends

| Backend | Constructor | Where data lives | Shared across threads? | Risk level |
|---|---|---|---|---|
| `StateBackend` | `StateBackend()` | LangGraph state, thread-scoped | No | Low |
| `FilesystemBackend` | `FilesystemBackend(root_dir, virtual_mode)` | Local disk under `root_dir` | Yes (disk) | High without `virtual_mode` |
| `LocalShellBackend` | `LocalShellBackend(root_dir, virtual_mode, env, inherit_env, timeout, max_output_bytes)` | Local disk, plus shell `execute` | Yes | Highest |
| `StoreBackend` | `StoreBackend(namespace, store)` | LangGraph `BaseStore` | Yes, by namespace | Low |
| `ContextHubBackend` | `ContextHubBackend(repo)` | LangSmith Context Hub repo | Yes | Depends on repo |
| `CompositeBackend` | `CompositeBackend(default, routes)` | Routes path prefixes to other backends | Mixed | Depends on routes |
| Sandbox backends | Provider classes (see [08-sandboxes.md](08-sandboxes.md)) | Isolated container | Per sandbox | Isolated |

## `StateBackend` (default)

- No constructor arguments.
- Files are stored in LangGraph state, scoped to the current thread.
- Persists across turns when a checkpointer is configured. Not shared across threads.
- Shared between supervisor and subagents. Files written by a subagent remain available afterward.
- Must be used inside a graph run. Calling methods like `upload_files(...)` outside a run has no effect until the graph executes.
- Best for scratch space and automatic eviction of large tool outputs.
- Checkpointed at every step, so avoid storing large files in it (a point the production guide makes).
- Skills can be passed at invoke time: `invoke(files={...})` with `create_file_data()` from `deepagents.backends.utils`. Raw strings are not supported.

## `FilesystemBackend` (local disk)

- Constructor: `FilesystemBackend(root_dir, virtual_mode)`.
- Reads and writes real files under `root_dir`. Uses secure path resolution, avoids unsafe symlink traversal when possible, and uses ripgrep for `grep` when it's available.
- `root_dir` must be an **absolute path**.
- `virtual_mode=True` normalizes and sandboxes paths under `root_dir`, blocking `..`, `~`, and absolute paths outside the root.
- **Default `virtual_mode=False` gives no security**, even with `root_dir` set.
- Security warnings from the docs:
  - Agents can read secrets (`.env`, API keys).
  - Secrets may be exfiltrated via network tools.
  - File changes are irreversible.
- Recommended safeguards: enable HITL middleware, exclude secrets from accessible paths, use a sandbox in production, always use `virtual_mode=True`.
- Not suited to web servers or HTTP APIs.
- Best for local projects, CI sandboxes, and mounted persistent volumes.
- The production guide says deployed agents should not use `FilesystemBackend` or `LocalShellBackend`.

```python
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend

backend = FilesystemBackend(root_dir="./my-project", virtual_mode=True)

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=backend,
    skills=["/skills/"],
)
```

## `LocalShellBackend`

- Constructor: `LocalShellBackend(root_dir, virtual_mode, env, inherit_env, timeout, max_output_bytes)`.
- Extends `FilesystemBackend` and adds the `execute` tool.
- Runs commands on the host with `subprocess.run(shell=True)`. **No sandboxing.**
- Defaults: `timeout` 120 seconds, `max_output_bytes` 100,000. Supports `env` and `inherit_env`.
- Commands use `root_dir` as the working directory but can access any path.
- `virtual_mode=True` gives **no** security once shell access is enabled.
- Only for trusted development environments. HITL is strongly recommended.

## `StoreBackend` (cross-thread)

- Constructor: `StoreBackend(namespace, store)`.
- Stores files in a LangGraph `BaseStore`, so they persist across threads.
- On LangSmith Agent Server, **omit `store`**; the platform provides one. For local development, pass `InMemoryStore()` to `create_deep_agent(store=...)`.

### Namespace

`namespace` controls isolation. Two forms:

- A static tuple, which is the simplest form.
- A **namespace factory**, `NamespaceFactory = Callable[[Runtime], tuple[str, ...]]`.

For multi-user deployments, always use a factory. Without one, the legacy default uses `assistant_id`, so all users of an assistant share storage. The docs say this default will be required to change in v0.5.0.

### Runtime object (for factories)

- `rt.context`: user-supplied context from the context schema.
- `rt.server_info`: assistant ID, graph ID, authenticated user.
- `rt.execution_info`: thread ID, run ID, checkpoint ID.

Common patterns:

- Per-user: `rt.server_info.user.identity`
- Per-assistant: `rt.server_info.assistant_id`
- Per-thread: `rt.execution_info.thread_id`
- Tuples can combine components.

Allowed characters in namespace components: alphanumerics, hyphens, underscores, dots, `@`, `+`, colons, tildes. Wildcards (`*`, `?`) are rejected.

Version requirements: namespace factories need `deepagents>=0.5.2`. `server_info` and `execution_info` need `>=0.5.0`.

## `ContextHubBackend`

- Constructor: `ContextHubBackend(repo)`. `repo` is `owner/name` or `name`.
- Stores files in a LangSmith Context Hub repo. Requires `LANGSMITH_API_KEY`.
- The agent repo mounts at the root. Linked skill repos appear under `/skills/`.
- Pulls the repo tree lazily on first use, serves reads from an in-memory cache, and persists writes as Hub commits.
- Writes use optimistic `parent_commit` concurrency. Stale writes can fail; re-pull and retry on conflict.
- A missing repo is treated as empty on first pull. The first successful write can create it.
- `upload_files()` accepts UTF-8 only. Non-UTF-8 files are rejected per path with `invalid_path`.

## `CompositeBackend` (routing)

- Constructor: `CompositeBackend(default, routes)`.
- `routes` maps path prefixes (such as `"/memories/"`) to backend instances.
- **Longer prefixes win.** `"/memories/projects/"` overrides `"/memories/"`.
- `ls`, `glob`, and `grep` aggregate results across backends and keep the original path prefixes.
- **Path stripping:** the route prefix is removed before the operation is forwarded. Seed data uses backend-relative keys (for example, `/AGENTS.md`), not agent-facing paths (`/memories/AGENTS.md`).
- Internal data (offloaded results, conversation history) goes to the default backend.
- For `StoreBackend` routes, a store must be provided via `create_deep_agent(store=...)` or by the platform.

Example routing from the docs:

- `/workspace/plan.md` → `StateBackend` (thread-scoped).
- `/memories/agent.md` → `FilesystemBackend` under a specified root.

```python
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
```

(Import paths follow the reference; confirm them against your installed version.)

## Offloading binary content

Requires `deepagents>=0.7.21`. Disabled by default.

- Set `offload_binary_content=True` on `FilesystemMiddleware`, passed in the `middleware` list. Use the same backend for the agent and middleware.
- Blobs are stored under `/blobs/<sha256>` by default, or under `artifacts_root` if set on the middleware.
- Message history keeps content-addressed references and restores media before each model call.
- Has no effect when blobs route to `StateBackend`, including via `CompositeBackend`. Route the blob directory to external storage.
- The original payload still appears in earlier checkpoints. Keep blob storage available when resuming threads.

## Custom backends

To write your own backend, implement `BackendProtocol`.

### Required methods

| Method | Signature | Purpose |
|---|---|---|
| `ls` | `(path) -> LsResult` | List files and directories |
| `read` | `(file_path, offset, limit) -> ReadResult` | Read contents, paginated |
| `write` | `(file_path, content) -> WriteResult` | Create or overwrite |
| `edit` | `(file_path, old_string, new_string, replace_all) -> EditResult` | Find and replace |
| `glob` | `(pattern, path) -> GlobResult` | Match paths |
| `grep` | `(pattern, path, glob) -> GrepResult` | Literal search |
| `delete` | `(file_path) -> DeleteResult` | Optional. Hidden from the model if unsupported |

For `execute` support, implement `SandboxBackendProtocol`, which extends `BackendProtocol` with `execute`.

### Behavior rules

- Return structured results with an `error` field. **Do not raise exceptions.**
- `ls`: include `is_dir`, `size`, and `modified_at` when available. Sort by `path`.
- `read`: on a missing file, return an error such as `"Error: File '/x' not found"`.
- `grep`: return structured matches. On error, return an error result.
- `glob`: return `FileInfo` entries, or an empty list.
- `write`: on conflict, return an error. On success, set `path`. State backends set `files_update`. External backends use `files_update=None`.
- `edit`: enforce uniqueness of `old_string` unless `replace_all=True`. Return `occurrences` on success.

### Result and data types

- `LsResult(error, entries)`
- `ReadResult(error, file_data)`
- `GrepResult(error, matches)`
- `GlobResult(error, matches)`
- `WriteResult(error, path, files_update)`
- `EditResult(error, path, files_update, occurrences)`
- `FileInfo`: `path` (required), plus optional `is_dir`, `size`, `modified_at`
- `GrepMatch`: `path`, `line`, `text`
- `FileData`: `content`, `encoding` (`"utf-8"` or `"base64"`), `created_at`, `modified_at`

### Skeleton from the docs

The docs include an S3-style skeleton, `S3Backend(bucket, prefix)`, that maps agent paths to object keys, with stubbed method bodies. The mapping idea is the useful part: paths become keys under a prefix.

## Policy hooks (custom validation)

For logic beyond path rules (rate limiting, audit logging, content inspection):

- **Subclass approach**: extend `FilesystemBackend` and override `write` and `edit` to return errors for denied prefixes.
- **Wrapper approach**: a `PolicyWrapper(inner, deny_prefixes)` that implements `BackendProtocol`, delegates reads, and blocks writes and edits under denied prefixes. Denied prefixes are normalized to end with `/`.

Path-level rules are simpler. Use [09-permissions.md](09-permissions.md) first.

## Specifying the backend

```python
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6", backend=StateBackend())
```

Pass **instances**, not factories. The factory pattern is deprecated in 0.5.0 and emits a warning.

## Deprecations (0.5.0)

- Callables passed to `backend=`.
- The `runtime` constructor argument on `StateBackend` and `StoreBackend`.
- The `files_update` field on `WriteResult` and `EditResult` (per the migration section; the protocol section above still lists `files_update` for state backends, so check your version).
- `Command` wrapping in middleware write and edit tools. Tools return plain strings now.
- `BackendContext` access through `.runtime` in namespace factories. Deprecated in `deepagents>=0.5.2` (Python) and `>=1.9.1` (TypeScript). Removed in `>=0.7`.
- Migration example: `ctx.runtime.context.user_id` becomes `rt.server_info.user.identity`.
- There is no direct replacement for `ctx.state`. Namespaces should be stable across a run, so deriving them from mutable state is discouraged.

## Quick reference

| Backend | Constructor |
|---|---|
| `StateBackend` | `StateBackend()` |
| `FilesystemBackend` | `FilesystemBackend(root_dir, virtual_mode)` |
| `LocalShellBackend` | `LocalShellBackend(root_dir, virtual_mode, env, inherit_env, timeout, max_output_bytes)` |
| `StoreBackend` | `StoreBackend(namespace, store)` |
| `ContextHubBackend` | `ContextHubBackend(repo)` |
| `CompositeBackend` | `CompositeBackend(default, routes)` |

## Related

- Sandboxes (isolated `execute`): [08-sandboxes.md](08-sandboxes.md)
- Memory on backends: [15-memory.md](15-memory.md)
- Permissions: [09-permissions.md](09-permissions.md)
