"""Configuration for automatic thread title generation."""

import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TitleConfig(BaseModel):
    """Configuration for automatic thread title generation."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable automatic title generation",
    )
    max_words: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Maximum number of words in the generated title",
    )
    max_chars: int = Field(
        default=60,
        ge=10,
        le=200,
        description="Maximum number of characters in the generated title",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for LLM title generation (None = use local fallback title)",
    )
    prompt_template: str = Field(
        default=("Generate a concise title (max {max_words} words) for this conversation.\nUser: {user_msg}\nAssistant: {assistant_msg}\n\nReturn ONLY the title, no quotes, no explanation."),
        description="Prompt template for LLM title generation when model_name is set",
    )


# Global configuration instance
_title_config: TitleConfig = TitleConfig()


def get_title_config() -> TitleConfig:
    """Get the current title configuration."""
    return _title_config


def set_title_config(config: TitleConfig) -> None:
    """Set the title configuration."""
    global _title_config
    _title_config = config


def load_title_config_from_dict(config_dict: dict) -> None:
    """Load title configuration from a dictionary."""
    global _title_config
    _title_config = TitleConfig(**config_dict)


def reset_title_config() -> None:
    """Restore the title configuration to its pristine ``TitleConfig()`` default.

    Public API so that tests do not have to reach into the private
    ``_title_config`` module attribute. ``AppConfig.from_file()`` calls
    :func:`load_title_config_from_dict`, which permanently mutates the
    singleton; tests that need a clean slate between cases should call
    this between tests.
    """
    global _title_config
    _title_config = TitleConfig()


# --- Fork: per-run automatic-rename preference -------------------------------
#
# The Web UI sends a per-user auto-rename preference in the run context
# (Settings -> Conversation titles). Both keys are optional; a caller that sends
# neither (IM channels, TUI, scheduler, the embedded runtime) gets the operator
# config unchanged.
AUTO_TITLE_ENABLED_CONTEXT_KEY = "auto_title_enabled"
AUTO_TITLE_MODEL_CONTEXT_KEY = "auto_title_model_name"

# Sentinel the UI sends for "rename, but without spending a model call": the
# empty string clears a configured ``title.model_name`` so the middleware takes
# its local truncate-the-first-message path. It is distinct from the key being
# absent, which means "follow whatever the operator configured".
AUTO_TITLE_NO_MODEL = ""


def _configured_model_names(app_config: object) -> set[str] | None:
    """Names in ``app_config.models``, or ``None`` when there is no catalog.

    ``None`` (no ``models`` attribute at all) is not the same as a configured
    but empty catalog: lightweight config-shaped objects used by tests and
    embedders predate the field, and those must not have every model rejected.
    """
    models = getattr(app_config, "models", None)
    if models is None:
        return None
    return {name for name in (getattr(model, "name", "") for model in models) if name}


def apply_auto_title_preference(app_config, cfg: Mapping[str, Any]):
    """Return an ``AppConfig`` honoring the per-run auto-rename preference.

    Two independent overrides, both layered on top of the operator's
    ``config.yaml -> title`` block:

    * ``auto_title_enabled=False`` turns automatic renaming off for this run.
      Like the memory preference, it is a one-way **opt-out**: a client can
      never switch renaming on when the operator disabled it, so an explicit
      ``True`` deliberately changes nothing.
    * ``auto_title_model_name`` picks which model writes the title. The empty
      string means "no model call" (the local fallback title); a name is
      honored only when it is in the configured model catalog, so a client
      cannot make the run reach for a model the operator never configured.

    Returns *app_config* itself when neither override applies, so the common
    path allocates nothing.
    """
    updates: dict[str, Any] = {}

    if cfg.get(AUTO_TITLE_ENABLED_CONTEXT_KEY) is False:
        updates["enabled"] = False

    requested_model = cfg.get(AUTO_TITLE_MODEL_CONTEXT_KEY)
    if isinstance(requested_model, str):
        if requested_model == AUTO_TITLE_NO_MODEL:
            updates["model_name"] = None
        else:
            configured = _configured_model_names(app_config)
            if configured is None or requested_model in configured:
                updates["model_name"] = requested_model
            else:
                logger.warning(
                    "Ignoring auto-title model %r: not present in the configured model catalog.",
                    requested_model,
                )

    if not updates:
        return app_config

    title_config = getattr(app_config, "title", None)
    if title_config is None:
        return app_config
    return app_config.model_copy(update={"title": title_config.model_copy(update=updates)})
