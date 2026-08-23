"""Prompt construction and response parsing for automatic agent generation.

Pure functions and value objects only, so the two parts most likely to break a
release — the instruction the model is given and the tolerance of the parser
reading it back — are unit-testable without a model, a store, or a request.

The contract with the model is a single JSON object. It answers one question
("do this user's existing agents already cover the work in these sources?") and,
only when the answer is no, drafts the agent. A "no gap" verdict is a first-class
success, not a failure to produce output: over-eager agent creation is the
failure mode this flow has to avoid.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from deerflow.utils import llm_text

from .transcript import SourceTranscript, truncate

VERDICT_PROPOSE = "propose"
VERDICT_NO_GAP = "no_gap"
VALID_VERDICTS = frozenset({VERDICT_PROPOSE, VERDICT_NO_GAP})

# Mirrors ``AGENT_NAME_PATTERN`` in agents_config: the generated name is written
# straight into a filesystem path / DB key by the create route, so it must be
# valid there before it is ever shown to the user.
_INVALID_NAME_CHARS = re.compile(r"[^a-z0-9-]+")
_REPEATED_HYPHENS = re.compile(r"-{2,}")
MAX_NAME_LENGTH = 48
FALLBACK_AGENT_NAME = "generated-agent"

MAX_RATIONALE_CHARS = 2000
MAX_DESCRIPTION_CHARS = 300
MAX_SOUL_CHARS = 8000


class AgentAnalysisError(ValueError):
    """The model's reply could not be read as a usable analysis result."""


@dataclass(frozen=True)
class AgentProposal:
    """A drafted custom agent, shaped for ``POST /api/agents``."""

    name: str
    description: str
    soul: str
    skills: list[str] | None = None


@dataclass(frozen=True)
class AgentAnalysis:
    """The model's verdict on whether a new agent is warranted."""

    verdict: str
    rationale: str
    covered_by: str | None = None
    proposal: AgentProposal | None = None

    @property
    def proposes_agent(self) -> bool:
        return self.verdict == VERDICT_PROPOSE and self.proposal is not None


def normalize_agent_name(raw: str) -> str:
    """Coerce a model-authored name into a valid agent name.

    Models reliably return human-shaped names ("Weekly Report Writer"), and the
    agent store requires ``^[A-Za-z0-9-]+$``. Coercing here rather than
    rejecting keeps a good proposal usable instead of failing the whole run on
    a formatting detail.
    """
    candidate = _INVALID_NAME_CHARS.sub("-", raw.strip().lower())
    candidate = _REPEATED_HYPHENS.sub("-", candidate).strip("-")
    candidate = candidate[:MAX_NAME_LENGTH].strip("-")
    return candidate or FALLBACK_AGENT_NAME


def uniquify_agent_name(name: str, existing: Sequence[str]) -> str:
    """Return ``name``, or the first free ``name-2``, ``name-3``… variant.

    The proposal is shown to the user as a ready-to-create draft, so a name that
    would 409 against one of their own agents is a dead end. Suffixing keeps the
    draft actionable; the user can still rename it before creating.
    """
    taken = {str(item).strip().lower() for item in existing}
    if name not in taken:
        return name
    suffix = 2
    while True:
        # Keep room for the suffix so a maximum-length name stays valid.
        candidate = f"{name[: MAX_NAME_LENGTH - len(str(suffix)) - 1].strip('-')}-{suffix}"
        if candidate not in taken:
            return candidate
        suffix += 1


def _existing_agents_block(existing_agents: Sequence[dict[str, Any]]) -> str:
    if not existing_agents:
        return "(none — this user has no custom agents yet)"
    lines: list[str] = []
    for agent in existing_agents:
        name = str(agent.get("name") or "").strip()
        if not name:
            continue
        description = str(agent.get("description") or "").strip() or "(no description)"
        lines.append(f"- {name}: {truncate(description, MAX_DESCRIPTION_CHARS)}")
    return "\n".join(lines) or "(none — this user has no custom agents yet)"


def build_system_instruction(existing_agents: Sequence[dict[str, Any]]) -> str:
    """Instruction for the one-shot analysis call."""
    return (
        "You analyze a user's past work with an AI assistant and decide whether they would "
        "benefit from a NEW custom agent — a reusable assistant persona with its own SOUL.md.\n"
        "\n"
        "The user's existing custom agents are:\n"
        f"{_existing_agents_block(existing_agents)}\n"
        "\n"
        "Decide between exactly two verdicts:\n"
        f'- "{VERDICT_NO_GAP}": the work in the sources is one-off, too varied to specialize, or already '
        "covered by an existing agent. Prefer this verdict when in doubt — an unnecessary agent is worse "
        "than none, because it dilutes the user's roster and has to be maintained.\n"
        f'- "{VERDICT_PROPOSE}": the sources show a RECURRING kind of work with a consistent shape '
        "(same domain, same deliverable, same standards) that no existing agent covers. Only then, draft the agent.\n"
        "\n"
        "When proposing, the SOUL.md must follow this structure, with these exact bold section headers:\n"
        "**Identity** — one dense paragraph: what the agent is, the specific domain it owns, and what that frees the user from.\n"
        "**Core Traits** — 3 to 5 lines, each an imperative behavioral rule grounded in evidence from the sources, not an adjective.\n"
        "**Communication** — tone, default language (match the language the user writes in), and format expectations.\n"
        "**Growth** — how the agent should learn this user's preferences over time.\n"
        "**Lessons Learned** — leave as the placeholder line: _(Mistakes and insights recorded here to avoid repeating them.)_\n"
        "Keep the whole SOUL.md under 300 words. Ground every claim in the sources; invent nothing.\n"
        "\n"
        "Reply with ONE JSON object and nothing else — no prose, no markdown fence:\n"
        "{\n"
        f'  "verdict": "{VERDICT_PROPOSE}" | "{VERDICT_NO_GAP}",\n'
        '  "rationale": "2-4 sentences citing concrete evidence from the sources",\n'
        '  "covered_by": "<existing agent name, or null>",\n'
        '  "proposal": {\n'
        '    "name": "hyphen-case-name",\n'
        '    "description": "one line, under 200 characters",\n'
        '    "soul": "the full SOUL.md markdown"\n'
        f'  }} // omit or null when the verdict is "{VERDICT_NO_GAP}"\n'
        "}\n"
    )


def build_user_content(sources: Sequence[SourceTranscript]) -> str:
    """Render the selected sources as the analysis request body."""
    rendered = "\n\n".join(source.render() for source in sources)
    return f"Here are {len(sources)} source(s) of the user's past work.\n\n{rendered}\n\nDecide whether a new custom agent is warranted, and reply with the JSON object."


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = llm_text.strip_think_blocks(text)
    candidate = llm_text.strip_markdown_code_fence(candidate)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AgentAnalysisError("The analysis model did not return a JSON object.")
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AgentAnalysisError(f"The analysis model returned malformed JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentAnalysisError("The analysis model returned JSON that is not an object.")
    return data


def _clean_skills(raw: Any) -> list[str] | None:
    """Normalize a proposed skill whitelist.

    ``None`` is meaningful in ``AgentConfig`` (inherit every enabled skill), so
    an absent or unusable value must stay ``None`` rather than collapse to
    ``[]``, which would mean the opposite: no skills at all.
    """
    if not isinstance(raw, list):
        return None
    skills = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    return skills or None


def parse_analysis(text: str, *, existing_names: Sequence[str] = ()) -> AgentAnalysis:
    """Read the model's reply into an :class:`AgentAnalysis`.

    Raises:
        AgentAnalysisError: when the reply is not usable — no JSON object, an
            unknown verdict, or a "propose" verdict with no SOUL.md content. The
            route surfaces these as a retryable failure rather than persisting a
            half-formed agent.
    """
    data = _extract_json_object(text)

    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VALID_VERDICTS:
        raise AgentAnalysisError(f"The analysis model returned an unknown verdict: {verdict or '(missing)'}")

    rationale = truncate(str(data.get("rationale") or "").strip(), MAX_RATIONALE_CHARS)

    covered_by_raw = data.get("covered_by")
    covered_by = str(covered_by_raw).strip() if isinstance(covered_by_raw, str) and covered_by_raw.strip() else None

    if verdict == VERDICT_NO_GAP:
        return AgentAnalysis(verdict=VERDICT_NO_GAP, rationale=rationale, covered_by=covered_by)

    raw_proposal = data.get("proposal")
    if not isinstance(raw_proposal, dict):
        raise AgentAnalysisError("The analysis model proposed an agent but returned no proposal object.")

    soul = str(raw_proposal.get("soul") or "").strip()
    if not soul:
        # setup_agent refuses an empty SOUL.md for the same reason (#3549): an
        # agent without one is unusable, and failing here lets the user retry
        # instead of leaving a broken draft on screen.
        raise AgentAnalysisError("The analysis model proposed an agent with an empty SOUL.md.")

    name = uniquify_agent_name(normalize_agent_name(str(raw_proposal.get("name") or "")), existing_names)
    description = truncate(str(raw_proposal.get("description") or "").strip(), MAX_DESCRIPTION_CHARS)

    return AgentAnalysis(
        verdict=VERDICT_PROPOSE,
        rationale=rationale,
        covered_by=covered_by,
        proposal=AgentProposal(
            name=name,
            description=description,
            soul=truncate(soul, MAX_SOUL_CHARS),
            skills=_clean_skills(raw_proposal.get("skills")),
        ),
    )
