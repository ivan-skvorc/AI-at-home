"""Self-critiquing generation loop — the server-side half (roadmap 14).

The loop belongs to the agent (see ``skills/public/image-refine``); what lives
on the server is exactly the bookkeeping a model cannot be trusted with, and
that is what these tests pin:

* the rubric is frozen before iteration 1, and a verdict cannot judge anything
  outside it;
* the iteration counter is the server's — iteration N+1 is *refused*, with a
  message the agent can report, rather than trusted to stop;
* the wall-clock budget is enforced the same way, which is what makes video
  safe to iterate on;
* a retry names exactly one change, because one change per iteration is what
  makes the loop diagnosable;
* the session record on disk is the audit trail — params, seed, verdict and
  filename per iteration.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from _comfyui_helpers import FakeComfyUIClient, image_output, object_info_for, runtime

from deerflow.community.comfyui import service, tools
from deerflow.community.comfyui.sessions import (
    RefineError,
    RefineLimitError,
    begin_iteration,
    create_session,
    load_session,
    record_generation,
    record_verdict,
    save_session,
    session_path,
    summarize,
)
from deerflow.community.comfyui.templates import load_template
from deerflow.config.media_config import GpuArbiterConfig, MediaConfig, RefineConfig

CRITERIA = ["the cat is orange", "the light is warm afternoon sun", "no text anywhere in frame"]


def _refine_config(**overrides) -> RefineConfig:
    return RefineConfig(**overrides)


def _session(tmp_path: Path, *, criteria=None, config=None, **kwargs):
    return create_session(
        tmp_path,
        goal="a cat on a windowsill",
        criteria=list(criteria or CRITERIA),
        kind="image",
        config=config or _refine_config(),
        **kwargs,
    )


def _all_pass(session):
    return [{"criterion": criterion, "passed": True, "note": "checked"} for criterion in session.criteria]


class TestFrozenRubric:
    def test_a_session_freezes_the_criteria_it_was_opened_with(self, tmp_path: Path):
        session = _session(tmp_path)
        assert session.criteria == CRITERIA
        assert load_session(tmp_path, session.session_id).criteria == CRITERIA

    def test_too_few_criteria_are_refused_with_the_range(self, tmp_path: Path):
        with pytest.raises(RefineError, match="between 3 and 6"):
            _session(tmp_path, criteria=["looks nice"])

    def test_too_many_criteria_are_refused(self, tmp_path: Path):
        with pytest.raises(RefineError, match="between 3 and 6"):
            _session(tmp_path, criteria=[f"criterion {index}" for index in range(7)])

    def test_duplicate_criteria_are_refused(self, tmp_path: Path):
        with pytest.raises(RefineError, match="distinct"):
            _session(tmp_path, criteria=["a", "a", "b"])

    def test_blank_criteria_do_not_pad_the_count(self, tmp_path: Path):
        with pytest.raises(RefineError, match="between 3 and 6"):
            _session(tmp_path, criteria=["a cat", "  ", ""])

    def test_a_verdict_cannot_judge_a_criterion_that_was_not_frozen(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        with pytest.raises(RefineError, match="not one of this session's frozen criteria"):
            record_verdict(session, 1, criteria_results=[{"criterion": "vibes", "passed": True}], overall="accept", change=None)

    def test_every_frozen_criterion_must_be_judged_each_iteration(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        with pytest.raises(RefineError, match="missing"):
            record_verdict(session, 1, criteria_results=[{"criterion": CRITERIA[0], "passed": True}], overall="accept", change=None)


class TestServerHeldCounter:
    def test_the_cap_refuses_the_next_iteration_with_a_reportable_message(self, tmp_path: Path):
        session = _session(tmp_path, config=_refine_config(max_iterations=2))
        begin_iteration(session)
        begin_iteration(session)
        with pytest.raises(RefineLimitError, match="used all 2 iterations"):
            begin_iteration(session)

    def test_a_requested_cap_can_lower_but_never_raise_the_configured_one(self, tmp_path: Path):
        config = _refine_config(max_iterations=4)
        assert _session(tmp_path, config=config, max_iterations=2).max_iterations == 2
        assert _session(tmp_path, config=config, max_iterations=99).max_iterations == 4

    def test_the_wall_clock_budget_refuses_a_late_iteration(self, tmp_path: Path):
        session = _session(tmp_path, config=_refine_config(budget_seconds=60))
        begin_iteration(session, now=1_000.0)
        with pytest.raises(RefineLimitError, match="out of time"):
            begin_iteration(session, now=1_061.0)

    def test_the_budget_starts_at_the_first_iteration_not_at_session_creation(self, tmp_path: Path):
        session = _session(tmp_path, config=_refine_config(budget_seconds=60))
        session.created_at = 0.0
        # Thinking about the rubric for an hour must not consume the budget.
        iteration = begin_iteration(session, now=3_600.0)
        assert iteration.index == 1
        assert begin_iteration(session, now=3_630.0).index == 2

    def test_a_closed_session_refuses_further_iterations(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        record_verdict(session, 1, criteria_results=_all_pass(session), overall="accept", change=None)
        with pytest.raises(RefineLimitError, match="closed"):
            begin_iteration(session)


class TestVerdicts:
    def test_a_retry_must_name_exactly_one_change(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        with pytest.raises(RefineError, match="exactly one change"):
            record_verdict(session, 1, criteria_results=_all_pass(session), overall="retry", change=None)

    def test_a_retry_naming_several_changes_is_refused(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        with pytest.raises(RefineError, match="reads as several"):
            record_verdict(session, 1, criteria_results=_all_pass(session), overall="retry", change="raise cfg to 8 and also add 'studio lighting'")

    def test_an_accept_carries_no_change(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        with pytest.raises(RefineError, match="Only a 'retry'"):
            record_verdict(session, 1, criteria_results=_all_pass(session), overall="accept", change="one more tweak")

    def test_an_unknown_overall_is_refused(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        with pytest.raises(RefineError, match="must be one of"):
            record_verdict(session, 1, criteria_results=_all_pass(session), overall="pretty good", change=None)

    def test_abandon_closes_the_session_instead_of_spinning(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        record_verdict(
            session,
            1,
            criteria_results=[{"criterion": criterion, "passed": False, "note": "not achievable with this checkpoint"} for criterion in session.criteria],
            overall="abandon",
            change=None,
        )
        assert session.closed == "abandon"

    def test_the_verdict_records_the_score_against_the_frozen_list(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        verdict = record_verdict(
            session,
            1,
            criteria_results=[
                {"criterion": CRITERIA[0], "passed": True, "note": "orange tabby"},
                {"criterion": CRITERIA[1], "passed": False, "note": "midday light"},
                {"criterion": CRITERIA[2], "passed": True, "note": "clean"},
            ],
            overall="retry",
            change="add 'golden hour' to the prompt",
        )
        assert (verdict["passed"], verdict["of"]) == (2, 3)
        assert [entry["criterion"] for entry in verdict["criteria"]] == CRITERIA


class TestAuditTrail:
    def test_the_session_file_records_params_seed_verdict_and_filename(self, tmp_path: Path):
        session = _session(tmp_path)
        iteration = begin_iteration(session)
        record_generation(session, iteration.index, params={"steps": 25, "cfg": 6.0}, seed=99, filename="/mnt/user-data/outputs/cat.png")
        record_verdict(session, iteration.index, criteria_results=_all_pass(session), overall="accept", change=None)
        save_session(tmp_path, session)

        stored = json.loads(session_path(tmp_path, session.session_id).read_text())
        entry = stored["iterations"][0]
        assert entry["seed"] == 99
        assert entry["params"]["steps"] == 25
        assert entry["filename"].endswith("cat.png")
        assert entry["verdict"]["overall"] == "accept"

    def test_the_summary_carries_verdicts_forward_without_re_viewing_images(self, tmp_path: Path):
        session = _session(tmp_path)
        begin_iteration(session)
        record_generation(session, 1, params={}, seed=1, filename="a.png")
        record_verdict(session, 1, criteria_results=_all_pass(session)[:2] + [{"criterion": CRITERIA[2], "passed": False, "note": "watermark"}], overall="retry", change="add 'no watermark' to the negative prompt")
        history = summarize(session)["history"]
        assert history[0]["change"] == "add 'no watermark' to the negative prompt"
        assert history[0]["passed"] == 2

    def test_a_session_id_from_another_conversation_is_not_readable_as_a_path(self, tmp_path: Path):
        with pytest.raises(RefineError, match="Invalid refine session id"):
            session_path(tmp_path, "../../etc/passwd")

    def test_an_unknown_session_says_so(self, tmp_path: Path):
        with pytest.raises(RefineError, match="No refine session"):
            load_session(tmp_path, "deadbeefcafe")


@pytest.mark.asyncio
class TestToolBoundary:
    """The counter must bite at the *tool* boundary, not in the model's head."""

    def _config(self, **refine_overrides) -> MediaConfig:
        return MediaConfig(gpu=GpuArbiterConfig(tenants=[]), refine=RefineConfig(**refine_overrides))

    def _client(self):
        template = load_template("txt2img")
        info = object_info_for(template, {("CheckpointLoaderSimple", "ckpt_name"): ["x.safetensors"]})
        return FakeComfyUIClient(info, outputs=[image_output()])

    async def _generate(self, tmp_path: Path, config: MediaConfig, **kwargs):
        service.reset_validation_cache()
        client = self._client()
        with patch.object(tools, "media_config", lambda: config), patch.object(tools, "build_client", lambda *a, **k: client):
            command = await tools.generate_image_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="t1", prompt="a cat", **kwargs)
        return command.update["messages"][0].content

    async def test_refine_start_returns_a_session_the_generate_tool_counts_against(self, tmp_path: Path):
        config = self._config(max_iterations=2)
        with patch.object(tools, "media_config", lambda: config):
            started = await tools.refine_start_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="t0", goal="a cat", criteria=CRITERIA)
        session_id = json.loads(started.update["messages"][0].content)["session_id"]

        first = json.loads(await self._generate(tmp_path, config, session_id=session_id))
        assert first["session"]["iterations_used"] == 1
        assert first["session"]["iterations_remaining"] == 1

    async def test_the_cap_is_enforced_by_the_tool_when_the_model_tries_to_exceed_it(self, tmp_path: Path):
        config = self._config(max_iterations=1)
        with patch.object(tools, "media_config", lambda: config):
            started = await tools.refine_start_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="t0", goal="a cat", criteria=CRITERIA)
        session_id = json.loads(started.update["messages"][0].content)["session_id"]

        await self._generate(tmp_path, config, session_id=session_id)
        refused = await self._generate(tmp_path, config, session_id=session_id)
        assert "used all 1 iterations" in refused
        assert refused.startswith("Error:")

    async def test_refine_start_refuses_a_rubric_that_cannot_be_judged(self, tmp_path: Path):
        config = self._config()
        with patch.object(tools, "media_config", lambda: config):
            command = await tools.refine_start_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="t0", goal="a cat", criteria=["looks nice"])
        assert "between 3 and 6" in command.update["messages"][0].content

    async def test_the_verdict_tool_records_against_the_frozen_rubric(self, tmp_path: Path):
        config = self._config()
        with patch.object(tools, "media_config", lambda: config):
            started = await tools.refine_start_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="t0", goal="a cat", criteria=CRITERIA)
            session_id = json.loads(started.update["messages"][0].content)["session_id"]
            await self._generate(tmp_path, config, session_id=session_id)
            command = await tools.refine_verdict_tool.coroutine(
                runtime=runtime(str(tmp_path)),
                tool_call_id="t2",
                session_id=session_id,
                iteration=1,
                criteria_results=[{"criterion": criterion, "passed": True, "note": "ok"} for criterion in CRITERIA],
                overall="accept",
            )
        payload = json.loads(command.update["messages"][0].content)
        assert payload["closed"] == "accept"
        assert payload["verdict"]["passed"] == 3

    async def test_a_verdict_the_model_shaped_wrongly_is_refused_not_stored(self, tmp_path: Path):
        config = self._config()
        with patch.object(tools, "media_config", lambda: config):
            started = await tools.refine_start_tool.coroutine(runtime=runtime(str(tmp_path)), tool_call_id="t0", goal="a cat", criteria=CRITERIA)
            session_id = json.loads(started.update["messages"][0].content)["session_id"]
            await self._generate(tmp_path, config, session_id=session_id)
            command = await tools.refine_verdict_tool.coroutine(
                runtime=runtime(str(tmp_path)),
                tool_call_id="t2",
                session_id=session_id,
                iteration=1,
                criteria_results=[{"criterion": criterion, "passed": False, "note": "no"} for criterion in CRITERIA],
                overall="retry",
            )
        assert "exactly one change" in command.update["messages"][0].content
        assert load_session(tmp_path, session_id).iterations[0].verdict is None


class TestSkillContract:
    """The loop lives in the skill; these are the instructions that carry it.

    Each assertion is a rule the loop stops working without: the counter is on
    the server, the seed is held so a change is attributable, only the newest
    result is viewed, and a text-only model must not iterate blind.
    """

    SKILL = Path(__file__).resolve().parents[2] / "skills" / "public" / "image-refine" / "SKILL.md"

    def _prose(self) -> str:
        """The skill text with line wrapping collapsed, so rewrapping is not a failure."""
        return " ".join(self.SKILL.read_text(encoding="utf-8").split())

    def test_the_skill_exists_and_declares_itself(self):
        text = self.SKILL.read_text(encoding="utf-8")
        assert text.startswith("---\nname: image-refine\n")
        assert "description:" in text.split("---")[1]

    def test_it_tells_the_agent_to_freeze_criteria_before_generating(self):
        prose = self._prose()
        assert "refine_start" in prose
        assert "3–6 checkable criteria" in prose

    def test_it_states_the_seed_discipline(self):
        prose = self._prose()
        assert "SAME seed" in prose
        assert "Changing the seed is itself the one change" in prose

    def test_it_forbids_re_viewing_every_earlier_image(self):
        assert "Only view the newest result each round" in self._prose()

    def test_it_documents_the_vision_constraint_instead_of_degrading_silently(self):
        prose = self._prose()
        assert "view_image" in prose
        assert "do not iterate blind" in prose

    def test_it_refuses_to_route_around_the_cap(self):
        assert "Do **not** open a second session to get around the cap" in self._prose()

    def test_video_is_judged_from_the_contact_sheet(self):
        assert "view the contact sheet, not the clip" in self._prose()

    def test_an_unreachable_service_sends_the_agent_to_the_cloud_skill(self):
        """The tools now ship enabled, so "missing tool" is no longer the signal.

        On a machine with no GPU nothing is provisioned and the tools stay bound,
        answering with an error. Without this sentence the agent retries a local
        service that will never come up instead of falling back — which is the
        whole reason the tools are left bound rather than unbound.
        """
        prose = self._prose()
        assert "unreachable" in prose
        assert "cloud `image-generation` skill instead" in prose
