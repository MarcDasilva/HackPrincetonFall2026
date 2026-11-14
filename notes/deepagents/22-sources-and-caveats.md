# Sources, Coverage, and Caveats

These notes were built on 2026-11-13 from public pages. This file says where the information came from and where it's weak.

## Sources used

Official pages (docs.langchain.com, Python, unless noted):

- Overview: `docs.langchain.com/oss/python/deepagents/overview`
- Quickstart: `docs.langchain.com/oss/python/deepagents/quickstart`
- Customization: `docs.langchain.com/oss/python/deepagents/customization.md`
- Harness: `docs.langchain.com/oss/python/deepagents/harness/index.html`
- Harness profiles: `docs.langchain.com/oss/python/deepagents/harness-profiles.md`
- Subagents: `docs.langchain.com/oss/python/deepagents/subagents.md`
- Async subagents: `docs.langchain.com/oss/python/deepagents/async-subagents.md`
- Backends: `docs.langchain.com/oss/python/deepagents/backends.md`
- Sandboxes: `docs.langchain.com/oss/python/deepagents/sandboxes.md`
- Permissions: `docs.langchain.com/oss/python/deepagents/permissions.md`
- Human-in-the-loop: `docs.langchain.com/oss/python/deepagents/human-in-the-loop.md`
- Models: `docs.langchain.com/oss/python/deepagents/models.md`
- Skills: `docs.langchain.com/oss/python/deepagents/skills.md`
- Memory: `docs.langchain.com/oss/python/deepagents/memory.md`
- Streaming: `docs.langchain.com/oss/python/deepagents/streaming.md`
- Middleware: `docs.langchain.com/oss/python/deepagents/middleware.md`
- Going to production: `docs.langchain.com/oss/python/deepagents/going-to-production.md`
- Comparison: `docs.langchain.com/oss/python/deepagents/comparison`
- API reference: `reference.langchain.com/python/deepagents/`

Repo:

- README: `github.com/langchain-ai/deepagents`
- Changelog and development guide are linked from the README (not read).

Other:

- JavaScript docs: `docs.langchain.com/oss/javascript/deepagents/overview` (found in search, not read in detail)
- Managed Deep Agents: `docs.langchain.com/langsmith/managed-deep-agents-sdk.md` (found in search, not read)

## How the content was collected

The pages were fetched with an automated summarizing reader. Its output is a **summary of the page**, not the page verbatim. Several things follow from that:

- Code blocks are often **paraphrased or abbreviated**, especially where the reader hit its size or quoting limits. The notes use the code that came through, but treat any snippet as an approximation and check it against the source before relying on it.
- Some snippets in these notes are **written by me** from the described API, and are labeled as such where I could tell. Examples: the `researcher` subagent (10), `subagents=` shape in async (11), the harness profile shape (13), the permission rule-list examples (09). Verify them against the installed package before using them.
- The customization page was truncated. Its last ~46,000 characters weren't read. That affects the structured output section, the full profiles section, and any later parameter details.
- The subagents page was also truncated at about 100,000 characters, so the tail of that page (after roughly the last section on limitations) may be missing details.
- The `docs.langchain.com/oss/python/deepagents/going-to-production` link returned 404 when fetched directly with `.md`. The content in note 19 came from a successful fetch of the same guide without the `.md` suffix.
- The harness index page returned 404 on the fetch attempt. Note 13 relies on the customization page for profile material.

## Inconsistencies found in the sources

Recording them so they aren't mistaken for settled facts.

- **Model IDs vary between pages.** For example, Anthropic appears as `claude-sonnet-5`, `claude-sonnet-4-6`, and `claude-sonnet-5-5`. OpenAI appears as `gpt-6.1-sol`, `gpt-5.4`, and `gpt-5.5`. The quickstart page says some names may be placeholders. Check the supported models page for current IDs.
- **`task` tool signature.** The subagents page shows `subagent_type` and `description` in one place, and `name` and `task` in another. The page says this is an inconsistency.
- **`files_update` in backend results.** The protocol section lists it for state backends, and the migration section lists it as deprecated in 0.5.0. Check the version you install.
- **`create_deep_agent` location.** The API reference lists it under the `graph` module. Examples import from the top-level package.
- **Quickstart search tool name.** The quickstart says the Tavily function is named `internet_search`. The README example does not use search, so there is no conflict, but the tool name is only an example.

## Things that look like version-gated or beta behavior

Many features need a specific `deepagents` version. These are the ones the pages mention most. Check them before relying on a feature:

- `delete` tool: `>=0.7`
- Restricting filesystem tools (`FilesystemMiddleware(tools=...)`): `>=0.7`
- Binary offloading: `>=0.7.21`
- Skill tools: `>=0.7.22`
- Pinned skills: `>=0.7.23`
- Reloading skills with `skills_metadata: None`: `>=0.7.16`
- Forked subagents (beta): `>=0.7.13`
- Async subagent `update_strategy` and `webhook`: `>=0.7.30`
- Async notifications: `>=0.7.26`, metadata `>=0.7.33`
- Subagent model refusals: `>=0.7.33`
- Summarizer model override: `>=0.7.26`
- Interrupt permission mode: `>=0.6.8`
- Structured subagent output: `>=0.5.3`
- Namespace factories: `>=0.5.2`
- Permissions: `>=0.5.2`
- Filesystem permissions delete semantics: `>=0.7.3`
- Harness profiles (beta): API varies by version

Beta and experimental features named in the pages: forked subagents, dynamic subagents, async subagent `update_strategy` and `notify_parent`, the `waiting` status, task tagging, harness profiles, model router, and auto mode.

## Gaps, not covered by these notes

- The full `create_deep_agent` signature beyond the table in note 03.
- Exact `task` tool schema.
- Full content of the harness profile page and the structured output section.
- Full content of the middleware custom-hook page (LangChain's, not Deep Agents').
- Full MCP guide (stdio, OAuth, filtering).
- The LangSmith Agent Server API and deployment configuration in depth.
- Deep Agents Code (the CLI), and ACP integration.
- The JavaScript SDK differences.
- Context engineering and multimodal guides (linked, not read).
- OpenWiki, cron jobs, and custom store docs (linked, not read).
- The changelog and release history.

## Suggested next steps for a deeper pass

1. Install the `deepagents` package and read its source, especially `graph`, `middleware`, and `backends`. The source resolves the inconsistencies above.
2. Run the examples against a real model to confirm the snippets.
3. Read the truncated pages in full (customization and subagents), using the page offsets.
4. Read the MCP guide and the Agent Server deployment docs.
5. Check the changelog for the version you install.

## Confidence guide

- **High confidence** (stated plainly and consistent across pages): install commands, the `create_deep_agent` entry point, `provider:model` format, backend list and constructors, filesystem tool names, permission modes and first-match ordering, `interrupt_on` shape, decision types, HITL requires a checkpointer, skill file format, memory via `memory=`, subagent dict fields, async subagent tool names.
- **Medium confidence** (described, but examples were paraphrased or sources conflict): exact code for streaming, harness profile registration, async subagent configuration, namespace factory code, CompositeBackend import paths.
- **Low confidence** (single source, beta, or unverified): `stream_events` v3 details, dynamic subagents, the model router, exact model IDs, eval scores, Managed Deep Agents CLI details.
