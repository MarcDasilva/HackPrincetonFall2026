# Human-in-the-Loop (HITL)

Human-in-the-loop lets a person approve, edit, or reject tool calls before they run. It is built on **LangGraph interrupts**.

## Setup

- Set `interrupt_on=` in `create_deep_agent`. It maps tool names to interrupt configs.
- Setting `interrupt_on` adds `HumanInTheLoopMiddleware` to the stack.
- **A checkpointer is required**, so the agent state persists between the interrupt and the resume.
- `PatchToolCallsMiddleware` repairs the message history automatically if a run is cancelled or interrupted before a tool returns.
- Filesystem permission interrupts need `deepagents>=0.6.8`.
- Conditional `when` predicates need `langchain>=1.3.3`.

```python
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    interrupt_on={"edit_file": True},
    checkpointer=MemorySaver(),
)
```

The `MemorySaver` import path is from LangGraph; the docs name `MemorySaver` and `InMemorySaver` as examples of checkpointers.

The overview's example: `interrupt_on={"edit_file": True}` pauses before every edit, so you can approve, add guidance, or modify inputs.

## `interrupt_on` config shape

Each key is a tool name. Each value is one of:

- `True`: interrupt with the default decisions (approve, edit, reject, respond).
- `False`: no interrupt for this tool.
- An `InterruptOnConfig` dict:
  - `allowed_decisions`: a list restricting which decisions a reviewer can take.
  - `when` (**Python only**): a predicate that receives a `ToolCallRequest` and returns `True` to pause or `False` to auto-approve.

```python
interrupt_on = {
    "remove_file": True,
    "fetch_file": False,
    "notify_email": {"allowed_decisions": ["approve", "reject"]},
}
```

## Decision types

| Decision | Effect | Typical use |
|---|---|---|
| `approve` | Runs the tool with the agent's original arguments | Send an email exactly as drafted |
| `edit` | Runs the tool with modified arguments | Change the recipient before sending |
| `reject` | Skips the tool and returns feedback to the agent | Deny a file deletion and explain why |
| `respond` | Returns the human's message as a synthetic tool result, skipping execution | Answer an `ask_user`-style prompt |

Guidance from the page:

- **Use `reject`, not `respond`, to deny side-effecting tools.** The model may treat a `respond` message as a successful tool result.
- Keep edits to arguments small. Large changes can make the model re-plan, call the tool again, or act unexpectedly.

## Conditional interrupts

A `when` predicate controls whether a given call pauses. It inspects the call's arguments.

```python
def writes_outside_workspace(request: ToolCallRequest) -> bool:
    path = request.tool_call["args"].get("file_path", "")
    return not path.startswith("/workspace/")

interrupt_on = {
    "write_file": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "when": writes_outside_workspace,
    },
}
```

Calls where the predicate returns `False` never appear in the interrupt batch.

## Resume flow (non-streaming)

1. Create a config with a `thread_id`.
2. Call `agent.invoke(...)`.
3. Check `result.get("__interrupt__")`.
4. Read `action_requests` and `review_configs` from the first interrupt's `value`. Map each tool name to its review config.
5. Build **one decision per action**, in the same order as `action_requests`.
6. Resume with `Command(resume={"decisions": decisions})` using the **same config**.

```python
from langchain_core.utils.uuid import uuid7
from langgraph.types import Command

config = {"configurable": {"thread_id": str(uuid7())}}
result = agent.invoke({"messages": [{"role": "user", "content": "..."}]}, config=config)

if result.get("__interrupt__"):
    value = result["__interrupt__"][0].value
    action_requests = value["action_requests"]
    review_configs = value["review_configs"]
    config_map = {cfg["action_name"]: cfg for cfg in review_configs}

    decisions = [{"type": "approve"} for _ in action_requests]
    result = agent.invoke(Command(resume={"decisions": decisions}), config=config)

print(result["messages"][-1].content)
```

## Resume flow (streaming)

- Use `agent.stream(..., stream_mode=["messages", "updates"], config=config)`.
- Print tokens from `messages` mode as they arrive.
- Watch `updates` mode for a `__interrupt__` key and store the pending interrupt.
- When the stream ends with a pending interrupt, collect decisions and resume by streaming again with `Command(resume=...)`.
- Loop until the stream ends with no interrupt.
- For a standard `interrupt_on` pause, the resume payload is the flat `{"decisions": [...]}` shape.
- Parallel branches with several pending interrupts need a map from interrupt ID to resume value. The docs link to LangGraph's interrupts page for that.

## Multiple tool calls

- Approvals for several tools are **batched into one interrupt**.
- Provide exactly one decision per action, in the same order as `action_requests`.

## Rejection messages

- If you omit `message` on a `reject`, the default feedback says the tool did not run and should not be retried unless the user asks.
- For sensitive tools, pass a specific message. Say whether the agent should drop the action, ask a follow-up, or try a safer option.

## Editing arguments

When `edit` is allowed, send an `edited_action` with the tool `name` (required) and the new `args`:

```python
decisions = [{
    "type": "edit",
    "edited_action": {
        "name": action_request["name"],
        "args": {"to": "team@company.com", "subject": "...", "body": "..."},
    },
}]
```

## Subagent interrupts

- Each subagent can define its own `interrupt_on`. That **overrides** the parent's settings for that subagent.
- Handling is the same: check `__interrupt__` and resume with `Command`.
- In streaming, subagent interrupts appear in the parent's `updates` stream.
- `subgraphs=True` is only needed to stream subagent tokens and progress.

## Interrupts inside tools

A tool can call LangGraph's `interrupt()` directly and receive the resume value (for example, `{"approved": True}`). The tool then decides what to return based on that value.

## Filesystem permission interrupts

- Add a `FilesystemPermission` with `mode="interrupt"` and matching `operations` and `paths`. For example, writes under a protected folder.
- When the agent calls `write_file` or `edit_file` on a matching path, the run pauses. The action name is the filesystem tool's name.
- Resume it the same way as any tool interrupt.
- These combine with your `interrupt_on` config, so one review step can cover both.

See [09-permissions.md](09-permissions.md).

## Best practices

- Always pass a checkpointer when using HITL.
- Reuse the same `thread_id` on every resume call.
- Build decisions in the same order as `action_requests`.
- Set risk-based policies, for example:
  - High risk (delete, send): approve, edit, reject.
  - Medium risk (write): approve, reject.
  - Low risk (read, list): `False`.

## Middleware-level HITL notes

The middleware page adds:

- By default, `HumanInTheLoopMiddleware` pauses **once per model turn**. Set `interrupt_mode="per_call"` to pause once per tool call.
- Thread-level counts for limits need a checkpointer.

See [12-middleware.md](12-middleware.md).

## Related

- Secrets and sandboxes: [08-sandboxes.md](08-sandboxes.md) recommends HITL for any agent that handles injected secrets.
- Async subagent waiting state: [11-async-subagents.md](11-async-subagents.md).
