"""The deviation monitor's operator block and its per-run request (fork feature).

Two shapes live here because both the Gateway and the harness read them:

* ``DeviationMonitorConfig`` is the operator's ``deviation_monitor:`` block in
  ``config.yaml``. ``enabled`` says whether the feature is offered at all
  (``GET /api/features`` reports it, so the composer hides its button when it
  is off); the other fields bound what one check may cost.
* ``DeviationMonitorRequest`` is what one run asks for, read from the run
  context key ``deviation_monitor``:
  ``{"enabled": true, "model": "<name>", "cadence": {"mode": "steps" | "turns", "every": n}}``.
  A value that does not fit that shape turns the monitor off for the run with
  a fixed reason code; it never fails the run. The Gateway rewrites what a
  client sent into the canonical form (``to_context``), so the checkpointed
  copy never carries arbitrary client data, and the middleware parses it again
  because embedded callers reach the graph without the Gateway.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean

DEVIATION_MONITOR_CONTEXT_KEY = "deviation_monitor"

CadenceMode = Literal["steps", "turns"]

#: Inclusive bounds of ``cadence.every`` per mode: a check every 1-50 agent
#: steps, or at the final answer of every 1-20 conversation turns.
CADENCE_BOUNDS: dict[str, tuple[int, int]] = {"steps": (1, 50), "turns": (1, 20)}

#: The canonical value is tiny; anything bigger is not something a composer sent.
MAX_CONTEXT_BYTES = 1024
MAX_MODEL_NAME_CHARS = 200

#: Why a run's request turned the monitor off. The code is what the Gateway
#: stores; the sentence is what the status bar shows. Neither echoes the value.
REJECTION_REASONS: dict[str, str] = {
    "not_an_object": "The deviation monitor settings were not an object, so the monitor is off for this run.",
    "too_large": "The deviation monitor settings were too large, so the monitor is off for this run.",
    "unknown_keys": "The deviation monitor settings had fields this server does not know, so the monitor is off for this run.",
    "enabled_not_boolean": "The deviation monitor's on/off value was not true or false, so the monitor is off for this run.",
    "model_missing": "No monitor model was chosen, so the monitor is off for this run.",
    "cadence_invalid": "The monitor cadence must be every N steps or every N turns, so the monitor is off for this run.",
    "cadence_out_of_range": "The monitor cadence is out of range (every 1-50 steps or 1-20 turns), so the monitor is off for this run.",
}

_TOP_LEVEL_KEYS = frozenset({"enabled", "model", "cadence", "rejected"})
_CADENCE_KEYS = frozenset({"mode", "every"})


class DeviationMonitorConfig(BaseModel):
    """Operator switch and bounds for the deviation monitor (``deviation_monitor:``)."""

    enabled: bool = Field(
        default=True,
        description=("Offer the deviation monitor in the composer. It is still off in every chat until the user turns it on there; false hides the button and ignores any request a client sends."),
    )
    judge_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        description="How long one check may wait for the monitor model. A check that runs out of time is reported as unsure and never acted on.",
    )
    max_evidence_chars: int = Field(
        default=24_000,
        ge=4_000,
        le=200_000,
        description=("Ceiling, in characters, on the evidence one check sends the monitor model. The monitor model's own window lowers it further; the user's request is never cut, older steps are dropped first."),
    )

    @field_validator("judge_timeout_seconds", "max_evidence_chars", mode="before")
    @classmethod
    def _reject_boolean_numbers(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")


@dataclass(frozen=True)
class DeviationMonitorRequest:
    """One run's monitor choice, after validation."""

    enabled: bool
    model: str | None = None
    mode: CadenceMode | None = None
    every: int | None = None
    #: A ``REJECTION_REASONS`` code when the run asked for something invalid.
    rejected: str | None = None

    @property
    def rejection_reason(self) -> str | None:
        return REJECTION_REASONS.get(self.rejected) if self.rejected else None

    def to_context(self) -> dict[str, object]:
        """The canonical run-context value (what the Gateway checkpoints)."""
        if self.enabled:
            return {"enabled": True, "model": self.model, "cadence": {"mode": self.mode, "every": self.every}}
        if self.rejected:
            return {"enabled": False, "rejected": self.rejected}
        return {"enabled": False}


_OFF = DeviationMonitorRequest(enabled=False)


def _rejected(code: str) -> DeviationMonitorRequest:
    return DeviationMonitorRequest(enabled=False, rejected=code)


def parse_deviation_monitor_request(raw: object) -> DeviationMonitorRequest:
    """Validate a run's ``deviation_monitor`` value; anything invalid is off with a reason.

    ``None`` (the key sent empty) is off without a reason. ``{"enabled": false}``
    is off without a reason too, and the other fields are not checked then: a
    composer that remembers the last model and cadence may send them along.
    """
    if raw is None:
        return _OFF
    if not isinstance(raw, Mapping):
        return _rejected("not_an_object")
    try:
        encoded = json.dumps(raw, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return _rejected("not_an_object")
    if len(encoded.encode("utf-8")) > MAX_CONTEXT_BYTES:
        return _rejected("too_large")
    if not all(isinstance(key, str) for key in raw) or not set(raw) <= _TOP_LEVEL_KEYS:
        return _rejected("unknown_keys")
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        return _rejected("enabled_not_boolean")
    if "rejected" in raw:
        # Only the Gateway writes this, and only beside enabled=false.
        code = raw.get("rejected")
        if enabled or not isinstance(code, str) or code not in REJECTION_REASONS:
            return _rejected("unknown_keys")
        return _rejected(code)
    if not enabled:
        return _OFF
    model = raw.get("model")
    if not isinstance(model, str) or not model.strip() or len(model.strip()) > MAX_MODEL_NAME_CHARS:
        return _rejected("model_missing")
    cadence = raw.get("cadence")
    if not isinstance(cadence, Mapping) or set(cadence) != _CADENCE_KEYS:
        return _rejected("cadence_invalid")
    mode = cadence.get("mode")
    every = cadence.get("every")
    if mode not in CADENCE_BOUNDS or isinstance(every, bool) or not isinstance(every, int):
        return _rejected("cadence_invalid")
    low, high = CADENCE_BOUNDS[mode]
    if not low <= every <= high:
        return _rejected("cadence_out_of_range")
    return DeviationMonitorRequest(enabled=True, model=model.strip(), mode=mode, every=every)
