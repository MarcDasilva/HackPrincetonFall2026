# Filesystem Permissions

`permissions=` on `create_deep_agent` takes a list of `FilesystemPermission` rules that control which filesystem operations the agent may perform. Requires `deepagents>=0.5.2`.

## Scope

Covers the built-in filesystem tools:

- **Reads**: `ls`, `read_file`, `glob`, `grep`.
- **Writes**: `write_file`, `edit_file`, `delete`.

Does **not** cover:

- Custom tools.
- MCP tools that touch the filesystem.
- Sandbox backends, which can run arbitrary commands through `execute`.

For custom validation (rate limiting, audit logging, content inspection), use backend policy hooks. See [07-backends.md](07-backends.md).

## `FilesystemPermission` fields

| Field | Type | Details |
|---|---|---|
| `operations` | `list["read" \| "write"]` | `"read"` covers reads; `"write"` covers writes |
| `paths` | `list[str]` | Glob patterns such as `/workspace/**`. Supports `**` (recursive) and `{a,b}` (alternation) |
| `mode` | `"allow" \| "deny" \| "interrupt"` | Default `"allow"`. `"interrupt"` requires `deepagents>=0.6.8` |

Example used in the backends page: deny `write` on `/policies/**`.

## Evaluation order

- Rules are checked **in declaration order**.
- The **first rule** whose `operations` and `paths` both match decides the outcome.
- If no rule matches, the call is **allowed**. The default is permissive.
- Order matters. A broad rule placed first shadows the narrower rules after it.

## Modes

- **`allow`**: permits the matching operation.
- **`deny`**: blocks it.
- **`interrupt`**: for write tools on matching paths, `create_deep_agent` raises a human-in-the-loop interrupt instead of running the tool. A reviewer can approve, edit, or reject. Requires a checkpointer such as `InMemorySaver`. Interrupt rules merge with any `interrupt_on` you pass and resume the same way.

## Delete semantics

- **Directory delete is all-or-nothing.** `delete` checks `write` on the target and every descendant. If any is denied, the whole operation is refused, including for an empty directory.
- **File delete is exact-match.** It resolves the target the same way `write_file` and `edit_file` do, with first-match-wins. An earlier, narrower `allow` beats a later catch-all `deny`. Requires `deepagents>=0.7.3`.

## Interrupt pattern anchoring

- Anchor interrupt patterns with a literal leading segment, such as `/secrets/**` or `/projects/*/secrets/**`.
- Bulk tools (`ls`, `glob`, `grep`, and `delete` on a directory) trigger an interrupt when their search subtree could overlap the anchored prefix.
- Fully unanchored patterns like `/**/secrets` over-fire conservatively.

## Glob semantics

- `**` matches recursively across directory levels.
- `{a,b}` is alternation.
- Literal paths work, such as `/workspace/.env`.
- A single `*` works as a segment wildcard in the example `/projects/*/secrets/**`. The page does not formally define it.

## Examples (reconstructed from the docs' descriptions)

These are described in prose on the page. Here they are written as rule lists, reconstructed from the description:

**1. Read-only agent:** one `write` rule with `deny` on `/**`.

```python
permissions=[
    FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
]
```

**2. Workspace isolation:** allow reads and writes under `/workspace/**`, then deny everything else.

```python
permissions=[
    FilesystemPermission(operations=["read", "write"], paths=["/workspace/**"], mode="allow"),
    FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
]
```

**3. Protected files:** deny `.env` and an examples folder first, then allow the workspace, then a catch-all deny.

```python
permissions=[
    FilesystemPermission(operations=["read", "write"], paths=["/workspace/.env", "/workspace/examples/**"], mode="deny"),
    FilesystemPermission(operations=["read", "write"], paths=["/workspace/**"], mode="allow"),
    FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
]
```

**4. Read-only memory:** a `CompositeBackend` routes `/memories/` and `/policies/` to `StoreBackend`s, with namespaces keyed by user identity and org ID. A `write` deny covers both routes. See [15-memory.md](15-memory.md).

**5. Deny-all baseline:** deny read and write on `/**`, with allow rules layered above.

**6. Rule ordering:** the correct version puts `deny` on `/workspace/.env` before `allow` on `/workspace/**`. The incorrect version puts the allow first, so the `.env` deny never fires.

The rule ordering in example 6 is the one to remember. A broad allow above a narrow deny silently disables the deny.

## Subagent permissions

- Subagents **inherit** the parent's permissions by default.
- Setting `permissions` in a subagent spec **replaces** the parent's rules entirely. It does not merge.
- Example pattern: an "auditor" subagent with `deny` on all writes, `allow` on reads under `/workspace/**`, and a catch-all read `deny`.

See [10-subagents.md](10-subagents.md).

## Composite backends

With a **sandbox** as the default backend, every permission path must fall under a known route prefix.

- Reason: sandboxes allow shell execution, so path rules alone can't stop filesystem access through commands.
- Paths outside any route raise `NotImplementedError` at agent creation. Examples: `/workspace/**`, which falls to the sandbox default, and `/**`, which covers both routes and the default.
- Scope permissions to route-specific backends to avoid the error. For example, a `deny` on `/memories/**` works when `/memories/` is a configured route.

## Interaction with skills

For read-only skills: route `/skills/` to a curated backend and add a `FilesystemPermission` with `operations=["write"]`, `paths=["/skills/**"]`, `mode="deny"`. See [14-skills.md](14-skills.md).

## Summary of gotchas

- First match wins. Put narrow rules first.
- No match means allowed.
- Subagent permissions replace, not merge.
- Directory delete is all-or-nothing.
- Permissions don't cover shell commands in sandboxes.
