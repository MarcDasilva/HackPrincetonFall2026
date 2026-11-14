# Context Management

Long agent runs fill the context window. Deep Agents manages this in four layers, according to the overview page: **skills**, **memory**, **summarization and offloading**, and **prompt caching**. Planning and subagents also reduce context growth.

## The four parts of context (overview)

- **Input context**: system prompt, memory, skills, and tool prompts.
- **Compression**: built-in offloading and summarization of history and large results.
- **Isolation**: subagents return only final results, so their intermediate work stays out of the parent context.
- **Long-term memory**: persistent virtual filesystem storage across threads.

## Skills (on-demand instructions)

- Skill metadata (`name` and `description`) loads at startup. Full `SKILL.md` content loads only when needed.
- This is progressive disclosure. See [14-skills.md](14-skills.md).

## Memory (always loaded)

- `memory=` files load at startup and are always present. See [15-memory.md](15-memory.md).
- Keep memory files short, since they're always in the prompt.

## Summarization

`SummarizationMiddleware` is in the default stack (position 3 in the full stack). It summarizes history when token limits are approached.

Configuration from the middleware page:

```python
SummarizationMiddleware(
    model=...,
    backend=...,
    trigger=("tokens", 100000),
    keep=("messages", 20),
)
```

- `trigger` sets when summarization happens. Accepts `("tokens", n)` and `("fraction", ...)`. Multiple triggers combine with OR.
- `keep` sets how many recent messages to keep.
- `summarizer=` (`deepagents>=0.7.26`) can point to a cheaper model. It accepts a model string, a `BaseChatModel`, a `Runnable`, or a callable. Model strings and models use `summary_prompt`. Runnables and callables skip it.

Summarization can also be triggered by the agent itself. `create_summarization_tool_middleware` lets the agent trigger it at chosen points, for example between tasks.

Summarization also drops old tool results, which can affect skill-tool gating (see [14-skills.md](14-skills.md)).

## Offloading large tool outputs

- Large tool results are offloaded to the backend instead of staying in context.
- The quickstart describes this: the agent uses `write_file` and `read_file` to offload large search results.
- The default `StateBackend` stores offloaded results in state (under a path such as `/large_tool_results/`, per the backends page's example for the composite pattern).
- Large shell output from `execute` is saved to a file, and the agent reads it in pieces with `read_file`. See [08-sandboxes.md](08-sandboxes.md).
- Binary content can also be offloaded (`offload_binary_content=True`, `deepagents>=0.7.21`). See [06-filesystem-tools.md](06-filesystem-tools.md).

## Context editing (prebuilt middleware)

The middleware page lists **Context editing**: clears older tool outputs when token limits are reached. It's a LangChain prebuilt middleware, not a Deep Agents default.

## Subagent isolation

- Subagents keep their intermediate tool calls out of the parent's context. Only the final result returns.
- Fork subagents inherit the parent's history, so they don't reduce context. See [10-subagents.md](10-subagents.md).

## Prompt caching

- Automatically applied to **static system prompt sections**: base instructions, memory, and skill content.
- Applies to **Anthropic and Amazon Bedrock** models (Claude or Nova).
- Enabled by default. No configuration needed.
- Other providers: see the middleware integrations docs.
- Anthropic TTL: default `5m`. Override with `AnthropicPromptCachingMiddleware(ttl="1h")`.
- The middleware is always registered and no-ops on unsupported models.
- Memory middleware is placed late in the stack so that memory changes don't invalidate the cached prefix.
- Fork subagents can reuse the parent's cache for the matching prefix. Changing the system prompt, tools, or earlier messages shortens that prefix.

## Planning (task list)

- **Opt-in** starting in v0.7. Earlier versions included it by default.
- Enable with `middleware=[TodoListMiddleware()]`, imported from `langchain.agents.middleware`.
- Adds a `write_todos` tool.
- Task statuses: `'pending'`, `'in_progress'`, `'completed'`. Stored in agent state.
- Useful for long multi-step tasks, less capable models, and UIs that show progress.

## Model-side context tools

- **Context editing** (above).
- **LLM tool selector**: an LLM picks which tools are relevant, so fewer tool schemas sit in context.
- **Provider tool search**: defers tools to provider-side search (Anthropic and OpenAI), with `extras={"defer_loading": True}`.

## Practical checklist (synthesized from the pages)

- Keep `system_prompt` and memory short. They load on every turn.
- Put long reference material in skills, not in the system prompt.
- Give subagents the work that produces bulky intermediate output.
- Use a sandbox or backend for large artifacts, and return only summaries to the parent.
- Pin the system prompt across turns to keep the prompt cache warm.
- Set summarization `trigger` and `keep` to fit the model's window.

## Related

- Middleware stack and ordering: [12-middleware.md](12-middleware.md)
- Backends for offloading: [07-backends.md](07-backends.md)
- Streaming (how to watch context grow): [17-streaming.md](17-streaming.md)
