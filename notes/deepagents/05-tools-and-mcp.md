# Tools and MCP

## Passing tools

Pass tools in the `tools=` parameter of `create_deep_agent`. Accepted forms, based on the signature (`Sequence[BaseTool | Callable | dict]`):

1. **Plain Python functions** with a docstring. The docstring becomes the tool description.
2. **LangChain `BaseTool` objects**.
3. **Dict-form provider tools**, such as `{"google_search": {}}` or `{"type": "web_search"}`.

### Example: plain function

```python
from deepagents import create_deep_agent

def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

agent = create_deep_agent(
    model="<provider:model>",
    tools=[get_weather],
    system_prompt="You are a helpful assistant",
)
```

### Example: multiple tools

From the overview:

```python
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6", tools=[search, fetch_page, run_query])
```

## Built-in tools

These are always present (the overview says so for filesystem and subagent tools):

- Filesystem tools: `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`. Plus `execute` on sandbox backends. See [06-filesystem-tools.md](06-filesystem-tools.md).
- The `task` tool for subagents. See [10-subagents.md](10-subagents.md).
- Planning tool `write_todos`, only if you add `TodoListMiddleware`. See [12-middleware.md](12-middleware.md).

To remove filesystem tools or the `task` tool, see [06-filesystem-tools.md](06-filesystem-tools.md) and [10-subagents.md](10-subagents.md).

## Web search tools

The quickstart supports three options:

1. **Provider built-in search** (recommended, no extra package):
   - Google: `{"google_search": {}}`
   - OpenAI: `{"type": "web_search"}`
   - Anthropic: `{"type": "web_search_20260209", "name": "web_search"}`
2. **Tavily**, any provider: install `tavily-python`, define a function that wraps `TavilyClient.search`, using the `TAVILY_API_KEY`.
3. Your own function.

Tavily wrapper parameters from the quickstart:

- `query` (str)
- `max_results` (int, default `5`)
- `topic` (`"general"`, `"news"`, `"finance"`; default `"general"`)
- `include_raw_content` (bool, default `False`)

## MCP (Model Context Protocol)

The overview says Deep Agents has full MCP support. The customization page gives these steps:

1. Install `langchain[mcp]`.
2. Create an `MCPAdapter` with a server config. Example shape: a `url` entry under `mcpServers`.
3. Call `list_tools()` on the adapter.
4. Pass the result to `tools=`.

The page says stdio servers, OAuth, tool filtering, and stateful sessions are covered in the MCP guide (not in these notes).

The README lists "Tools: bring your own functions or any MCP server" as a feature.

## Tool error and retry middleware

Tool-level reliability is handled by prebuilt middleware, not by `tools=`:

- **Tool error middleware**: converts tool exceptions into error `ToolMessage`s (requires `langchain>=1.3.14`).
- **Tool retry middleware**: retries with exponential backoff.
- **Tool call limit**: caps calls globally or per tool.

Ordering guidance from the middleware page: place tool retry inside (later in the list) tool error, with `on_failure="error"` on the retry, so exceptions reach the error handler after retries run out.

See [12-middleware.md](12-middleware.md).

## Tool search (deferred tools)

- `ProviderToolSearchMiddleware` defers tools to provider-side search (Anthropic and OpenAI, per the middleware page).
- Deferred tools are marked with `extras={"defer_loading": True}`.
- Skills can also expose tools; see [14-skills.md](14-skills.md).

## LLM tool selector

A prebuilt middleware uses an LLM to pick which tools are relevant for each turn.

## Restricting tools

Filesystem tool allowlists are possible through `FilesystemMiddleware(tools=[...])`. Custom tools passed through `tools=` are not affected by that list.

## Interpreter tool (`eval`)

`CodeInterpreterMiddleware` from `langchain_quickjs` adds an `eval` tool that runs JavaScript in a scoped QuickJS runtime. It has no shell, package install, or filesystem/network access. Use it for loops, batching, deterministic transforms, and programmatic tool calling. See [08-sandboxes.md](08-sandboxes.md) for the distinction from sandbox `execute`.

## Writing tools: practical notes from the docs

- Write a clear docstring. The model reads it to decide when to call the tool.
- Give each subagent the minimum tool set it needs. See [10-subagents.md](10-subagents.md).
- Tools that have side effects should be considered for human approval. See [16-human-in-the-loop.md](16-human-in-the-loop.md).
- Tool outputs can be large. The harness offloads large results to disk (see [18-context-management.md](18-context-management.md)).
- The overview and customization docs say that custom tools are plain functions, so no special base class is required.
