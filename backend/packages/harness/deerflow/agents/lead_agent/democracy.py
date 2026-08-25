"""Democracy panels — the organizer half of the multi-model deliberation mode.

A Democracy run is one *organizer* model dispatching one identical assignment to
several deliberately different *panelist* models, then synthesizing what came
back. This module owns the two pure pieces of that: which panel a run actually
has, and the organizer instructions rendered into the lead-agent system prompt.

Two design rules are load-bearing and must survive refactors:

* **The panel roster is the whole feature.** A panelist name that is not a
  configured model is dropped rather than substituted, and a panel that falls
  below two distinct models renders no section at all. Silently running a
  "panel" that is one model twice would report independent agreement that never
  happened — a wrong answer wearing the costume of a right one.
* **The organizer collects facts once.** The section says so at length because
  the naive reading of "ask five models" is to let five models each do the
  retrieval, which multiplies cost by five *and* gives the panel five slightly
  different datasets to disagree about.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from deerflow.config.subagents_config import clamp_total_subagents_per_run

logger = logging.getLogger(__name__)

# Upper bound on panel size. Not a cost control — `max_total_per_run` and the
# spend budget are — but a bound on how much of the system prompt one roster may
# occupy, and a guard against a malformed context turning into a giant prompt.
MAX_DEMOCRACY_PARTICIPANTS = 12

# A panel needs at least two *different* models; one model asked twice is not a
# second opinion, it is the same opinion at twice the price.
MIN_DEMOCRACY_PARTICIPANTS = 2


DEMOCRACY_SECTION_TEMPLATE = """
<democracy_panel>
You are the **organizer** of a deliberation panel. The user chose this mode to
get several *different* models' independent readings of one question, and then a
synthesis of where they agree and disagree. Your own opinion is one input to that
synthesis, not the answer.

**The panel (run each `task` call with exactly this `model=` value):**
{participant_lines}

**Phase 1 — you gather the shared facts, once.**
Any retrieval, browsing, file reading, or computation the question needs is
*your* job, done a single time. Having {count} panelists each fetch the same
interest rates, filings, or prices costs {count}x for one dataset and, worse,
produces {count} slightly different datasets — so the panel would disagree about
inputs while appearing to disagree about judgement. Collect it, condense it into
one plain factual brief, and hand that identical brief to every panelist.

**Treat gathered facts as given. Do not spend a round verifying them.**
Cross-checking every figure across the panel is exactly the cost this design
refuses to pay. Record the source alongside each fact so the reader can judge it,
flag anything you already know to be contested or stale, and move on.

**Phase 2 — dispatch the identical assignment to every panelist.**
One `task` call per panelist, each with its own `model=`, all in the same
response so they run concurrently. Every panelist receives **the same brief and
the same question, word for word**, plus the shared facts. Varying the wording
between panelists means you are measuring your prompts, not their judgement.
Ask each for its own reasoning and a clearly stated conclusion. Do not tell a
panelist what the others said in this phase, and do not reveal which model any
other panelist is.

**Phase 3 — cross-review.**
Give each panelist the *anonymized* answers of the others ("Panelist A said…")
and ask it to either revise its conclusion or hold it, with a reason. Anonymity
matters: a model told it is arguing with a bigger-name model defers to the name
rather than the argument. Skip this phase only if the budget is nearly spent, and
say so in the final answer.

**Phase 4 — synthesize, objectively.**
This is the part that is easy to do badly:
- Report the actual distribution of views, including a lone dissenter. A 4-1
  split is a materially different answer from unanimity and must not be
  flattened into "the panel concluded".
- Where they agree, say so plainly. Where they disagree, name the disagreement
  and the reasoning behind each side — the reader wants the shape of the
  disagreement, not a number.
- Do not average conclusions into mush, and do not hold a vote as though model
  count were evidence. A single well-argued minority position can be the right
  one; say when you think it is, and why.
- Do not privilege a panelist because it is the model you would have picked, and
  do not privilege your own Phase 1 hunch. If your reading differs from the
  panel's, present it as one more labelled view.
- Attribute each position to the model that held it, so the reader can weigh it.

**Budget.** Each phase costs one full model run per panelist. You have {total}
`task` calls for the whole run; {count} panelists over two phases is {two_phase}.
Stay inside it — spend it on the panel, not on exploratory delegations.
</democracy_panel>"""


def normalize_democracy_participants(
    raw: object,
    *,
    configured_models: Iterable[str] | None = None,
) -> list[str]:
    """Return the panel a run can actually dispatch, or ``[]`` for no panel.

    Deduplicates while preserving the user's chosen order, drops names that are
    not configured models, caps the roster at :data:`MAX_DEMOCRACY_PARTICIPANTS`,
    and returns ``[]`` when fewer than :data:`MIN_DEMOCRACY_PARTICIPANTS`
    distinct models survive.

    ``configured_models`` of ``None`` means "no catalog to check against" (the
    embedded client, tests) and skips the membership filter; an *empty* catalog
    is a real catalog with nothing in it and drops everything.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    known = None if configured_models is None else {str(name) for name in configured_models}
    seen: set[str] = set()
    panel: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            continue
        name = entry.strip()
        if not name or name in seen:
            continue
        if known is not None and name not in known:
            logger.warning("Democracy panelist %r is not a configured model; dropping it from the panel.", name)
            continue
        seen.add(name)
        panel.append(name)
        if len(panel) == MAX_DEMOCRACY_PARTICIPANTS:
            break
    if len(panel) < MIN_DEMOCRACY_PARTICIPANTS:
        return []
    return panel


def build_democracy_section(participants: list[str], *, max_total: int) -> str:
    """Render the organizer section for a panel, or ``""`` when there is none."""
    if len(participants) < MIN_DEMOCRACY_PARTICIPANTS:
        return ""
    participant_lines = "\n".join(f'- `model="{name}"`' for name in participants)
    return DEMOCRACY_SECTION_TEMPLATE.format(
        participant_lines=participant_lines,
        count=len(participants),
        total=clamp_total_subagents_per_run(max_total),
        two_phase=len(participants) * 2,
    )
