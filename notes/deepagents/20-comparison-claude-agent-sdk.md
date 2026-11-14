# Comparison: Deep Agents vs. Claude Agent SDK

The LangChain comparison page is dated April 16, 2026. It positions Deep Agents against Anthropic's Claude Agent SDK. This is the vendor's own comparison, so read it as their framing, not an independent review.

The page says Deep Agents is used in production by OpenSWE and LangSmith Fleet.

## At a glance

| Dimension | Deep Agents | Claude Agent SDK |
|---|---|---|
| Where the agent runs | Inside a sandbox, or outside one while executing commands remotely | Inside a sandbox |
| Execution backend | Pluggable: local, virtual filesystem, remote sandbox, or custom. Managed Deep Agents uses one managed sandbox declared in the project | Local filesystem of the sandbox it runs in |
| Model provider | Any (Anthropic, OpenAI, Google, 100+ others) | Claude, via Anthropic, Bedrock, Vertex, or Azure |
| Per-provider/model tuning | Harness profiles (beta): bundles of system prompt, tool, middleware, and subagent tweaks, registered per provider or model | Configured in code at each model call site |
| Deployment | Default is Managed Deep Agents (`mda deploy` on LangSmith), or self-host a standalone image via `langgraph build` | Self-hosted. You build the server, auth, and streaming. Claude managed agents is a separate product |
| Multi-tenancy | Built in: scoped threads, per-user sandboxes, RBAC. Managed adds identity and per-user connections | You build it yourself |
| License | MIT | MIT (Claude Code itself is proprietary) |

## Main differences (as the page describes them)

### 1. Agent and execution environment

- Two patterns for connecting agents to sandboxes: run the agent **inside** the sandbox, or run it **outside** and use the sandbox as a tool.
- The Claude Agent SDK supports only the first. Claude managed agents uses a decoupled model.
- Deep Agents supports both: inside a sandbox, in a long-lived container with a remote sandbox as a tool, or with a virtual filesystem for tests or a custom backend.
- In Managed Deep Agents, LangSmith owns the sandbox lifecycle. It creates, snapshots, and stops the sandbox when idle.

### 2. Multi-tenancy

- In the Claude Agent SDK, the agent is tied to its sandbox. Per-user isolation needs your own API wrapper that creates a sandbox per user, tracks ownership, and tears it down.
- Deep Agents configures sandboxes per user or per assistant, with scoped threads, run history, and RBAC.
- The LangSmith sandbox includes an auth proxy, so end users can call third-party APIs without per-user credential provisioning.
- Managed Deep Agents adds caller identity and OAuth-based connections, so users authorize their own accounts.

### 3. Production agent server

- Self-hosted Claude Agent SDK apps need your own HTTP, WebSocket, or SSE server for invoking the agent, streaming tokens, and managing threads.
- Deep Agents deployments include an agent server with streaming, thread management, run history, webhooks, and authentication.
- Managed Deep Agents runs on Agent Server without you operating it, and adds the Agent Server API and an MCP endpoint.

### 4. Managed cloud vs self-hosted

- Claude Agent SDK deployments are self-hosted. The SDK and Claude managed agents are separate products. SDK code does not deploy directly to the managed offering.
- Deep Agents runs in two modes with the same tools, middleware, and subagents:
  - **Managed**: LangSmith runs the backend, store, and checkpointer. Instructions, skills, and memory live in project files and Context Hub.
  - **Self-hosted**: run the SDK yourself, or use `langgraph build` to produce a standalone Docker image.
- The page includes a migration guide for moving SDK-built agents to the managed runtime.
- For a no-code, any-provider option, the page points to LangSmith Fleet. It notes Claude managed agents is limited to the Anthropic ecosystem.

### 5. LLM and infrastructure coupling

- The Claude Agent SDK bundles model, backend, and deployment, and optimizes support across all three.
- Deep Agents lets you pick the model provider, execution backend, and deployment target independently.

### 6. Ecosystems

- The Claude Agent SDK is built for Claude and Anthropic's product surface.
- Deep Agents integrates with the broader LangChain ecosystem: LangSmith for observability, evaluation, and deployment, and any model provider.

## The page's recommendations

- **Choose Deep Agents** for model and infrastructure flexibility, built-in multi-tenant deployment, and the option to run managed or self-hosted with the same agent code.
- **Choose the Claude Agent SDK** if you're already invested in Anthropic's ecosystem and willing to build the API, auth, and multi-tenant layers yourself.

## Reading this critically

- The comparison is written by LangChain. Claims such as "built in" features and production users are the vendor's.
- The Claude Agent SDK side of the table is a summary the page gives. It isn't verified in these notes against Anthropic's own docs.
- Feature availability differs between managed and self-hosted paths, and between beta and stable features (harness profiles and async subagents have beta parts).

## Related

- Deployment details: [19-production-and-deployment.md](19-production-and-deployment.md)
- Sandboxes: [08-sandboxes.md](08-sandboxes.md)
