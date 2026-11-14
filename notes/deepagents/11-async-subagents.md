# Async Subagents

Async subagents let a supervisor start background tasks that return immediately, so it can keep talking to the user while they run. The supervisor can check, steer, or cancel a task at any time.

On Agent Server, subagents also **notify the supervisor** when they finish, fail, or need input.

Async subagents run on any Agent Protocol server. Notifications and webhooks **require Agent Server**.

Synchronous subagents are in [10-subagents.md](10-subagents.md).

## `AsyncSubAgent` fields

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique identifier the supervisor uses when launching tasks |
| `description` | Yes | What the subagent does. The supervisor uses it to choose a delegate |
| `graph_id` | Yes | Graph or assistant ID on the server. For LangGraph deployments, must match a graph in `langgraph.json` |
| `url` | No | Omit for ASGI transport (co-deployed, in-process). Set for HTTP transport to a remote server |
| `headers` | No | Extra request headers for remote servers, such as custom auth on self-hosted servers |
| `mode` | No | `"isolated"` (default) or `"fork"`. Controls what conversation context the subagent gets at launch |
| `update_strategy` | No | `"interrupt"` (default) or `"enqueue"`. Controls how a follow-up is sent while a run is active. Beta, requires `deepagents>=0.7.30` |
| `webhook` | No | URL the Agent Server calls when a run of this subagent finishes. Requires `deepagents>=0.7.30` |
| `notify_parent` | No | Whether the subagent may wake an idle supervisor on finish or failure. Defaults to `True`. Beta |

## Tools the supervisor gets

`AsyncSubAgentMiddleware` adds five tools when async subagents are configured:

| Tool | Purpose | Returns |
|---|---|---|
| `start_async_task` | Start a background task | Task ID immediately (the subagent's thread ID) |
| `check_async_task` | Get current status | Status, plus result, error, or pending request |
| `update_async_task` | Send follow-up instructions | Confirmation that the follow-up started or was queued |
| `cancel_async_task` | Stop a task | Confirmation |
| `list_async_tasks` | List tracked tasks, optionally filtered by status | Status of each task, no results |

## Lifecycle

- **Launch**: creates a new server thread and starts a run. Isolated mode sends only the task description. Fork mode also sends the parent's effective conversation history.
- **Check**: fetches status, and the result, error, or pending request if there is one.
- **Update**: creates a new run on the same thread. The task ID does not change.
  - With the default `"interrupt"` strategy, the previous run is interrupted and the subagent restarts with the full conversation history plus the new instructions.
- **Enqueue update**: with `update_strategy="enqueue"`, the new run waits behind the current one. The task reads `pending` until it starts. Cancelling also cancels earlier active runs.
- **Cancel**: calls `runs.cancel()` on the server and marks the task `"cancelled"`.
- **List**: fetches live status for non-terminal tasks in parallel. Terminal statuses (`success`, `error`, `timeout`, `cancelled`, `interrupted`) come from cache.

## Notifications

On Agent Server, a finished or failed subagent wakes an idle supervisor with a new run, if both are on the same deployment and the subagent is a deep agent.

- A subagent waiting for input does **not** wake the supervisor. The supervisor sees that on its next run.
- While the supervisor is busy, it receives notifications before its next model call.
- Notifications arrive as `HumanMessage` objects with metadata: `source` set to `"async_subagent"`, and a `TaskEvent` containing `task_id`, `agent_name`, `status`, and `run_id`. Read them with `get_notification_metadata`.
- Notifications can include multimodal media.
- Requires `deepagents>=0.7.26`. Metadata requires `>=0.7.33`.

## Waiting for input

When a subagent pauses through `interrupt()` or human-in-the-loop:

- `check_async_task` and `list_async_tasks` report `waiting`.
- Only `check_async_task` returns the pending interrupts.
- The user answers **on the subagent's own thread**, where the task ID is the thread ID, by resuming the run with the interrupt ID.
- The supervisor **cannot** answer on the user's behalf.
- Updating a waiting task **drops** its pending request.
- Cancelling it only marks it `"cancelled"`.

## Model refusals (`deepagents>=0.7.33`)

If a subagent run ends in a model refusal, the supervisor receives a short result saying so, not the refusal text.

## Launch modes

- **`isolated` (default)**: starts fresh with only the task description. Use for most tasks.
- **`fork` (experimental)**: receives a snapshot of the parent's conversation at launch, plus the task.
  - If the parent compacted its history, the snapshot contains the compacted context.
  - Later parent messages are not forwarded.
  - Fork mode copies conversation messages only, not checkpoint history or full state.
  - Metadata links the new thread to its supervisor but does not transfer context.
  - For prompt-cache reuse, the remote agent must match the parent's model, system prompt, tools, and prompt-processing middleware. Matching does not guarantee cache hits.

## State management

Task metadata lives in a dedicated **`async_tasks` state channel**, separate from message history. It survives the summarization that deep agents apply when context fills.

Each tracked task records:

- task ID
- agent name
- thread ID
- run ID
- status
- timestamps: `created_at`, `last_checked_at`, `last_updated_at`

Subagent threads are created with `metadata={"parent_thread_id": ...}`.

- Use it to find a supervisor's subagent threads with a thread search, or to read the parent thread from a subagent's graph factory.
- Anyone with access to a thread can edit its metadata, so verify access before relying on it.
- Example use: a subagent reuses the supervisor's thread-scoped sandbox.

## Transports and topologies

- **ASGI (no `url`)**: in-process calls, no network latency, no extra auth. Both graphs must be registered in the same `langgraph.json`. Recommended default.
- **HTTP (`url` set)**: network calls to a remote server. Authentication for LangGraph deployments uses `LANGSMITH_API_KEY` or `LANGGRAPH_API_KEY`. Self-hosted servers may use other mechanisms. Suited to independent scaling, different resource profiles, or separate teams.

Deployment shapes:

- **Single deployment**: all agents co-deployed with ASGI. Recommended starting point.
- **Split deployment**: supervisor and subagents on separate servers, connected by HTTP.
- **Hybrid**: some subagents co-deployed through ASGI, others remote through HTTP.

## Configuration example (shape)

The docs show two `AsyncSubAgent` specs passed as `subagents` to `create_deep_agent`: a `researcher` and a `coder`. One uses ASGI (no URL); the other shows a commented-out HTTP URL.

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    subagents=[
        {
            "name": "researcher",
            "description": "Researches a topic and returns sourced findings.",
            "graph_id": "researcher",
        },
        {
            "name": "coder",
            "description": "Writes and tests code changes.",
            "graph_id": "coder",
            # "url": "https://coder.example.com",  # HTTP transport
        },
    ],
)
```

This is an illustrative shape built from the field list, not a verbatim copy of the docs.

`langgraph.json` registers `supervisor`, `researcher`, and `coder` graphs in one file for a co-deployed setup.

Other documented examples (described, not reproduced):

- **Webhook, no parent wake-up**: a `researcher` spec with a `webhook` URL and `notify_parent=False`, so the application delivers results instead of the supervisor.
- **Answering a waiting subagent**: a helper gets the subagent thread, reads its first pending interrupt, and resumes the run with the answer.
- **Reading notifications**: a loop checks each message's notification metadata and prints the agent name and status.
- **Finding subagent threads**: a helper searches threads by `parent_thread_id`, and a graph factory reads the parent thread ID from run config.
- **Fork mode**: a `drafter` spec with `mode: "fork"`.

## Worker pool

- Local dev: `langgraph dev --n-jobs-per-worker 10`.
- Each active run takes a worker slot. A supervisor with 3 subagent tasks needs 4 slots.
- Launches queue or hang when the pool is exhausted. Increase `--n-jobs-per-worker`.

## Prompt guidance

The docs suggest a system-prompt addition that tells the supervisor to return control to the user after launch, and never check immediately.

## Best practices

- Size the worker pool for concurrent runs.
- Write specific, action-oriented descriptions. A specific description helps the supervisor pick correctly.
- Use thread IDs to match subagent traces to the supervisor's trace. On the same deployment, subagents receive the supervisor's trace headers, and a subagent can adopt them to nest its runs under the supervisor's trace.
- Use `isolated` mode unless the subagent needs established context.

## Troubleshooting

- **Supervisor polls right after launch**: notifications make polling unnecessary. Reinforce this in the system prompt.
- **Stale status in history**: statuses in conversation history are stale. Tell the supervisor to re-check before reporting.
- **Task ID errors**: pass the task ID in full. Truncation is usually model-specific. Try another model, or tell the supervisor never to abbreviate it.
- **Launches queue or hang**: the worker pool is probably exhausted.

## Limitations

- **Beta**: `update_strategy`, `notify_parent`, the `waiting` status, task notifications, and tagging. These may change between releases. Fork mode is experimental.
- **Agent Server only**: notifications, webhooks, and waking an idle supervisor require Agent Server. Only deep-agent subagents on the same deployment can wake an idle supervisor.
- **Waiting subagents** don't wake the supervisor. Updating or cancelling them has the side effects above.
- **Interrupting updates**: the default `interrupt` strategy restarts the subagent from full history, so the previous run's work is lost.
- **Enqueued updates**: if the current run pauses for input before the follow-up starts, the follow-up still starts, and the pending request is dropped.
- **Fork limits**: later parent messages are not forwarded. Checkpoint history and full state are not copied. Cache hits depend on matching configuration and the provider.
- **Co-deployment**: ASGI transport requires both graphs in the same `langgraph.json`.
- **Metadata trust**: thread metadata can be edited by anyone with thread access.
- **Worker capacity**: each active run uses a slot, and too few slots cause queued launches.
