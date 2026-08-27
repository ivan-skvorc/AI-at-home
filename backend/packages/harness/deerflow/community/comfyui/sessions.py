"""Refine sessions — the server side of the self-critiquing generation loop.

The loop itself belongs to the agent: a skill instructs generate → view → judge
→ adjust → repeat, so the reasoning stays in the transcript, the run journal
keeps counting tokens per model, and streaming still works. Building the loop
inside a tool that calls the model itself would break all three.

What a model cannot be trusted with is the bookkeeping, so it lives here:

* **The rubric is frozen before iteration 1.** Three to six checkable criteria
  are derived from the request once and every iteration is judged against that
  list. An open-ended "is this good?" either accepts immediately or never
  converges, because the standard drifts with each look.
* **The counter is on the server.** The tool returns a ``session_id``; iteration
  N+1 is *refused* with a message the agent can report. Models lose count, and
  a runaway loop on a local GPU is free at the margin — which is precisely why
  nothing else stops it.
* **The wall-clock budget is enforced the same way**, which is what makes video
  (minutes per clip) safe to iterate on.
* **One named change per retry.** A verdict that asks for three changes at once
  makes the next iteration undiagnosable, so it is rejected.

The record is persisted as JSON beside the outputs: criteria, and per iteration
the params, seed, verdict and filename. That file is the audit trail — it is
what makes "target achieved" reviewable rather than asserted.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from deerflow.config.media_config import RefineConfig

SESSION_FILE_PREFIX = "refine-"
SESSION_FILE_SUFFIX = ".json"
_SESSION_ID_RE = re.compile(r"^[a-z0-9]{8,32}$")
VERDICT_CHOICES = ("accept", "retry", "abandon")


class RefineError(ValueError):
    """The session cannot do what was asked, and the agent should say so."""


class RefineLimitError(RefineError):
    """An iteration was refused by the cap or the wall-clock budget."""


@dataclass
class Iteration:
    """One generation and, once judged, its verdict."""

    index: int
    started_at: float
    params: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    filename: str | None = None
    verdict: dict[str, Any] | None = None


@dataclass
class RefineSession:
    """A frozen rubric plus the iterations judged against it."""

    session_id: str
    goal: str
    kind: str
    criteria: list[str]
    max_iterations: int
    budget_seconds: float
    created_at: float
    iterations: list[Iteration] = field(default_factory=list)
    closed: str | None = None

    # ── derived ──────────────────────────────────────────────────────────

    @property
    def used_iterations(self) -> int:
        return len(self.iterations)

    @property
    def remaining_iterations(self) -> int:
        return max(0, self.max_iterations - self.used_iterations)

    def deadline(self) -> float:
        """Budget runs from the first iteration, not from session creation."""
        first = self.iterations[0].started_at if self.iterations else self.created_at
        return first + self.budget_seconds

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["iterations"] = [asdict(iteration) for iteration in self.iterations]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RefineSession:
        iterations = [Iteration(**iteration) for iteration in data.get("iterations") or []]
        return cls(
            session_id=str(data["session_id"]),
            goal=str(data.get("goal") or ""),
            kind=str(data.get("kind") or "image"),
            criteria=[str(item) for item in data.get("criteria") or []],
            max_iterations=int(data.get("max_iterations") or 1),
            budget_seconds=float(data.get("budget_seconds") or 0.0),
            created_at=float(data.get("created_at") or 0.0),
            iterations=iterations,
            closed=data.get("closed"),
        )


def session_path(outputs_dir: Path, session_id: str) -> Path:
    if not _SESSION_ID_RE.match(session_id):
        raise RefineError(f"Invalid refine session id: {session_id!r}")
    return Path(outputs_dir) / f"{SESSION_FILE_PREFIX}{session_id}{SESSION_FILE_SUFFIX}"


def save_session(outputs_dir: Path, session: RefineSession) -> Path:
    path = session_path(outputs_dir, session.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_session(outputs_dir: Path, session_id: str) -> RefineSession:
    path = session_path(outputs_dir, session_id)
    if not path.is_file():
        raise RefineError(f"No refine session {session_id} in this conversation's outputs")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RefineError(f"Refine session {session_id} could not be read: {exc}") from exc
    return RefineSession.from_dict(data)


def create_session(
    outputs_dir: Path,
    *,
    goal: str,
    criteria: list[str],
    kind: str,
    config: RefineConfig,
    max_iterations: int | None = None,
    budget_seconds: float | None = None,
    now: float | None = None,
) -> RefineSession:
    """Freeze a rubric and open a session. Criteria cannot change afterwards."""
    cleaned = [criterion.strip() for criterion in criteria if criterion and criterion.strip()]
    if len(cleaned) < config.min_criteria or len(cleaned) > config.max_criteria:
        raise RefineError(f"A refine session needs between {config.min_criteria} and {config.max_criteria} checkable criteria; got {len(cleaned)}. Derive them from the request before generating anything.")
    if len(set(cleaned)) != len(cleaned):
        raise RefineError("Refine criteria must be distinct; two identical criteria cannot both fail informatively")
    cap = config.max_iterations if max_iterations is None else min(int(max_iterations), config.max_iterations)
    if cap < 1:
        raise RefineError("A refine session needs at least one iteration")
    budget = config.budget_seconds if budget_seconds is None else min(float(budget_seconds), config.budget_seconds)
    session = RefineSession(
        session_id=uuid.uuid4().hex[:12],
        goal=goal.strip(),
        kind=kind,
        criteria=cleaned,
        max_iterations=cap,
        budget_seconds=budget,
        created_at=now if now is not None else time.time(),
    )
    save_session(outputs_dir, session)
    return session


def begin_iteration(session: RefineSession, *, now: float | None = None) -> Iteration:
    """Claim the next iteration, or refuse it.

    Refusal is the whole point of holding the counter server-side, so the
    message is written to be reported verbatim by the agent.
    """
    moment = now if now is not None else time.time()
    if session.closed:
        raise RefineLimitError(f"Refine session {session.session_id} is closed ({session.closed}). Start a new session to keep going.")
    if session.remaining_iterations <= 0:
        raise RefineLimitError(
            f"Refine session {session.session_id} has used all {session.max_iterations} iterations. Report the best result so far and what the remaining criteria would need; do not start another session to get around the cap."
        )
    if session.iterations and moment >= session.deadline():
        raise RefineLimitError(f"Refine session {session.session_id} is out of time ({session.budget_seconds:.0f}s budget). Report the best result so far.")
    iteration = Iteration(index=session.used_iterations + 1, started_at=moment)
    session.iterations.append(iteration)
    return iteration


def record_generation(session: RefineSession, index: int, *, params: dict[str, Any], seed: int | None, filename: str | None) -> None:
    iteration = _iteration(session, index)
    iteration.params = dict(params)
    iteration.seed = seed
    iteration.filename = filename


def record_verdict(
    session: RefineSession,
    index: int,
    *,
    criteria_results: list[dict[str, Any]],
    overall: str,
    change: str | None,
) -> dict[str, Any]:
    """Attach a structured verdict to one iteration.

    Rejects prose-shaped verdicts: every frozen criterion must be judged, the
    overall call must be one of accept/retry/abandon, and a retry must name
    exactly one change.
    """
    iteration = _iteration(session, index)
    if overall not in VERDICT_CHOICES:
        raise RefineError(f"Verdict must be one of {', '.join(VERDICT_CHOICES)}; got {overall!r}")

    judged: dict[str, dict[str, Any]] = {}
    for entry in criteria_results:
        name = str(entry.get("criterion") or entry.get("name") or "").strip()
        if name not in session.criteria:
            raise RefineError(f"'{name}' is not one of this session's frozen criteria: {'; '.join(session.criteria)}")
        judged[name] = {"criterion": name, "passed": bool(entry.get("passed")), "note": str(entry.get("note") or "").strip()}
    missing = [criterion for criterion in session.criteria if criterion not in judged]
    if missing:
        raise RefineError(f"Every frozen criterion must be judged each iteration; missing: {'; '.join(missing)}")

    named_change = (change or "").strip()
    if overall == "retry":
        if not named_change:
            raise RefineError("A retry must name exactly one change to make next; one change per iteration is what makes the loop diagnosable")
        if _looks_like_several_changes(named_change):
            raise RefineError(f"A retry names exactly one change; this reads as several: {named_change!r}")
    elif named_change:
        raise RefineError(f"Only a 'retry' verdict carries a change; drop it for '{overall}'")

    verdict = {
        "criteria": [judged[criterion] for criterion in session.criteria],
        "overall": overall,
        "change": named_change or None,
        "passed": sum(1 for entry in judged.values() if entry["passed"]),
        "of": len(session.criteria),
    }
    iteration.verdict = verdict
    if overall in {"accept", "abandon"}:
        session.closed = overall
    return verdict


_MULTI_CHANGE_RE = re.compile(r"\b(?:and also|as well as)\b|;|\bthen\b", re.IGNORECASE)


def _looks_like_several_changes(change: str) -> bool:
    return bool(_MULTI_CHANGE_RE.search(change))


def _iteration(session: RefineSession, index: int) -> Iteration:
    for iteration in session.iterations:
        if iteration.index == index:
            return iteration
    raise RefineError(f"Refine session {session.session_id} has no iteration {index}")


def summarize(session: RefineSession) -> dict[str, Any]:
    """A compact status the agent can carry forward instead of re-reading images."""
    return {
        "session_id": session.session_id,
        "goal": session.goal,
        "kind": session.kind,
        "criteria": session.criteria,
        "iterations_used": session.used_iterations,
        "iterations_remaining": session.remaining_iterations,
        "closed": session.closed,
        "history": [
            {
                "iteration": iteration.index,
                "seed": iteration.seed,
                "file": iteration.filename,
                "overall": (iteration.verdict or {}).get("overall"),
                "passed": (iteration.verdict or {}).get("passed"),
                "change": (iteration.verdict or {}).get("change"),
            }
            for iteration in session.iterations
        ],
    }
