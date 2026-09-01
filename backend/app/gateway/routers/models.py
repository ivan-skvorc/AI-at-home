import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import (
    _AuthorizationUnavailable,
    _is_internal_caller,
    resolve_model_authorization,
)
from app.gateway.deps import get_config, get_optional_user_from_request
from deerflow.authz.provider import AuthzDecision, AuthzRequest
from deerflow.config.app_config import AppConfig
from deerflow.pricing import build_pricing_map, lookup_pricing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["models"])


class ModelPriceResponse(BaseModel):
    """A model's effective price, per one million tokens (fork feature).

    Resolved server-side from `price:` / the legacy `pricing:` block / the
    `($in/out)` pair in `display_name`, so the UI renders one shape and never
    re-implements that precedence or parses a display name.

    The discount fields are already **expiry-filtered**: a lapsed discount is
    absent here rather than present-and-stale, so a client cannot show a
    promotion that has ended by forgetting to compare dates. `discount_until` is
    informational only ("promo rate through Aug 31").
    """

    currency: str = Field(..., description="ISO currency code; one currency across all priced models")
    input: float = Field(..., description="Price per 1M input tokens (cache miss)")
    output: float = Field(..., description="Price per 1M output tokens")
    cache_hit: float | None = Field(default=None, description="Price per 1M cache-hit input tokens; null means hits bill at the miss price")
    discount_input: float | None = Field(default=None, description="Discounted input price, when a discount is currently active")
    discount_output: float | None = Field(default=None, description="Discounted output price, when a discount is currently active")
    discount_cache_hit: float | None = Field(default=None, description="Discounted cache-hit price, when configured")
    discount_until: str | None = Field(default=None, description="ISO 8601 instant the active discount lapses; null means no expiry")


class ModelResponse(BaseModel):
    """Response model for model information."""

    name: str = Field(..., description="Unique identifier for the model")
    model: str = Field(..., description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Model description")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")
    supports_tools: bool | None = Field(default=None, description="Whether model supports tool calling (None if unknown)")
    price: ModelPriceResponse | None = Field(default=None, description="Effective price with any active discount; null when this model has no configured price")
    context_window: int | None = Field(default=None, description="Fork feature. Configured total context window in tokens; null when unknown")
    size_bytes: int | None = Field(default=None, description="Fork feature. On-disk weight size in bytes for a local model; null for hosted models")


def _price_response(pricing: dict, model: Any) -> ModelPriceResponse | None:
    """The effective price for one model, or None when it has no price.

    Reads the shared pricing map rather than the model config so the API agrees
    with what actually gets billed — including the one-currency rule, which
    disables cost reporting wholesale when configured models mix currencies.
    """
    entry = lookup_pricing(pricing, model.name) or lookup_pricing(pricing, getattr(model, "model", None))
    if entry is None:
        return None
    promo = entry.promo()
    return ModelPriceResponse(
        currency=entry.currency,
        input=entry.input_per_million,
        output=entry.output_per_million,
        cache_hit=entry.input_cache_hit_per_million,
        discount_input=promo.input_per_million if promo else None,
        discount_output=promo.output_per_million if promo else None,
        discount_cache_hit=promo.input_cache_hit_per_million if promo else None,
        discount_until=entry.discount_until.isoformat() if (promo and entry.discount_until) else None,
    )


class TokenUsageResponse(BaseModel):
    """Token usage display configuration."""

    enabled: bool = Field(default=False, description="Whether token usage display is enabled")


class ModelsListResponse(BaseModel):
    """Response model for listing all models."""

    models: list[ModelResponse]
    token_usage: TokenUsageResponse


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
    description="Retrieve a list of all available AI models configured in the system.",
)
async def list_models(
    request: Request,
    config: AppConfig = Depends(get_config),
) -> ModelsListResponse:
    """List all available models from configuration.

    Returns model information suitable for frontend display,
    excluding sensitive fields like API keys and internal configuration.

    When ``authorization.enabled`` is true, only models the caller's role may
    ``list`` are returned (filtered via ``provider.filter_resources``). A
    provider error yields an empty list (fail-closed) or all models (fail-open).

    Returns:
        A list of all configured models with their metadata and token usage display settings.

    Example Response:
        ```json
        {
            "models": [
                {
                    "name": "gpt-4",
                    "model": "gpt-4",
                    "display_name": "GPT-4",
                    "description": "OpenAI GPT-4 model",
                    "supports_thinking": false,
                    "supports_reasoning_effort": false
                },
                {
                    "name": "claude-3-opus",
                    "model": "claude-3-opus",
                    "display_name": "Claude 3 Opus",
                    "description": "Anthropic Claude 3 Opus model",
                    "supports_thinking": true,
                    "supports_reasoning_effort": false
                }
            ],
            "token_usage": {
                "enabled": true
            }
        }
        ```
    """
    visible_models = config.models
    fail_closed = config.authorization.fail_closed

    user = await get_optional_user_from_request(request)
    if user is not None:
        try:
            provider, principal = resolve_model_authorization(user, is_internal=_is_internal_caller(request, user))
        except _AuthorizationUnavailable as exc:
            if exc.fail_closed:
                visible_models = []
        else:
            if provider is not None and principal is not None:
                try:
                    allowed_names = provider.filter_resources(principal, "model", [m.name for m in config.models])
                    if not isinstance(allowed_names, list) or any(not isinstance(n, str) for n in allowed_names):
                        raise TypeError("AuthorizationProvider.filter_resources must return list[str]")
                    allowed_set = set(allowed_names)
                    visible_models = [m for m in config.models if m.name in allowed_set]
                except Exception:
                    logger.warning("Authorization provider failed while filtering models", exc_info=True)
                    visible_models = [] if fail_closed else config.models

    # Built from the full configured set, not just the visible one: the
    # one-currency rule is a property of the deployment, so an authorization
    # filter must not change whether cost reporting is enabled.
    pricing = build_pricing_map(config.models, logger=logger)
    models = [
        ModelResponse(
            name=model.name,
            model=model.model,
            display_name=model.display_name,
            description=model.description,
            supports_thinking=model.supports_thinking,
            supports_reasoning_effort=model.supports_reasoning_effort,
            supports_tools=getattr(model, "supports_tools", None),
            price=_price_response(pricing, model),
            # Fork feature: how much room a model has, and how much of the GPU it
            # already occupies. Both are config metadata rather than anything the
            # provider returns, and the picker shows them together because the
            # weights are what decides whether the window is actually affordable.
            context_window=getattr(model, "context_window", None),
            size_bytes=getattr(model, "size_bytes", None),
        )
        for model in visible_models
    ]
    return ModelsListResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Get Model Details",
    description="Retrieve detailed information about a specific AI model by its name.",
)
async def get_model(
    model_name: str,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> ModelResponse:
    """Get a specific model by name.

    Args:
        model_name: The unique name of the model to retrieve.

    Returns:
        Model information if found.

    Raises:
        HTTPException: 404 if model not found; 403 if the caller's role may not
        ``use`` the model (only when ``authorization.enabled`` is true). A
        provider resolution error yields 403 (fail-closed) or allows the request
        (fail-open), mirroring ``list_models``'s provider-error semantics.

    Example Response:
        ```json
        {
            "name": "gpt-4",
            "display_name": "GPT-4",
            "description": "OpenAI GPT-4 model",
            "supports_thinking": false
        }
        ```
    """
    model = config.get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    # Phase 3: enforce model:use authorization (deny → 403, not 404, since the
    # model exists but the role lacks permission to use it).
    fail_closed = config.authorization.fail_closed
    user = await get_optional_user_from_request(request)
    if user is not None:
        try:
            provider, principal = resolve_model_authorization(user, is_internal=_is_internal_caller(request, user))
        except _AuthorizationUnavailable:
            if fail_closed:
                raise HTTPException(status_code=403, detail=f"Model '{model_name}' is not available for your role")
        else:
            if provider is not None and principal is not None:
                try:
                    decision = provider.authorize(AuthzRequest(principal=principal, resource="model", action="use", target=model_name))
                    if not isinstance(decision, AuthzDecision):
                        raise TypeError("AuthorizationProvider.authorize must return AuthzDecision")
                    allowed = decision.allow
                except Exception:
                    logger.warning(
                        "Authorization provider failed while checking model:use for %s",
                        model_name,
                        exc_info=True,
                    )
                    allowed = not fail_closed
                if not allowed:
                    raise HTTPException(status_code=403, detail=f"Model '{model_name}' is not available for your role")

    return ModelResponse(
        name=model.name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
        supports_tools=getattr(model, "supports_tools", None),
        price=_price_response(build_pricing_map(config.models, logger=logger), model),
        context_window=getattr(model, "context_window", None),
        size_bytes=getattr(model, "size_bytes", None),
    )
