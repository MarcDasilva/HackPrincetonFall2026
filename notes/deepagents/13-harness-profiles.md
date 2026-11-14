# Harness Profiles (beta)

A **harness profile** is a declarative bundle of tweaks that shape a deep agent's behavior for a specific model or provider. It can change the system prompt, add middleware, exclude tools, and configure the general-purpose subagent.

Harness profiles are different from **provider profiles** (see [04-models.md](04-models.md)), which set model initialization parameters.

Status: beta. The docs describe the API as "declarative bundles of system prompt, tool, middleware, and subagent tweaks, registered per provider or model."

## Fields the docs name

| Field | Purpose |
|---|---|
| `base_system_prompt` | Replaces the base system prompt |
| `system_prompt_suffix` | Appends text to the prompt (the authored prompt stays) |
| `general_purpose_subagent` | A `GeneralPurposeSubagentProfile` that can re-prompt, rename, or disable the general-purpose subagent |
| `excluded_tools` | Names of tools to hide from the model |
| `excluded_middleware` | Names of middleware to remove (with restrictions; see below) |

## Registration

Use `register_harness_profile(...)` with a `HarnessProfile` (and `HarnessProfileConfig` in the reference module list).

Illustrative shape, written for these notes (the docs do not show this exact call):

```python
register_harness_profile(
    HarnessProfile(
        base_system_prompt="...",
        system_prompt_suffix="...",
        general_purpose_subagent=GeneralPurposeSubagentProfile(system_prompt="..."),
    )
)
```

The customization page names the fields `base_system_prompt`, `system_prompt_suffix`, and `general_purpose_subagent=GeneralPurposeSubagentProfile(system_prompt=...)`, applied via `register_harness_profile(...)`. The exact call signature (for example, how the profile is keyed to a model) is truncated on the source page, so verify it in the installed package.

## Prompt rules

- A declarative subagent resolves profile overlays against its own model.
- A profile with **only** `system_prompt_suffix` **appends** to the authored prompt.
- A profile with `base_system_prompt` **replaces** the authored prompt.
- For the general-purpose subagent, base prompt precedence is: `general_purpose_subagent.system_prompt`, then `HarnessProfile.base_system_prompt`, then the SDK default. The profile suffix is layered on top.

## Excluding tools

- Exclude filesystem tools by name: `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`.
- Excluded tools are filtered at the end of the middleware stack ("excluded-tool filtering").

## Hard limits

- **`FilesystemMiddleware` cannot be removed** through `excluded_middleware`. Attempting to remove it is rejected. It is required scaffolding.
- **`SubAgentMiddleware` cannot be removed** through `excluded_middleware`. Listing it raises `ValueError`. To disable subagents, use `general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)` and pass no synchronous subagents. With no synchronous subagents, the `task` tool isn't attached.

## Built-in profiles

The reference lists harness profile modules for specific model families. The module names found in the reference include:

- `_anthropic_sonnet_4_6`, `_anthropic_opus_4_7`, `_anthropic_haiku_4_5`
- `_openai_codex`
- `_nvidia_nemotron_3_ultra`, which includes several middleware classes for a specific model family

Provider-level profiles also exist for `nvidia`, `openrouter`, and `openai`.

The source for the built-in profile content is not in these notes; only the module names are.

## Related

- Filesystem tool exclusions: [06-filesystem-tools.md](06-filesystem-tools.md)
- Middleware stack: [12-middleware.md](12-middleware.md)
- Subagent general-purpose profile: [10-subagents.md](10-subagents.md)
- Model provider profiles: [04-models.md](04-models.md)
