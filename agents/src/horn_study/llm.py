"""Model configuration.

Models are named in the environment as 'provider:model' strings understood by
LangChain's `init_chat_model`, so the provider can change without code edits.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

DEFAULT_MODEL = "anthropic:claude-opus-5-5"
MODEL_ENV = "HORN_STUDY_MODEL"
MAX_TOKENS_ENV = "HORN_STUDY_MAX_TOKENS"
DEFAULT_MAX_TOKENS = 16000

Role = Literal["research", "coordinator", "interpreter"]


def model_name(role: Role) -> str:
    return os.environ.get(f"HORN_STUDY_{role.upper()}_MODEL") or os.environ.get(MODEL_ENV) or DEFAULT_MODEL


class ModelNotConfigured(Exception):
    pass


_ANTHROPIC_CREDENTIAL_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_FEDERATION_RULE_ID",
)


def _check_credentials(name: str) -> None:
    """Fail early with a clear message instead of a vague connection error mid-study."""
    if not (name.startswith("anthropic:") or name.startswith("claude")):
        return
    if any(os.environ.get(variable) for variable in _ANTHROPIC_CREDENTIAL_ENV):
        return
    if (Path.home() / ".config" / "anthropic").is_dir():
        return
    raise ModelNotConfigured(
        f"The model '{name}' needs Anthropic credentials and none were found. "
        "Set ANTHROPIC_API_KEY in the environment or in a .env file, "
        f"or choose another provider with {MODEL_ENV}='provider:model'."
    )


def load_model(role: Role) -> BaseChatModel:
    """Build the chat model for a role from the environment."""
    name = model_name(role)
    _check_credentials(name)
    kwargs: dict[str, Any] = {}
    if name.startswith("anthropic:") or name.startswith("claude"):
        # Requests are not streamed, so keep the output cap within the SDK's
        # non-streaming limit.
        kwargs["max_tokens"] = int(os.environ.get(MAX_TOKENS_ENV, DEFAULT_MAX_TOKENS))
    return init_chat_model(name, **kwargs)
