# Deep Agents: Overview

## What it is

Deep Agents is an open source **agent harness** for complex, multi-step work. The README calls it "the batteries-included agent harness." It runs out of the box, and you can extend, override, or replace any component piece by piece without forking.

The docs describe it as the same core tool-calling loop used by other agent frameworks, plus built-in capabilities that let the agent handle long tasks:

- Planning (opt-in, see [18-context-management.md](18-context-management.md))
- A virtual filesystem for context
- Subagent spawning for isolated work
- Long-term memory across sessions
- Human approval of tool calls

## Where it sits in the LangChain stack

From the README's layering FAQ:

- **LangGraph**: the graph runtime. Provides durable execution, streaming, persistence, checkpointing.
- **LangChain `create_agent`**: a minimal agent harness built on LangGraph.
- **Deep Agents**: a more opinionated harness on top of `create_agent`. It bundles filesystem tools, subagents, context management, and skills.

The overview says: for custom agents without these features, use LangChain's `create_agent` or a custom LangGraph workflow instead.

## Two ways to run it

The overview page describes two modes:

1. **Managed Deep Agents**: LangSmith runs the harness, Agent Server, sandboxes, and schedules for you. Linked from the docs as `langsmith/python/managed-deep-agents-overview`.
2. **Deep Agents SDK** (this is what these notes cover): the same harness, self-hosted, with maximum flexibility. You host agents yourself or run a custom Agent Server.

Use the SDK when you:

- run the agent in your own process or container,
- need a custom backend, store, or checkpointer,
- want an Agent Server you configure yourself.

## Built-in capabilities (from the overview)

The docs group capabilities into four categories:

- **Execution environment**: tools and MCP, virtual filesystem, filesystem permissions, code execution, streaming.
- **Context management**: skills, memory, summarization and offloading, prompt caching.
- **Delegation**: task planning, subagents.
- **Steering**: human-in-the-loop.

"Optional" capabilities are task planning and skills.

## Core principles (README)

- **Opinionated**: defaults are tuned for long-horizon, multi-step work.
- **Extensible**: change any component without forking.
- **Model-agnostic**: works with any model that supports tool calling, including frontier, open-weight, and local models.
- **Production-ready**: built on LangGraph for streaming, persistence, and checkpointing. Pairs with LangSmith for tracing, evaluation, and deployment.

## Feature list (README)

- **Sub-agents**: delegate tasks to agents with isolated context windows.
- **Filesystem**: read, write, edit, search across pluggable local, sandboxed, or remote backends.
- **Context management**: summarize long threads and offload tool outputs to disk.
- **Shell access**: run commands in the sandbox of your choice.
- **Persistent memory**: pluggable state and store backends for cross-session recall.
- **Human-in-the-loop**: approve, edit, or reject tool calls before they run.
- **Skills**: load reusable behaviors on demand.
- **Tools**: bring your own functions or any MCP server.

## Deep Agents Code

A prebuilt terminal coding agent, similar to Claude Code or Cursor, that works with any LLM. Install:

```bash
curl -LsSf https://langch.in/dcode | bash
```

The docs mention it has its own section (`oss/deepagents/code/overview`), a `--sandbox` flag with `--sandbox-id` and `--sandbox-setup` options, and an ACP integration for use in code editors such as Zed.

## Security stance

The README says the project follows a **"trust the LLM"** model. The agent can do anything its tools allow, so boundaries must be enforced at the tool or sandbox level. The notes in [09-permissions.md](09-permissions.md), [08-sandboxes.md](08-sandboxes.md), and [16-human-in-the-loop.md](16-human-in-the-loop.md) cover how.

## Model support

Frontier APIs, open-weight models hosted by providers, and self-hosted models (Ollama, vLLM, llama.cpp) all work. The only hard requirement in the docs is **tool calling** support. See [04-models.md](04-models.md).

## Custom orchestration

Any LangGraph `CompiledStateGraph` can be used as a subagent. See [10-subagents.md](10-subagents.md).

## Links from the README

- Documentation: `docs.langchain.com/oss/python/deepagents/overview`
- API reference: `reference.langchain.com/python/deepagents/`
- Examples: `github.com/langchain-ai/deepagents/tree/main/examples`
- Changelog: `libs/deepagents/CHANGELOG.md` in the repo
- Development guide: `libs/DEVELOPMENT.md`
- Discussions: LangChain forum, deep-agents category
- LangChain Academy
- "Going to production" guide

## Repo facts

- Python package lives in `libs/deepagents` inside the `langchain-ai/deepagents` repo.
- JavaScript version: `github.com/langchain-ai/deepagentsjs`, npm package `deepagents` (the search results showed version `1.10.2` on jsDelivr).
