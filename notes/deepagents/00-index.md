# Deep Agents SDK Notes: Index

These notes cover the LangChain **Deep Agents** SDK (Python package `deepagents`), gathered from the official docs at docs.langchain.com and the GitHub README on 2026-11-13.

They live in `notes/deepagents/`. The other files in `notes/` belong to a separate ChatOverflow set and are not part of these notes.

Read in this order if you're new, or jump to a topic.

| File | Topic |
|---|---|
| [01-overview.md](01-overview.md) | What Deep Agents is, how it's positioned, core principles |
| [02-installation-and-quickstart.md](02-installation-and-quickstart.md) | Installing, API keys, first agent, LangSmith tracing |
| [03-create-deep-agent-parameters.md](03-create-deep-agent-parameters.md) | Every parameter of `create_deep_agent` with types and defaults |
| [04-models.md](04-models.md) | Model strings, provider setup, suggested models, eval scores, OpenAI Responses API, runtime model selection |
| [05-tools-and-mcp.md](05-tools-and-mcp.md) | Custom tools, MCP tools, built-in tools |
| [06-filesystem-tools.md](06-filesystem-tools.md) | `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute`; multimodal reads; hiding and restricting tools |
| [07-backends.md](07-backends.md) | All built-in backends, custom backend protocol, namespace factories, routing |
| [08-sandboxes.md](08-sandboxes.md) | Sandbox providers, lifecycle patterns, `execute`, secrets, security |
| [09-permissions.md](09-permissions.md) | `FilesystemPermission` rules, evaluation order, interrupt mode, subagent inheritance |
| [10-subagents.md](10-subagents.md) | Synchronous subagents, the `task` tool, forks, dynamic subagents, general-purpose subagent |
| [11-async-subagents.md](11-async-subagents.md) | Background subagents, launch/check/update/cancel tools, notifications, deployment topologies |
| [12-middleware.md](12-middleware.md) | Built-in middleware, default stack ordering, merge rules, overrides, custom middleware warnings |
| [13-harness-profiles.md](13-harness-profiles.md) | `HarnessProfile`, per-model tuning, excluded tools/middleware |
| [14-skills.md](14-skills.md) | `SKILL.md` format, `skills=`, precedence, pinning, skill tools |
| [15-memory.md](15-memory.md) | `memory=`, AGENTS.md, scopes, cross-thread memory, consolidation |
| [16-human-in-the-loop.md](16-human-in-the-loop.md) | `interrupt_on`, decisions, resume flow, conditional interrupts |
| [17-streaming.md](17-streaming.md) | Stream modes, subgraph streaming, namespaces, subagent streaming |
| [18-context-management.md](18-context-management.md) | Skills, memory, summarization, offloading, prompt caching, planning |
| [19-production-and-deployment.md](19-production-and-deployment.md) | Managed vs self-hosted, Agent Server, multi-tenancy, auth, PII, frontend |
| [20-comparison-claude-agent-sdk.md](20-comparison-claude-agent-sdk.md) | How the docs position Deep Agents against the Claude Agent SDK |
| [21-python-api-symbols.md](21-python-api-symbols.md) | Module map of the public Python API |
| [22-sources-and-caveats.md](22-sources-and-caveats.md) | Where the info came from, what's uncertain, what didn't load |

## Quick facts

- **Package:** `deepagents` (Python). Install with `uv add deepagents` or `pip install deepagents`.
- **Main entry point:** `create_deep_agent(...)`, returns a LangGraph `CompiledStateGraph`.
- **Runtime:** built on LangChain's `create_agent` and LangGraph (durable execution, streaming, checkpoints).
- **JavaScript:** `deepagents` on npm, `createDeepAgent`. Repo: github.com/langchain-ai/deepagentsjs.
- **License:** MIT.
- **Version markers used in the docs:** the pages reference features gated on `deepagents>=0.5.x` through `>=0.7.x`. Check the version you install.
