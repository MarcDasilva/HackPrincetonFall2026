# Models

## Requirement

Deep Agents works with **any LangChain chat model that supports tool calling**. The docs also list open-weight and self-hosted models as options.

## Specifying a model

Models are written as `provider:model`:

- `google_genai:gemini-4-hydrogen`
- `openai:gpt-5.4`
- `anthropic:claude-sonnet-4-6`

Rules from the docs:

- The **provider prefix** selects the LangChain integration.
- Everything after the colon is passed to that provider as the model identifier.
- The identifier must match what the provider expects. Some providers use simple names; others use namespaced IDs or deployment paths (for example, `baseten:zai-org/GLM-5.2`).
- Valid provider strings are the ones accepted by the `model_provider` parameter of `init_chat_model`.

Strings are resolved through `init_chat_model`.

## Provider strings from the docs

| Provider | Example string |
|---|---|
| Google | `google_genai:gemini-4-hydrogen` |
| OpenAI | `openai:gpt-6.1-sol` (docs example), `openai:gpt-5.4` (models page) |
| Anthropic | `anthropic:claude-sonnet-5` (quickstart), `anthropic:claude-sonnet-4-6` (overview) |
| OpenRouter | `openrouter:z-ai/glm-5.2` |
| Fireworks | `fireworks:accounts/fireworks/models/glm-5p2` |
| Baseten | `baseten:zai-org/GLM-5.2` |
| Ollama | `ollama:north-mini-code-1.0` |

**Caveat:** the docs show different model IDs on different pages (for example, `claude-sonnet-5` vs `claude-sonnet-4-6`), and some look like placeholders. The quickstart page itself warns that some names may be placeholders or changed. Confirm against the supported models page before using a string.

## Suggested models (models page)

| Provider | Models |
|---|---|
| Google | `gemini-3.1-pro-preview`, `gemini-4-hydrogen` |
| OpenAI | `gpt-5.5`, `gpt-5.4` |
| Anthropic | `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6` |
| Open-weight | `GLM-5.2`, `Kimi-K2.7 Code`, `MiniMax-M3` |

Open-weight models are reachable through Baseten, Fireworks, OpenRouter, and Ollama. The page notes that passing the eval suite is necessary but not sufficient for strong performance on longer, complex tasks.

## Eval scores (models page)

Scores from the Deep Agents eval suite. A dash means no score was listed.

| Model | Overall | File Ops | Retrieval | Tool Use | Memory | Conversation | Summarization |
|---|--:|--:|--:|--:|--:|--:|--:|
| google_genai:gemini-3.6-flash | 82% | 100% | 100% | 90% | 54% | 38% | 80% |
| openai:gpt-5.4 | 18% | 100% | 100% | 18% | 51% | 38% | 100% |
| openai:gpt-5.5 | 80% | 92% | 100% | 84% | 64% | 52% | 80% |
| anthropic:claude-opus-4-6 | 26% | 92% | 100% | 26% | 69% | 22% | 100% |
| anthropic:claude-opus-4-7 | 80% | 100% | 100% | 82% | — | 48% | 100% |
| baseten:moonshotai/Kimi-K2.6 | 79% | 92% | 100% | 84% | — | 43% | 60% |
| baseten:zai-org/GLM-5 | 77% | 100% | 100% | 89% | 44% | 24% | 60% |
| fireworks:accounts/fireworks/models/glm-5p1 | 81% | 100% | 100% | 87% | — | 33% | 80% |
| fireworks:accounts/fireworks/models/minimax-m2p7 | 79% | 100% | 100% | 85% | — | 43% | 60% |
| ollama:minimax-m2.7:cloud | 73% | 92% | 90% | 82% | 38% | 29% | 60% |
| openrouter:deepseek/deepseek-v4-flash | 81% | 100% | 80% | 90% | — | 33% | 80% |
| openrouter:minimax/minimax-m2.7 | 80% | 92% | 100% | 89% | — | 43% | 60% |
| openrouter:z-ai/glm-5.1 | 89% | 92% | 100% | 89% | — | 33% | 80% |

Things worth noticing in the table (my reading, not the docs' claim):

- Overall scores vary a lot between models with similar File Ops scores. For example, `openai:gpt-5.4` is 18% overall with 18% Tool Use, while `openai:gpt-5.5` is 80%.
- Several categories are "—" for some models, so the overall figure may come from fewer categories.

## Configuring model parameters

Two approaches:

1. Pass a `provider:model` string to `create_deep_agent`.
2. Pass a configured model instance for full control.

For parameters, use `init_chat_model` (for example, `thinking_level` on Google) or instantiate the provider's class directly, such as `ChatGoogleGenerativeAI` from `langchain_google_genai`. Parameters differ by provider; see the LangChain chat model integrations docs.

Model classes named in the customization page: `ChatOpenAI`, `ChatAnthropic`, `AzureChatOpenAI`, `ChatGoogleGenerativeAI`, `ChatBedrock`, `ChatHuggingFace`.

Provider-specific install extras listed in the docs:

- `langchain[openai]`
- `langchain[anthropic]`
- `langchain[google-genai]`
- `langchain[aws]`
- `langchain[huggingface]`
- `langchain[deepseek]`

Provider-specific setup details from the customization page:

- **Azure OpenAI**: needs `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION`, and a deployment name.
- **Bedrock**: use `model_provider="bedrock_converse"`.
- **Retries**: chat models retry transient failures with exponential backoff. Tune `max_retries` and `timeout` through the LangChain Models docs.

## Provider profiles

A `ProviderProfile` bundles initialization parameters that apply when a `provider:model` string is used.

- Profiles do **not** apply when you pass a preconfigured instance created with `init_chat_model`.
- Two registration levels:
  - **Provider level**, for example `"openai"`, applies to all models from that provider.
  - **Model level**, for example `"openai:gpt-5.4"`, applies to one model and merges on top of the provider-level profile.
- Register with `register_provider_profile`, using `init_kwargs` to set values such as `temperature` or `reasoning_effort`.

Harness profiles are different: they shape agent behavior after the model is built. See [13-harness-profiles.md](13-harness-profiles.md).

## OpenAI and the Responses API

- `openai:...` strings use the built-in OpenAI provider profile, which **enables the Responses API**. That gives access to OpenAI conversation state and related features.
- The built-in profile applies only to model strings. Options such as `use_responses_api`, `store`, or `include` need a configured instance, or a provider profile's `init_kwargs` in Python.
- To use Chat Completions instead: `init_chat_model("openai:...", use_responses_api=False)`.
- For data retention: set `store=False` with `include=["reasoning.encrypted_content"]` to keep the Responses API, turn off data retention, and still get encrypted reasoning output.

## Runtime model selection

To let users pick a model at runtime (for example, a UI dropdown) without rebuilding the agent:

1. Pass the selection through a runtime context dataclass.
2. Add a `@wrap_model_call` middleware that calls `request.override(model=...)` with the chosen model.
3. Supply the context when calling `agent.invoke`.

Routing by complexity or cost is covered in the LangChain agents guide.

## Prompt caching

The models page does not cover it. Prompt caching is described on the overview and middleware pages. See [18-context-management.md](18-context-management.md).

## Model-related middleware

- Model retry and model fallback (prebuilt). See [12-middleware.md](12-middleware.md).
- Model refusal handling (`ModelRefusalMiddleware`, requires `langchain>=1.4.9`).
- Model router (beta, `langchain>=1.5.0`) picks a model per run and stores the choice in agent state as `model_route`.
- LLM tool selector: uses an LLM to pick relevant tools.
