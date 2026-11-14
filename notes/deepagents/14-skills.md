# Skills

Skills are reusable, on-demand instructions the agent loads when needed. Deep Agents follows the **Agent Skills** specification at `agentskills.io`.

Skills are procedural memory: how to do a task, not facts. Memory is in [15-memory.md](15-memory.md).

## Directory format

A skill is a directory containing a `SKILL.md` file:

```
my-skill/
  SKILL.md          # required: YAML frontmatter + markdown instructions
  scripts/          # optional: executable code (API clients, transforms, validators)
  references/       # optional: on-demand docs (guides, schemas)
  assets/           # optional: templates, images, lookup tables
```

Rules:

- `SKILL.md` starts with YAML frontmatter, then markdown instructions the agent follows once the skill is activated.
- `SKILL.md` should describe each supporting file and when to use it.
- Paths are relative to the skill root.
- Keep references **one level deep**.

## Frontmatter fields

| Field | Required | Constraints |
|---|---|---|
| `name` | Yes | Lowercase letters, digits, hyphens. 1–64 characters. Must match the parent directory name |
| `description` | Yes | What the skill does and when to use it. Max 1,024 characters |
| `license` | No | License name, or a reference to a bundled license file |
| `compatibility` | No | Environment requirements. Max 500 characters |
| `metadata` | No | Arbitrary key-value pairs. Deep Agents reads `metadata.include_tools` (see Skill tools) |
| `allowed-tools` | No | Space-separated pre-approved tools. Experimental |

Deep Agents limits:

- `SKILL.md` files **over 10 MB are skipped** during loading.
- Keep frontmatter concise and the body under about 5,000 tokens. The spec suggests under 500 lines.

## Progressive disclosure

1. **Metadata**: `name` and `description` for every configured skill are added to the system prompt at startup. `SkillsMiddleware` handles this.
2. **Instructions**: the full `SKILL.md` body is read when the agent invokes the skill. `SkillsMiddleware` handles this.
3. **Resources**: `scripts/`, `references/`, and `assets/` are read only when the instructions call for them. The LLM handles this.

## The `skills` parameter

```python
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=backend,
    skills=["/skills/"],
)
```

- `skills` is a `list[str]` of **source directories**. Each entry must be a directory that **contains skill directories**.
- Pointing at a single skill directory loads **nothing** and raises no error.
- Paths use forward slashes and are relative to the backend's root.
- If omitted, no skills load.

## Backend setup for skills

| Backend | How to put skills in |
|---|---|
| `StateBackend` (default) | Pass files at invoke time: `invoke(files={...})`, with values built by `create_file_data()` from `deepagents.backends.utils`. Raw strings are not supported |
| `FilesystemBackend` | Call `backend.upload_files()`, or use skills already on disk under `root_dir`. Set `virtual_mode=True` |
| `StoreBackend` | Call `backend.upload_files()` to populate the store |

Subagent skills go in a `skills` key on each subagent definition.

## Sources and precedence

- You can pass multiple source paths.
- When two sources contain a skill with the same name, the **last** source in the list wins.
- Deep Agents does **not** scan `~/.deepagents/` or `~/.agents/` on its own. The SDK loads only what you pass.
- To emulate Deep Agents Code's layering, list sources from lowest precedence (user-level) to highest (project-level).

## Reloading skills

Skills load **once per thread** and persist in agent state when a checkpointer is configured.

To reload:

- Pass `"skills_metadata": None` in the run input (requires `deepagents>=0.7.16`), or
- Call `agent.update_state(config, {"skills_metadata": None})`.

Use `None`, not an empty list. An empty list means no skills for the rest of the thread.

Without a checkpointer, local runs reload on every run.

## Pinning skills

- Pass `"pinned_skills": [names]` in the run input (requires `deepagents>=0.7.23`).
- Before the next model call, each pinned skill's `SKILL.md` (without frontmatter) is appended as a `HumanMessage` wrapped in a `<skill>` tag.
- Each message's `additional_kwargs` has `lc_source` set to `"pinned_skill"`, and a `skill` value with `name`, `path`, and `description`.
- Unknown names and unreadable files are skipped and logged at debug level.
- Your app decides how users reference skills (for example, `/skill-name` in a message). Deep Agents does not parse messages.

## Skill tools (`deepagents>=0.7.22`)

Skills can expose tools.

- Declare them in frontmatter under `metadata.include_tools`, as a **space-separated string**. A YAML list does **not** match.
- Create `SkillsMiddleware` yourself and pass it in `middleware`, with `sources` and `tools`.
- **Gating**: skill tools fail as unknown until the agent reads the skill's `SKILL.md`. Summarization that drops that read makes them unavailable again.
- **Pinning** a skill also makes its tools available.
- `tools` can be a **resolver function** that receives each name and the graph `Runtime`. Use it to map readable names to real tool names, or to vary tools per user. Resolvers should be fast.
- Deferred tools (`extras={"defer_loading": True}`), passed to the agent's `tools` with `ProviderToolSearchMiddleware`, stay reachable through search even before the skill is read.
- If a listed name matches a tool already on the agent, the agent's tool takes precedence.

## Subagents and skills

- The **general-purpose subagent** inherits skills from `create_deep_agent` automatically.
- **Custom subagents do not inherit skills.** Give each one its own `skills` list.
- Skill state is isolated between the main agent and subagents.

## Permissions and write control

- **Read-only skills**: route `/skills/` to a curated backend and add a `FilesystemPermission` with `operations=["write"]`, `paths=["/skills/**"]`, `mode="deny"`.
- **Writable skills**: route editable paths to writable backends and deny writes to protected paths. Put more specific rules first.
- **Write approval**: use `interrupt_on`, or a permission rule with `mode="interrupt"`. Requires `deepagents>=0.6.8` and a checkpointer.

See [09-permissions.md](09-permissions.md).

## Skill availability by context

- Choose the `skills` list per request, role, or tenant when creating the agent.
- Use a backend route with a namespace function based on runtime context, so each identity gets its own library under the same path.
- Compose multiple sources, such as org-wide, team, and request-specific skills.

## Code execution in skills

- Skills can reference scripts, but running them requires a **sandbox backend** with a shell.
- Skill files outside the sandbox are not visible inside it. Use custom `AgentMiddleware` to copy skill files into the sandbox in `before_agent`, and write changes back in `after_agent`. See [08-sandboxes.md](08-sandboxes.md).

## Writing effective skills

- Write specific descriptions that say what the skill does and when to activate. Vague descriptions cause missed or wrong activations.
- Differentiate descriptions when skills overlap, or merge the skills.
- Fewer well-scoped skills work better than many overlapping ones.
- Include step-by-step procedures, decision criteria, input and output examples, and edge-case handling.
- Use `skills-ref` to validate frontmatter.

## Troubleshooting

| Symptom | Likely cause from the docs |
|---|---|
| Skill not activated | Description not specific enough, overlap with another skill, path not in `skills`. Or pin the skill |
| Skill missing at startup | Backslashes or non-root-relative paths; passed a skill directory instead of a source directory; invalid frontmatter `name`; file over 10 MB; overridden by a later source |
| Changes not picked up | Reset `skills_metadata` |
| Supporting files not found | Not referenced explicitly from `SKILL.md`, or not synced into the sandbox |
| Skill tool unavailable | Agent hasn't read the skill; `include_tools` is a YAML list, not a space-separated string; names don't match tools or the resolver. Unmatched names log at DEBUG for the `deepagents` logger |
| Scripts fail | No sandbox backend |
| Subagent lacks a skill | Add a `skills` entry to that subagent |

## Minimal example

```python
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend

backend = FilesystemBackend(root_dir="./my-project", virtual_mode=True)

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    backend=backend,
    skills=["/skills/"],  # a directory containing skill directories
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Summarize the release notes."}]},
    config={"configurable": {"thread_id": "1"}},
)
```

This example is written for these notes, not copied from the docs. It combines the documented `FilesystemBackend`, `skills=`, and `thread_id` config patterns.
