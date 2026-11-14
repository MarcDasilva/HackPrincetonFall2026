# Python API: Module and Symbol Map

Source: the API reference page at `reference.langchain.com/python/deepagents/`. The fetched page listed symbol names and module paths only. It did not include signatures, parameters, or descriptions, so this note records names and locations. For signatures, check the reference or the installed package.

Use these names to find the right module. Some are internal (underscore modules) and aren't part of the stable public surface.

## Graph and models

- `graph`
  - class `DeepAgentState`
  - function `create_deep_agent()`
  - function `get_default_model()`
- `_models` (internal)
  - `resolve_model()`
  - `get_model_identifier()`
  - `get_model_provider()`
  - `is_bedrock_model()`
  - `model_matches_spec()`

## Subagents

`middleware.subagents`:

- class `SubAgent`
- class `CompiledSubAgent`
- class `TaskToolSchema`
- class `SubAgentMiddleware`
- function `create_sub_agent()`

## Filesystem

`middleware.filesystem`:

- class `FilesystemPermission`
- class `FilesystemState`
- schema classes: `LsSchema`, `ReadFileSchema`, `ReadVideoFileSchema`, `WriteFileSchema`, `EditFileSchema`, `DeleteSchema`, `GlobSchema`, `GrepSchema`, `ExecuteSchema`
- class `FilesystemMiddleware`
- function `supports_execution()`

`middleware._video` (internal):

- class `VideoExtractionError`
- functions `video_dependencies_available()`, `extract_video_frames()`

## Async subagents

`middleware.async_subagents`:

- class `AsyncSubAgent`
- class `AsyncTask`
- class `AsyncSubAgentState`
- schema classes: `StartAsyncTaskSchema`, `CheckAsyncTaskSchema`, `UpdateAsyncTaskSchema`, `CancelAsyncTaskSchema`, `ListAsyncTasksSchema`
- class `TaskEvent`
- class `AsyncSubAgentMiddleware`

## Summarization

`middleware.summarization`:

- classes `CompactConversationSchema`, `SummarizationEvent`, `TriggerClause`, `TruncateArgsSettings`, `SummarizationState`, `SummarizationDefaults`, `SummarizationToolMiddleware`
- functions `compute_summarization_defaults()`, `create_summarization_middleware()`, `create_summarization_tool_middleware()`

## Skills

`middleware.skills`:

- classes `SkillMetadata`, `SkillsState`, `SkillsStateUpdate`, `SkillsMiddleware`
- function `disclosed_skill_tool_names()`
- type alias `SkillSource`

## Rubric

`middleware.rubric`:

- classes `CriterionPass`, `CriterionFail`, `RubricEvaluation`, `RubricState`, `GraderResponse`, `RubricMiddleware`
- type alias `RubricResult`

## Memory, content, and tool calls

- `middleware.memory`: classes `MemoryState`, `MemoryStateUpdate`, `MemoryMiddleware`
- `middleware.unsupported_content`: class `UnsupportedContentMiddleware`
- `middleware.patch_tool_calls`: class `PatchToolCallsMiddleware`
- `middleware._message_eviction` (internal): class `ContentPreview`

## Middleware internals

- `middleware._state`: function `private_state_field_names()`
- `middleware._utils`: functions `append_to_system_message()`, `is_anthropic_chat_model()`
- `middleware._prompt_caching`: function `append_prompt_caching_middleware()`

## Harness profiles

`profiles.harness.harness_profiles`:

- classes `GeneralPurposeSubagentProfile`, `HarnessProfileConfig`, `HarnessProfile`
- function `register_harness_profile()`

Model-specific harness modules:

- `profiles.harness._nvidia_nemotron_3_ultra`: many middleware classes for that model family (`NemotronToolCallShim`, `ReadFileContinuationNoticeMiddleware`, `ModelRateLimitRetryMiddleware`, `ChatNVIDIAMessageCompatibilityMiddleware`, `NemotronReasoningTagCleanupMiddleware`, `NemotronTextToolCallParser`, `NemotronProgressBudgetMiddleware`, `NemotronPolicyNudgeMiddleware`, `FollowupDisciplineMiddleware`, `EntityResolutionGuardMiddleware`, `FinalAnswerGuardMiddleware`, and their state classes), plus `register()`
- `register()` in `_anthropic_sonnet_4_6`, `_anthropic_opus_4_7`, `_anthropic_haiku_4_5`, `_openai_codex`

## Provider profiles

- `profiles.provider.provider_profiles`: class `ProviderProfile`; functions `register_provider_profile()`, `get_provider_profile()`, `apply_provider_profile()`
- `profiles.provider`: `_nvidia.register()`, `_openrouter.register()`, `_openrouter.check_openrouter_version()`, `_openai.register()`
- `profiles._keys` (internal): function `validate_profile_key()`

## Backends

`backends.protocol`:

- data and result classes: `FileDownloadResponse`, `FileUploadResponse`, `FileInfo`, `ContextLine`, `GrepMatch`, `FileData`, `ReadResult`, `WriteResult`, `EditResult`, `DeleteResult`, `LsResult`, `GrepResult`, `GlobResult`
- protocols: `BackendProtocol`, `BackendConsumer`, `SandboxBackendProtocol`
- execution classes: `ExecuteResponse`, `ExecuteArtifact`, `ExecuteOffloadResult`
- function `execute_accepts_timeout()`

Backend classes:

- `backends.state`: `StateBackend`
- `backends.filesystem`: `FilesystemBackend`
- `backends.local_shell`: `LocalShellBackend`
- `backends.store`: `StoreBackend`
- `backends.context_hub`: `ContextHubBackend`
- `backends.composite`: `CompositeBackend`; type `GlobBackendResult`
- `backends.sandbox`: `BaseSandbox`
- `backends.langsmith`: `LangSmithSandbox`

`backends.utils`:

- class `InvalidGlobPatternError`
- functions `compile_grep_include_glob()`, `sanitize_tool_call_id()`, `format_content_with_line_numbers()`, `check_empty_content()`, `file_data_to_string()`, `create_file_data()`, `update_file_data()`, `normalize_read_bounds()`, `slice_read_response()`, `perform_string_replacement()`, `truncate_if_too_long()`, `to_posix_path()`, `validate_path()`, `grep_matches_from_files()`, `build_grep_results_dict()`, `format_grep_matches()`, `regex_literal_hint()`

## Deprecation helpers

`_api.deprecation` (internal):

- functions `warn_deprecated()`, `reset_deprecation_dedupe()`

## Things to know

- `create_file_data` is the helper used to seed backend files (for skills and memory). Import it from `deepagents.backends.utils`.
- `create_deep_agent` lives in the `graph` module per the reference listing. Import it from the top-level `deepagents` package in the examples.
- The JavaScript package has its own reference: `reference.langchain.com/javascript/deepagents`.

## Related

- Parameters of `create_deep_agent`: [03-create-deep-agent-parameters.md](03-create-deep-agent-parameters.md)
- Backends: [07-backends.md](07-backends.md)
