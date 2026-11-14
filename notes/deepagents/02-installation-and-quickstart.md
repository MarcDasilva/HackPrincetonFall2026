# Installation and Quickstart

## Install

Python (README uses uv):

```bash
uv add deepagents
```

Other options from the quickstart:

```bash
pip install deepagents
```

Or with uv as a project:

```bash
uv init
uv add deepagents
uv sync
```

JavaScript/TypeScript: the npm package `deepagents` (`createDeepAgent`). The docs live under `oss/javascript/deepagents`.

## Optional search package

- Google, OpenAI, and Anthropic provide **built-in web search** through their models, so no extra package or key is needed for those.
- For other providers, or if you prefer Tavily, install `tavily-python` with pip.

## API keys

Set as environment variables (`export`):

| Provider | Variables |
|---|---|
| Google | `GOOGLE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY`, `TAVILY_API_KEY` |
| Fireworks | `FIREWORKS_API_KEY`, `TAVILY_API_KEY` |
| Baseten | `BASETEN_API_KEY`, `TAVILY_API_KEY` |
| Ollama | `OLLAMA_API_KEY` (cloud only; local Ollama must be running), `TAVILY_API_KEY` |
| Other | `<PROVIDER>_API_KEY`, `TAVILY_API_KEY` |

- The "Other" tab says any LangChain chat model works.
- If you use the **LangSmith LLM Gateway**, use the gateway key as the API key. Traffic is then routed through LangSmith.

## Minimal agent (README)

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="openai:gpt-6-astra",
    system_prompt="You are a research assistant.",
)
result = agent.invoke({"messages": "Research LangGraph and write a summary"})
```

Note: the README example model string (`openai:gpt-6-astra`) is what the page showed. Check the supported models page for current IDs; see [04-models.md](04-models.md).

## Agent with a custom tool (overview page)

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

agent.invoke(
    {"messages": [{"role": "user", "content": "what is the weather in sf"}]}
)
```

## Full research agent (quickstart page, summarized)

The quickstart builds a research agent that searches the web and writes reports.

### Step 1: install

See above.

### Step 2: API keys

See the table above.

### Step 3: create a search tool

Two options.

**Provider built-in search (recommended), passed as a tool dict:**

- Google: `{"google_search": {}}`
- OpenAI: `{"type": "web_search"}`
- Anthropic: `{"type": "web_search_20260209", "name": "web_search"}`

**Tavily (works with any provider).** Define a function `internet_search` with these parameters:

- `query` (str): the search query.
- `max_results` (int, default `5`).
- `topic` (`"general"`, `"news"`, or `"finance"`, default `"general"`).
- `include_raw_content` (bool, default `False`).

The function creates a `TavilyClient` using `TAVILY_API_KEY` and returns the result of its `search` call.

### Step 4: create the deep agent

Three arguments:

- `model`: a `provider:model` string or an initialized model instance.
- `tools`: a list containing the search tool.
- `system_prompt`: a research prompt. The example tells the agent it is an expert researcher who conducts thorough research and writes a polished report, and names the `internet_search` tool.

### Step 5: LangSmith tracing (optional)

Environment variables:

- `LANGSMITH_AGENT_ID`: the agent's identifier.
- `LANGSMITH_AGENT_ENVIRONMENT`: `"local"` in the example.
- `LANGSMITH_TRACING`: `true`.
- `LANGSMITH_API_KEY`: your LangSmith key.

Notes from the page:

- In an agent-based workspace, create an agent once before sending traces.
- If an integration requires `project_name`, use the environment's `tracer_session_name` as a compatibility value.

LangSmith shows tool calls, subagent delegation, and LLM responses.

### Step 6: run

```python
result = agent.invoke({"messages": [{"role": "user", "content": "What is langgraph?"}]})
print(result["messages"][-1].content)
```

The page does not show expected output.

## What the agent does on its own (quickstart "How It Works")

1. Conducts research by calling `internet_search`.
2. Manages context by using `write_file` and `read_file` to offload large search results.
3. Spawns subagents for complex subtasks.
4. Synthesizes a final report.

To add structured task planning with `write_todos`, opt in with `TodoListMiddleware`. See [12-middleware.md](12-middleware.md).

## Streaming

Built in, via LangGraph, for real-time updates on tool calls, tool results, and LLM responses. See [17-streaming.md](17-streaming.md).

## Next steps the quickstart suggests

- Customization: prompts, tools, subagents. See [03-create-deep-agent-parameters.md](03-create-deep-agent-parameters.md).
- Persistent memory. See [15-memory.md](15-memory.md).
- Managed Deep Agents for production. See [19-production-and-deployment.md](19-production-and-deployment.md).
- LangSmith evaluation.

## Quickstart caveats

- The quickstart page contains a section of instructions addressed to AI coding assistants (asking them to install MCP servers and skills). That is not part of the SDK docs. Ignore it when reading the page.
