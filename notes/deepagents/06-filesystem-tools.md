# Filesystem Tools

Every deep agent gets filesystem tools through `FilesystemMiddleware`. The tools route through the configured backend, so the same tool names work whether the storage is in state, on disk, in a store, or in a sandbox.

## Tool list

| Tool | What it does |
|---|---|
| `ls` | Lists files with metadata (size, modified time) |
| `read_file` | Reads with line numbers. Supports `offset` and `limit`. Returns multimodal blocks for non-text files |
| `write_file` | Creates or overwrites a file |
| `edit_file` | Exact string replacement, with a global replace mode |
| `delete` | Deletes a file, or a directory recursively. Requires `deepagents>=0.7`. Hidden for backends that don't support it |
| `glob` | Finds files by pattern (for example, `**/*.py`) |
| `grep` | Searches content. Output modes: files only, content with context, or counts |
| `execute` | Runs shell commands. Sandbox backends only |

Sources: overview page (table) and backends page.

## Multimodal reads (`read_file`)

`read_file` returns non-text files as multimodal content blocks. Supported extensions from the overview:

- **Image**: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.heic`, `.heif`
- **Video**: `.mp4`, `.mpeg`, `.mov`, `.avi`, `.flv`, `.mpg`, `.webm`, `.wmv`, `.3gpp`
- **Audio**: `.wav`, `.mp3`, `.aiff`, `.aac`, `.ogg`, `.flac`
- **File**: `.pdf`, `.ppt`, `.pptx`

The backends page says images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`) come back as multimodal blocks across all backends. The wider list above is from the overview page. Model support for each type depends on the model.

## Hiding default filesystem tools

Register a harness profile with `excluded_tools` and `HarnessProfile`, then `register_harness_profile(...)`.

Names you can exclude: `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`.

Rules from the overview:

- Removing `FilesystemMiddleware` through `excluded_middleware` is **rejected**. It is required scaffolding.
- To remove the `task` tool, see the subagents page (the general-purpose profile setting, not `excluded_middleware`).

See [13-harness-profiles.md](13-harness-profiles.md).

## Restricting filesystem tools (allowlist)

Pass a `FilesystemMiddleware` instance through `middleware=`, with a `tools` allowlist. Requires `deepagents>=0.7`.

```python
FilesystemMiddleware(backend=backend, tools=["read_file", "ls", "glob", "grep"])
```

That example is a read-only agent.

Rules:

- `read_file` must always be in the list, or `ValueError` is raised.
- `execute` and `delete` are dropped automatically if the backend doesn't support them.
- Custom tools passed through `tools=` are not affected.
- The restriction is **inherited by the general-purpose subagent**.
- Declarative subagents need their own `FilesystemMiddleware(tools=...)` instance.

## Offloading large results

The quickstart says the agent uses `write_file` and `read_file` to offload large search results. The overview lists "Context management: summarize long threads and offload tool outputs to disk." Offloading goes to the backend, so it lands in `StateBackend` by default. Details are in [18-context-management.md](18-context-management.md).

Binary offloading (opt-in, `deepagents>=0.7.21`): `offload_binary_content=True` on `FilesystemMiddleware`. Blobs are stored under `/blobs/<sha256>` by default, or under `artifacts_root` if set. Disabled by default. It has no effect when blobs route to `StateBackend`, including via `CompositeBackend`; route the blob directory to external storage.

## Permissions

Filesystem reads and writes can be restricted with `FilesystemPermission` rules. See [09-permissions.md](09-permissions.md).

- `read` covers `ls`, `read_file`, `glob`, `grep`.
- `write` covers `write_file`, `edit_file`, `delete`.

## Edit semantics

From the backend protocol:

- `edit` enforces that `old_string` is unique unless `replace_all=True`.
- A successful edit returns an `occurrences` count.

So if the agent tries to edit a string that appears more than once, it fails unless it asks for global replace.

## Read semantics

- `read` supports pagination through `offset` and `limit`.
- On a missing file, the error is `"Error: File '/x' not found"`.

## Write semantics

- Protocol reference: `write` is create-only in the protocol reference, but the overview describes `write_file` as "creates or overwrites." Treat the overwrite behavior as the documented tool behavior.
- On conflict, return an error result.

## Directory delete

- Directory delete is **all-or-nothing** under permissions. `delete` checks `write` on the target and every descendant. If any is denied, the whole operation is refused, including for an empty directory.
- File delete is exact-match and uses first-match-wins permission rules (requires `deepagents>=0.7.3`).

## `execute`

- Only on sandbox backends and `LocalShellBackend`. Other backends don't get it.
- Runs a shell command and returns combined stdout/stderr, the exit code, and a truncation notice if output is too large.
- Very large output is saved to a file, and the agent is told to read it incrementally with `read_file`.

See [08-sandboxes.md](08-sandboxes.md).

## Path rules

- Paths are root-relative and use forward slashes.
- With `FilesystemBackend(virtual_mode=True)`, paths are sandboxed under `root_dir`, and `..`, `~`, and absolute paths that escape the root are blocked.
- Glob patterns in permissions support `**` and `{a,b}`.

## Name collisions

If a custom tool has the same name as a built-in one, the custom tool takes precedence (this is documented for skill-tool name matching, and is the general rule for tools on the agent).
