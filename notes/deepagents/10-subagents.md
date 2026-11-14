# Subagents

A deep agent can delegate work to subagents through the built-in **`task`** tool. The main agent calls `task()` with a subagent name and a description of the work.

Subagents provide **context quarantine**. Their intermediate tool calls stay out of the main agent's context, and only the final result comes back. That keeps the supervisor's context small.

This note covers **synchronous** subagents, where the supervisor waits for the result. Parallel, long-running, or steerable work is in [11-async-subagents.md](11-async-subagents.md).

## When to use subagents

Use them when:

- multi-step tasks would clutter the main context,
- a domain needs custom instructions or tools,
- a different model fits the subtask better,
- the main agent should focus on coordination.

Skip them when:

- the task is simple and single-step,
- intermediate context must be kept,
- the overhead outweighs the benefit.

## Configuration

`subagents=` takes a list of either:

- **SubAgent dictionaries** (most common), or
- **`CompiledSubAgent`** objects wrapping a prebuilt LangGraph graph.

### SubAgent dictionary fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | `str` | Yes | Unique. Used in `task()` calls, and as metadata on `AIMessage`s and stream events |
| `description` | `str` | Yes | Specific and action-oriented. The main agent uses it to decide when to delegate |
| `system_prompt` | `str` | Yes for `mode: "isolated"` (default) | Does not inherit from the main agent. Optional for forks, where it appends an addendum |
| `mode` | `"isolated" \| "fork"` | No | Default `"isolated"`. `"fork"` inherits the parent's conversation |
| `tools` | `list[Callable]` | No | Defaults to inheriting the main agent's tools. If set, it **replaces** them entirely |
| `model` | `str \| BaseChatModel` | No | Defaults to the main agent's model. Accepts `provider:model` strings or chat model objects |
| `middleware` | `list` | No | Isolated subagents don't inherit the main agent's custom middleware. An instance whose `.name` matches a default replaces it. Otherwise it's added |
| `interrupt_on` | `dict[str, bool \| InterruptOnConfig]` | No | Per-tool HITL config. Requires a checkpointer. Overrides the inherited value |
| `skills` | `list[str]` | No | Skill source paths. Does not inherit from the main agent |
| `response_format` | schema | No | Structured output. The parent receives JSON |
| `permissions` | `list[FilesystemPermission]` | No | **Replaces** the parent's permissions entirely when set |

### CompiledSubAgent fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | `str` | Yes | |
| `description` | `str` | Yes | |
| `runnable` | `Runnable` | Yes | A compiled graph (call `.compile()`). It must have a `"messages"` state key |
| `mode` | `"isolated" \| "fork"` | No | Defaults to isolated. A compiled graph keeps its own system prompt in either mode |

The docs show a `create_agent` call used to build a compiled subagent, then wrapped. The pattern is the same across all providers; only the model string changes.

### Example

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    subagents=[
        {
            "name": "researcher",
            "description": "Searches the web and returns a concise summary with sources.",
            "system_prompt": "You are a research assistant. Return summaries under 500 words.",
            "tools": [internet_search],
        }
    ],
)
```

The `researcher` example is written for this note from the field list above. The docs' own examples use similar shapes.

## The `task` tool

**The page gives no formal schema for `task`.** It shows two forms:

- `subagent_type` and `description`, in the coordinator's tool-call examples.
- `name` and `task`, in an example for the general-purpose subagent.

The page calls this an inconsistency. Check the actual signature in your installed version.

## The general-purpose subagent

- Every deep agent gets a synchronous subagent named `general-purpose`, unless you supply one with that name.
- It uses the default system prompt, with profile overlays.
- It has the same tools and uses the same model, unless you override them.
- It inherits the main agent's **skills**, and the filesystem tool restriction if you set one.

Ways to change it:

- **Replace**: pass your own subagent named `general-purpose`. Your spec fully replaces the default.
- **Re-prompt or rename**: set `general_purpose_subagent=GeneralPurposeSubagentProfile(...)` on the active harness profile.
- **Disable**: set `general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)` on the profile, and pass no synchronous subagents.

When there are no synchronous subagents, `SubAgentMiddleware` and the `task` tool are not attached. Listing `SubAgentMiddleware` in `excluded_middleware` raises `ValueError`. Use the profile setting instead. Async subagents are unaffected.

Prompt precedence for the general-purpose subagent's base prompt (from the customization page): `general_purpose_subagent.system_prompt` → `HarnessProfile.base_system_prompt` → SDK default. The profile suffix is layered on top.

## Forked subagents (beta, `deepagents>=0.7.13`)

Set `mode: "fork"` to inherit the parent's effective conversation history and state. The default isolated mode sees only the task description.

- **Configurable fields**: `name`, `description`, `tools`, `model`, `middleware`, `interrupt_on`, `permissions`, `response_format`.
- **Rejected**: `skills`. Providing it raises an error.
- **Middleware**: forks inherit the custom middleware passed to the parent. A subagent middleware with a matching `.name` replaces the inherited one.
- **Tools**: by default forks inherit all parent tools. Setting `tools` **replaces** that list. Filesystem and other middleware tools are added separately.
- **System prompt**: `system_prompt` is appended to the inherited prompt as an addendum. It's optional.
- **Prompt rewriting**: a `wrap_model_call` hook can use `request.override(system_message=...)` to change the fork's request without changing the parent's prompt. Prepending text ahead of the inherited prefix reduces prompt-cache reuse.
- **Mechanics**: the fork receives the parent's history with the trailing delegation call removed, plus the task description wrapped in a continuation preamble. If the parent compacted its history, the fork gets the compacted version. The fork's answer returns as a normal tool result.
- **Caching**: forks can reuse the parent's prompt cache for the matching prefix. Changing the system prompt, tools, or earlier messages shortens the shared prefix. Hits are not guaranteed.
- `CompiledSubAgent` supports `mode: "fork"` but keeps its own system prompt.

### Isolated vs forked

| Dimension | Isolated (default) | Forked |
|---|---|---|
| Context | Only the task description | Parent history and state, plus the task |
| System prompt and skills | You configure them | Inherits skills and base prompt |
| Calling `task` | Allowed | Not allowed; must do the work itself |
| Best for | Focused work needing little context | Continuing work the parent started |

## Dynamic subagents (beta)

With an interpreter attached, the agent can dispatch subagents **from code**, using loops, branches, and parallel batches, instead of single `task` calls.

- **Setup**: install `deepagents[quickjs]`, then add `CodeInterpreterMiddleware` from `langchain_quickjs` to `middleware=`.
- **Requirements**: `langchain-quickjs>=0.2.0` and Python 3.11+.
- **Default**: dispatch is on whenever the agent has subagents and the interpreter middleware. `CodeInterpreterMiddleware(subagents=False)` forces dispatch through the normal `task` path.
- **Trigger**: the word "workflow" in a request signals fan-out from code. The docs advise phrasing single delegations plainly.
- **Interface**: the interpreter exposes a built-in `task()` global.
- **dcode**: the Deep Agents Code terminal agent ships with the interpreter enabled and shows subagents in a live panel grouped by phase.

## Streaming subagents

Use `agent.stream_events(..., version="v3")` and `stream.interleave("messages", "subagents")`. Each subagent handle exposes `.name`, `.messages`, `.tool_calls`, `.output`, and `.status`. Details are in [17-streaming.md](17-streaming.md).

## Structured output (`deepagents>=0.5.3`)

- Set `response_format` on the subagent. It accepts Pydantic models, `ToolStrategy(...)`, `ProviderStrategy(...)`, or raw schema types.
- The result is JSON-serialized and returned as the parent's `ToolMessage` content.
- Without `response_format`, the parent gets the subagent's last message text.

## Model refusals (`deepagents>=0.7.33`)

- If a subagent's model refuses, the parent gets a short result saying so. It advises rephrasing or continuing without the subagent.
- For Anthropic models, the result includes a refusal category.
- Covers refusal content blocks, `ModelRefusalError` raised by a subagent (for example through `ModelRefusalMiddleware`), and structured-output parse failures caused by refusals. Async subagents behave the same way.
- When a subagent raises, the parent does not receive state the subagent changed before refusing.
- The main agent raises `ModelRefusalError` itself. A `ModelFallbackMiddleware` can catch it and retry on the next model.

## Skills

- Custom subagents do **not** inherit skills unless you set `skills`.
- Only the general-purpose subagent inherits the main agent's skills.
- Subagents with skills get an independent `SkillsMiddleware`. Skill state is isolated in both directions.

## Context propagation

- Runtime context passed to the parent's `invoke` or `ainvoke` propagates to all subagents and their tools. Declare the schema with `context_schema=`.
- Per-subagent settings: use namespaced keys such as `researcher:max_depth` in a flat mapping, or separate fields on the context type.
- A shared tool can read `lc_agent_name` from `runtime.config` metadata to branch on which agent is calling it, and can combine that with `runtime.context`.

## Tracing (LangSmith)

- Every run from a subagent or the coordinator has `lc_agent_name` in its metadata.
- In the UI, add a metadata filter with key `lc_agent_name` and the subagent name as value. Filters can be saved as named views.
- In the SDK: `client.list_runs(...)` with a `has(metadata, ...)` filter. `has(metadata, 'lc_agent_name')` matches any subagent run.

## Best practices

- **Descriptions**: be specific. The page's model is "Analyzes financial data and generates investment insights with confidence scores." Vague descriptions like "Does finance stuff" are discouraged.
- **System prompts**: detail the steps, the output format, and length limits. The page's example caps responses near 500 words.
- **Tools**: give each subagent the minimum set it needs.
- **Models**: pick per task. For example, a long-context model for document review and a numerical model for financial analysis.
- **Concise results**: tell subagents to return summaries, not raw data or intermediate calculations.

## Common patterns

- **Specialized pipelines**: separate subagents for collection, analysis, and report writing, coordinated by a main agent. Each works from a clean, task-focused context.

## Limitations and caveats

- Forked subagents cannot call `task`. They must finish the work themselves.
- Isolated subagents do not inherit the main agent's custom middleware.
- A `permissions` list on a subagent **replaces** the parent's permissions. It does not merge.
- `interrupt_on` requires a checkpointer.
- Forks and dynamic subagents are **beta**. Their APIs may change.
- A subagent that refuses cannot pass its partial state back to the parent.
- Prompt cache reuse for forks is not guaranteed.
- `excluded_middleware` cannot remove `SubAgentMiddleware`. Use the general-purpose profile setting instead.

## Related

- Async subagents: [11-async-subagents.md](11-async-subagents.md)
- Permissions: [09-permissions.md](09-permissions.md)
- Middleware: [12-middleware.md](12-middleware.md)
- Profiles: [13-harness-profiles.md](13-harness-profiles.md)
