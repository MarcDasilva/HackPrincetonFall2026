# `create_deep_agent`: Parameters

`create_deep_agent` is the main entry point. It returns a `CompiledStateGraph` (a LangGraph graph), so you call `.invoke`, `.stream`, and related methods on the result.

## Full parameter table

| Parameter | Type | Default | Purpose |
|---|---|---|---|
| `model` | `str \| BaseChatModel \| None` | `None` | Model as `provider:model` string, or an initialized model instance |
| `tools` | `Sequence[BaseTool \| Callable \| dict]` | `None` | Custom domain tools |
| `system_prompt` | `str \| SystemMessage \| None` | `None` | Custom instructions. A `SystemMessage` with content blocks is preserved |
| `middleware` | `Sequence[AgentMiddleware]` | `()` | Extra middleware merged into the stack |
| `subagents` | `Sequence[SubAgent \| CompiledSubAgent \| AsyncSubAgent]` | `None` | Delegated subagents |
| `skills` | `list[str]` | `None` | Skill source directory paths |
| `memory` | `list[str]` | `None` | AGENTS.md files loaded at startup |
| `permissions` | `list[FilesystemPermission]` | `None` | Path-level filesystem access control |
| `backend` | `BackendProtocol` | `StateBackend` | Filesystem backend |
| `interrupt_on` | `dict[str, bool \| InterruptOnConfig]` | `None` | Tools that pause for human approval |
| `response_format` | `ResponseFormat \| type \| dict` | `None` | Structured output schema |
| `state_schema` | `type[DeepAgentState]` | `None` | Custom graph state |
| `context_schema` | `type[ContextT]` | `None` | Per-run runtime context (user IDs, API keys, flags) |
| `checkpointer` | `Checkpointer` | `None` | Required for human-in-the-loop |
| `store` | `BaseStore` | `None` | Store used by `StoreBackend` |
| `debug` | `bool` | `False` | Debug mode |
| `name` | `str` | `None` | Agent name |
| `cache` | `BaseCache` | `None` | Cache |

Source: the customization reference table. The page was truncated, so the table may not be complete.

## Parameter notes

### `model`

- A `provider:model` string, resolved through `init_chat_model`, or an initialized model object.
- Example strings from the docs: `anthropic:claude-sonnet-4-6`, `openai:gpt-5.4`, `google_genai:gemini-4-hydrogen`.
- See [04-models.md](04-models.md).

### `tools`

- Plain Python functions with docstrings, LangChain `BaseTool` objects, or dict-form provider tools (for example, `{"google_search": {}}`).
- Built-in filesystem and subagent tools are always added on top of these.
- See [05-tools-and-mcp.md](05-tools-and-mcp.md).

### `system_prompt`

- A string, or a `SystemMessage` with structured content blocks.
- The SDK adds its own base prompts (for filesystem, planning, and subagent tools). The harness profile can change the base prompt; see [13-harness-profiles.md](13-harness-profiles.md).
- Subagent dict specs accept string prompts only.

### `middleware`

- Extra middleware. Each instance is matched to built-in entries by its `.name` and replaces the built-in one; non-matching middleware is inserted after `PatchToolCallsMiddleware`.
- Overrides replace the default; they are not merged. The replacement must be fully configured.
- See [12-middleware.md](12-middleware.md).

### `subagents`

- Accepts dict specs, `CompiledSubAgent` objects, and `AsyncSubAgent` objects.
- A `general-purpose` subagent is added automatically unless you define one with that name or disable it through a profile.
- See [10-subagents.md](10-subagents.md) and [11-async-subagents.md](11-async-subagents.md).

### `skills`

- A list of **source directories** that contain skill directories. Pointing at a single skill directory loads nothing and raises no error.
- See [14-skills.md](14-skills.md).

### `memory`

- A list of file paths (such as `/memories/AGENTS.md`) loaded at startup.
- Always loaded, unlike skills. See [15-memory.md](15-memory.md).

### `permissions`

- A list of `FilesystemPermission` rules, evaluated in order. See [09-permissions.md](09-permissions.md).

### `backend`

- Must implement `BackendProtocol`. Pass an instance, not a factory (factories are deprecated as of 0.5.0).
- Default `StateBackend()`. See [07-backends.md](07-backends.md).

### `interrupt_on`

- Maps tool names to `True`, `False`, or a config dict. Requires a `checkpointer`. See [16-human-in-the-loop.md](16-human-in-the-loop.md).

### `response_format`

- A structured output schema. The customization page was truncated here, so details are limited.

### `state_schema`

- A custom state type that extends `DeepAgentState`.

### `context_schema`

- A type for per-run runtime context. Values such as user IDs or feature flags are read through `runtime.context` in tools and middleware. The context propagates automatically to subagents.

### `checkpointer`

- Needed for human-in-the-loop, and for keeping state across turns in a thread. Example used in docs: `MemorySaver` or `InMemorySaver`.

### `store`

- Needed for `StoreBackend`. On LangSmith Agent Server, omit it and the platform provides one. For local development, pass `InMemoryStore()`.

## Minimal example with several parameters

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[get_weather],
    system_prompt="You are a helpful assistant",
)
```

The docs write the model string as a placeholder (`<provider:model>`), so pick a real one from [04-models.md](04-models.md).

## Return value

`CompiledStateGraph`. Typical calls:

- `agent.invoke({"messages": [...]}, config=...)`
- `agent.stream(..., stream_mode=..., subgraphs=True, version="v2")`
- `agent.stream_events(..., version="v3")`
- `agent.update_state(config, {...})`

See [17-streaming.md](17-streaming.md).

## Things the docs say you need before creating the agent

- For skills or memory on the file backends, add the expected files to the backend first.
- For `StoreBackend`, pass `store=`.
- For human-in-the-loop, pass a `checkpointer=`.
