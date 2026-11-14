# Streaming

Deep Agents runs on LangGraph, so streaming is built in. You can stream tokens, tool calls, step-by-step progress, and subagent activity.

## Two APIs

1. **`agent.stream(...)`** with `stream_mode`, `subgraphs`, and `version`. This is the documented streaming API in the Deep Agents streaming page.
2. **`agent.stream_events(..., version="v3")`**. The streaming page calls this "the typed-projection API introduced in Deep Agents v0.6" and recommends it for new applications. It returns separate iterators for subagents, messages, tool calls, and values. The page itself does not document `stream_events`; the subagent and HITL pages do, with examples. Confirm details in the installed version.

## Enabling subgraph streaming

```python
agent.stream(..., subgraphs=True, version="v2")
```

- Each chunk then carries a namespace, `ns`, that identifies its source.
- Deep Agents examples use the tuple format. LangGraph 1.1+ also offers a unified `version="v2"` `StreamPart` dict format, which the page links to but does not detail.

## Stream modes

| Mode | What you get |
|---|---|
| `"updates"` | Step-by-step progress for the main agent and subagents |
| `"messages"` | Individual LLM tokens and tool-call or tool-result chunks, with source metadata |
| `"custom"` | User-defined events emitted with `get_stream_writer` inside tools |
| List of modes | Combine, for example `["updates", "messages", "custom"]` |

`"values"` appears only as a projection name, not as a documented stream mode.

## Chunk shapes

| `stream_mode` | With `subgraphs=True` | Without `subgraphs` |
|---|---|---|
| Single mode | `(namespace, data)` | `data` |
| Multiple modes | `(namespace, mode, data)` | `(mode, data)` |

In `version="v2"` examples, chunks are dicts with `type` and `data` keys, plus `ns` for the namespace.

## Event types

- **`updates`**: `data` maps node names to their output. An empty `ns` means the main agent. Node names include `model_request`, `model`, and `tools`.
- **`messages`**: `data` is `(token, metadata)`. Tool-call chunks appear as `tool_call_chunks` on `AIMessageChunk`. Tool results arrive as `ToolMessage`.
- **`custom`**: `data` is whatever the tool passed to the stream writer.
- **Interrupts**: appear as a `__interrupt__` key inside `updates` data. See [16-human-in-the-loop.md](16-human-in-the-loop.md).

## Namespaces

- `()` (empty): the main agent.
- `("tools:<tool_call_id>",)`: a subagent spawned by a `task` tool call.
- `("tools:<tool_call_id>", "model_request:<id>")`: a model request node inside a subagent.

To route events, check for a segment that starts with `tools:`.

## Subagent streaming

- **Progress**: `updates` mode shows which subagent node is running. Subagent results return as `tool` messages on the main agent's `tools` node.
- **Tokens**: `messages` mode streams tokens from the main agent and from each subagent, tagged by namespace.
- **Tool calls**: streamed as `tool_call_chunks` with the name and incremental args. Results appear as `ToolMessage` entries.
- **Custom events**: subagent tools call `get_stream_writer()` to emit progress such as `{"status", "progress"}`.

## `stream_events` (v3) subagent handles

From the subagents page:

```python
stream.interleave("messages", "subagents")
```

- Yields coordinator messages and subagent handles together.
- Each subagent handle exposes `.name`, `.messages`, `.tool_calls`, `.output`, and `.status`.
- The page's example uses a coordinator whose system prompt forces delegation to a `research-agent`.

## Lifecycle tracking pattern

The streaming page describes deriving subagent state from the stream:

1. **Pending**: a `task` tool call appears in the main agent's `model` node.
2. **Running**: the first event from a `tools:` namespace. The pregel task ID differs from the `tool_call_id`, so matching is approximate.
3. **Complete**: a `ToolMessage` on the main `tools` node whose `tool_call_id` matches.

## Human-in-the-loop with streaming

- Set `interrupt_on` to require approval for sensitive tool operations.
- Detect pauses by checking `updates` chunks for `__interrupt__`.
- Resume with the same flat `{"decisions": [...]}` payload used with `.invoke()`.

## Frontend streaming

The production guide says `useStream` is available for React, Vue, Svelte, and Angular. It streams messages, subagent progress, and custom state.

- Point `apiUrl` at your Agent Server and set the `assistantId`.
- Configure reconnection so users don't lose progress if the connection drops.
- For agents that spawn many subagents, the guide recommends a high `recursionLimit` (its example uses 10000) and enabling subgraph streaming.

## Providers in examples

The streaming page shows the same code for Google, OpenAI, Anthropic, OpenRouter, Fireworks, Baseten, and Ollama. Only the `model` argument changes.

## Related

- Subagent streaming details: [10-subagents.md](10-subagents.md)
- Async subagent notifications (not streaming, but the other way subagents reach the supervisor): [11-async-subagents.md](11-async-subagents.md)
- Production frontend notes: [19-production-and-deployment.md](19-production-and-deployment.md)
