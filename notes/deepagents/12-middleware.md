# Middleware

Middleware is how Deep Agents adds behavior to the agent loop: filesystem tools, subagents, summarization, memory, skills, prompt caching, human-in-the-loop, and more. You customize the stack with the `middleware=` parameter of `create_deep_agent`.

Deep Agents middleware is added through the customization API, not by passing it straight to `create_agent`.

## Built-in Deep Agents middleware

| Middleware | Module | What it does |
|---|---|---|
| `FilesystemMiddleware` | `deepagents.middleware.filesystem` | Filesystem tools. Options: `backend`, `system_prompt`, `custom_tool_descriptions`, `tools` (allowlist). Also `offload_binary_content` |
| `SubAgentMiddleware` | `deepagents.middleware.subagents` | Adds the `task` tool, which exposes only the subagents you pass in. General-purpose subagent auto-added unless a profile disables it |
| `AsyncSubAgentMiddleware` | `deepagents.middleware.async_subagents` | Async subagent tools (`start_async_task` etc.). Only when async subagents exist |
| `SummarizationMiddleware` | `deepagents.middleware.summarization` | Summarizes history near token limits |
| `PatchToolCallsMiddleware` | `deepagents.middleware.patch_tool_calls` | Repairs dangling tool calls after interruptions or malformed arguments |
| `SkillsMiddleware` | `deepagents.middleware.skills` | Skill catalog and loading. Only with `skills` |
| `MemoryMiddleware` | `deepagents.middleware.memory` | Loads memory files (AGENTS.md). Only with `memory` |
| `HumanInTheLoopMiddleware` | (LangChain) | Pauses for approval. Only with `interrupt_on` |
| `UnsupportedContentMiddleware` | `deepagents.middleware.unsupported_content` | Replaces unsupported multimodal content with a text placeholder |
| `ModelRefusalMiddleware` | (LangChain) | Raises `ModelRefusalError` on refusals |
| Prompt caching | `AnthropicPromptCachingMiddleware`, `BedrockPromptCachingMiddleware` | Always registered; ignored on unsupported models |
| `RubricMiddleware` | `deepagents.middleware.rubric` | Self-evaluation loop against a rubric (`deepagents>=0.6.5`) |

## Default stack (full, in order)

From the customization page:

1. `FilesystemMiddleware`. Includes permission enforcement when `permissions` is passed.
2. `SubAgentMiddleware`. Only with at least one synchronous subagent.
3. `SummarizationMiddleware`.
4. `PatchToolCallsMiddleware`.
5. `AsyncSubAgentMiddleware`. Only with async subagents.
6. Your `middleware=` entries.
7. Harness profile extras.
8. `SkillsMiddleware`. Only with `skills`.
9. Prompt caching: `AnthropicPromptCachingMiddleware` and `BedrockPromptCachingMiddleware`. Both always registered; each ignores unsupported models.
10. `MemoryMiddleware`. Only with `memory`. Placed late so it doesn't invalidate the cache prefix.
11. `HumanInTheLoopMiddleware`. Only with `interrupt_on`.
12. `UnsupportedContentMiddleware`.
13. `ModelRefusalMiddleware`. Raises `ModelRefusalError` on refusal.
14. Excluded-tool filtering, if the profile lists excluded tools.

## Bare stack (model only)

When there are no extra options, the stack is smaller:

1. `FilesystemMiddleware`
2. `SubAgentMiddleware`. The general-purpose subagent is auto-added unless a profile disables it.
3. `SummarizationMiddleware`
4. `PatchToolCallsMiddleware`
5. Prompt caching middleware (always registered)
6. Harness profile extras, if defined
7. `UnsupportedContentMiddleware`
8. `ModelRefusalMiddleware`
9. Excluded-tool filtering, if the profile defines it

## Synchronous subagent stack

Similar in shape to the main agent: filesystem, summarization, patch-tool-calls, profile extras, skills, caching, and optional permissions. It has **no** `SubAgentMiddleware`, so only the parent exposes the `task` tool.

A subagent's `interrupt_on` is forwarded to `create_agent`.

## Merge rules (important)

- Each middleware instance is matched to built-in entries by its **`.name`**.
- A match **replaces** the built-in instance in place (requires `deepagents>=0.7`).
- Non-matching middleware is inserted after `PatchToolCallsMiddleware`.
- **Overrides replace; they do not merge.** Your replacement must be fully configured.
- A custom `FilesystemMiddleware` does **not** inherit `backend=` or `permissions=` from `create_deep_agent`. Pass them directly.
- The general-purpose subagent inherits main-agent middleware overrides.
- Declarative subagents do **not** inherit them. Pass overrides in each subagent's own `middleware` field.

## Override examples

### Summarization triggers

```python
SummarizationMiddleware(
    model=...,
    backend=...,
    trigger=("tokens", 100000),
    keep=("messages", 20),
)
```

- `trigger` also accepts `("fraction", ...)`.
- Multiple triggers combine with **OR** semantics.

### Cheaper summarizer (`deepagents>=0.7.26`)

`summarizer=` accepts a model string, a `BaseChatModel`, a `Runnable`, or a callable.

- Model strings and models use `summary_prompt`.
- Runnables and callables skip `summary_prompt`.

### Prompt cache TTL

```python
AnthropicPromptCachingMiddleware(ttl="1h")
```

Default TTL is `5m`.

### Filesystem tool allowlist (`deepagents>=0.7`)

```python
FilesystemMiddleware(backend=..., tools=["read_file", "ls", "glob", "grep"])
```

A read-only agent.

### Custom skill catalog template

```python
SkillsMiddleware(backend=..., sources=[...], system_prompt=template)
```

- The template **must** include `{skills_locations}`, `{skills_list}`, and `{skills_load_warnings}`. A missing slot raises `ValueError`.
- Don't also pass `skills=`.

### Suppress the skill catalog

```python
SkillsMiddleware(..., system_prompt=None)
```

Skills stay in `state["skills_metadata"]`. You maintain any hand-written descriptions yourself.

## Prebuilt LangChain middleware

The middleware page lists these prebuilt options (available in LangChain's `create_agent`, and usable with Deep Agents):

| Middleware | Purpose |
|---|---|
| Tool error | Converts tool exceptions into error `ToolMessage`s (requires `langchain>=1.3.14`) |
| Tool retry | Retries tool calls with exponential backoff |
| Model retry | Retries model calls with exponential backoff |
| Model fallback | Falls back to alternative models |
| Model refusal | Raises `ModelRefusalError` on refusals (requires `langchain>=1.4.9`) |
| Summarization | Summarizes history near token limits |
| Human-in-the-loop | Pauses for tool-call approval; needs a checkpointer |
| Model call limit | Caps model calls per thread or run |
| Tool call limit | Caps tool calls globally or per tool |
| PII detection | Redact, mask, block, or hash sensitive data |
| To-do list | Adds `write_todos` planning |
| LLM tool selector | Uses an LLM to pick relevant tools |
| Model router | Picks a model per run (beta, `langchain>=1.5.0`) |
| Auto mode | Blocks risky tool calls via a decision model (beta, `langchain>=1.5.0`) |
| Provider tool search | Defers tools to provider-side search (Anthropic, OpenAI) |
| Shell tool | Persistent shell session with execution policies |
| File search | Glob and Grep tools |
| Context editing | Clears older tool outputs when token limits are reached |
| LLM tool emulator | Simulates tool results with an LLM for testing |

Provider-specific middleware:

- **Anthropic**: prompt caching, bash, text editor, memory, file search.
- **AWS**: prompt caching for Bedrock.
- **OpenAI**: content moderation.

## Ordering rules

- **Tool error + tool retry**: place retry **inner** (later in the `middleware` list) with `on_failure="error"`, so exceptions reach the tool-error middleware after retries are exhausted.
- **Model fallback + model refusal**: list `ModelFallbackMiddleware` **before** `ModelRefusalMiddleware`, so a refusal triggers fallback.
- **Custom handler with fallback**: a `@wrap_model_call` handler goes **before** `ModelFallbackMiddleware`, so it catches `ModelRefusalError` only after all models refuse.

Example from the docs:

```python
@wrap_model_call
def reply_on_refusal(request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
    try:
        return handler(request)
    except ModelRefusalError:
        return ModelResponse(result=[AIMessage("I cannot help with that request.")])

agent = create_agent(
    model="claude-sonnet-5-5",
    tools=[],
    middleware=[
        reply_on_refusal,
        ModelFallbackMiddleware("gpt-6.1-sol"),
        ModelRefusalMiddleware(),
    ],
)
```

This example uses `create_agent` (LangChain), not `create_deep_agent`.

## Custom middleware

- Hooks use the `@wrap_tool_call`, `@wrap_model_call` style decorators. The docs example for a tool hook receives `request` and `handler`, logs something, and calls `handler(request)`.
- The `a`-prefixed variants are the async versions. Use them for async tools and graph factories (see [19-production-and-deployment.md](19-production-and-deployment.md)).
- Full custom middleware hooks are documented in LangChain's custom middleware page, not in the Deep Agents pages.

**Warning from the docs**: do not mutate instance attributes inside hooks. Store state in the **graph state** instead. Subagents, parallel tools, and concurrent invocations can cause race conditions on instance attributes.

## State and checkpointers

- **Model router** stores its choice in agent state under `model_route`.
- **Human-in-the-loop** requires a checkpointer. By default it pauses once per model turn. Set `interrupt_mode="per_call"` to pause once per tool call.
- **Thread-level limits** (`thread_limit` on model-call and tool-call limits) need a checkpointer to persist counts across runs.
- **Refused replies** are not saved to the thread when you catch `ModelRefusalError`, so the conversation can continue.
- **Persistent shell sessions** don't currently work with interrupts.

## Interpreters

`CodeInterpreterMiddleware` from `langchain_quickjs` adds an `eval` tool. See [08-sandboxes.md](08-sandboxes.md) and [10-subagents.md](10-subagents.md).

## Related

- Tool-level details: [05-tools-and-mcp.md](05-tools-and-mcp.md)
- Profiles that add middleware: [13-harness-profiles.md](13-harness-profiles.md)
- Context management middleware: [18-context-management.md](18-context-management.md)
