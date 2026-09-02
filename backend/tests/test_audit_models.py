"""Tests for scripts/audit_models.py — the model & pricing drift audit (roadmap item 4).

FORK.md concedes that the existing tests "do not catch a stale-but-well-formed
price or a since-renamed slug, because both pass against any syntactically valid
entry", and names the specific failure: an expired promo leaves the chat header
advertising a discount nobody is getting. This audit is the thing that catches
those, so its own failure modes matter:

- an unreachable provider must be a *skip*, never a red job people learn to ignore;
- it must never propose auto-committing a price;
- a finding must name which of the two synced sources needs the edit.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_models.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("audit_models", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_script()


# The current shape: the price is data in `price:`/`discount:`, and the name is
# only a label. `TestLegacyPricingBlock` keeps the old `pricing:` spelling
# covered, because a user's own config may still carry it.
CONFIG_BLOCK = """models:
  # === BEGIN auto-model-config: openrouter (uncommented at startup when OPENROUTER_API_KEY is set) ===
  # - name: openrouter-alpha
  #   display_name: Alpha (OpenRouter) (p)
  #   use: langchain_openai:ChatOpenAI
  #   model: vendor/alpha
  #   price:
  #     currency: USD
  #     input: 2.0
  #     output: 6.0
  #
  # - name: openrouter-beta
  #   display_name: Beta (OpenRouter) (p)
  #   use: langchain_openai:ChatOpenAI
  #   model: vendor/beta
  #   price:
  #     currency: USD
  #     input: 1.0
  #     output: 4.0
  #   discount:
  #     input: 0.5
  #     output: 2.0
  #     until: 2099-12-31
  # === END auto-model-config: openrouter ===
"""

# A config written before prices moved out of the name. The audit must keep
# reading these, because `config_upgrade.py` cannot rewrite a list entry, so
# every pre-existing install still looks exactly like this.
LEGACY_CONFIG_BLOCK = """models:
  # === BEGIN auto-model-config: openrouter (uncommented at startup when OPENROUTER_API_KEY is set) ===
  # - name: openrouter-alpha
  #   display_name: Alpha ($2/6) (OpenRouter) (p)
  #   use: langchain_openai:ChatOpenAI
  #   model: vendor/alpha
  #   pricing:
  #     currency: USD
  #     input_per_million: 2.0
  #     output_per_million: 6.0
  # === END auto-model-config: openrouter ===
"""


def catalog(**slugs) -> dict:
    return {"openrouter": {"models": slugs, "reachable": True}}


# ---------------------------------------------------------------------------
# Parsing the two synced sources
# ---------------------------------------------------------------------------


class TestParseMarkerBlocks:
    def test_reads_commented_entries_out_of_a_marker_block(self):
        entries = audit.parse_marker_blocks(CONFIG_BLOCK)
        assert {e.name for e in entries} == {"openrouter-alpha", "openrouter-beta"}
        alpha = next(e for e in entries if e.name == "openrouter-alpha")
        assert alpha.provider == "openrouter"
        assert alpha.slug == "vendor/alpha"
        assert alpha.input_per_million == 2.0
        assert alpha.output_per_million == 6.0
        assert alpha.promo_input_per_million is None

    def test_reads_the_promo_pair(self):
        beta = next(e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-beta")
        assert beta.promo_input_per_million == 0.5
        assert beta.promo_output_per_million == 2.0

    def test_entries_outside_a_marker_block_are_ignored(self):
        text = "models:\n  - name: hand-edited\n    model: local\n" + CONFIG_BLOCK
        assert all(e.name != "hand-edited" for e in audit.parse_marker_blocks(text))

    def test_the_real_config_example_parses(self):
        entries = audit.parse_marker_blocks((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
        assert len(entries) > 20
        # Every bundled entry must carry a price; that is what the audit checks.
        assert all(e.input_per_million is not None for e in entries), [e.name for e in entries if e.input_per_million is None]

    def test_the_wizard_bundles_load(self):
        entries = audit.load_wizard_bundles()
        assert len(entries) > 20
        assert all(e.source == "scripts/wizard/providers.py" for e in entries)


class TestDisplayNamePrices:
    def test_extracts_list_and_promo_from_the_name(self):
        assert audit.prices_in_display_name("Beta ($1/4 → $0.5/2*) (OpenRouter) (p)") == (1.0, 4.0, 0.5, 2.0)

    def test_list_only(self):
        assert audit.prices_in_display_name("Alpha ($2/6) (OpenRouter)") == (2.0, 6.0, None, None)

    def test_no_price_at_all(self):
        assert audit.prices_in_display_name("Some Local Model (Ollama)") == (None, None, None, None)


# ---------------------------------------------------------------------------
# Diffing against a live catalog
# ---------------------------------------------------------------------------


class TestDiff:
    def test_matching_prices_produce_no_findings(self):
        entries = audit.parse_marker_blocks(CONFIG_BLOCK)
        findings = audit.diff_against_catalog(
            entries, catalog(**{"vendor/alpha": {"input_per_million": 2.0, "output_per_million": 6.0}, "vendor/beta": {"input_per_million": 1.0, "output_per_million": 4.0, "promo_input_per_million": 0.5, "promo_output_per_million": 2.0}})
        )
        assert findings == []

    def test_a_retired_slug_is_reported(self):
        entries = audit.parse_marker_blocks(CONFIG_BLOCK)
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/beta": {"input_per_million": 1.0, "output_per_million": 4.0, "promo_input_per_million": 0.5, "promo_output_per_million": 2.0}}))
        assert [f.kind for f in findings] == ["retired_slug"]
        assert findings[0].slug == "vendor/alpha"

    def test_a_changed_list_price_is_reported_with_both_numbers(self):
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-alpha"]
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {"input_per_million": 3.0, "output_per_million": 6.0}}))
        assert [f.kind for f in findings] == ["price_changed"]
        assert "2.0" in findings[0].detail and "3.0" in findings[0].detail

    def test_an_expired_promo_is_reported(self):
        # The silent failure FORK.md names: config still advertises a discount
        # that the provider has stopped running.
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-beta"]
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/beta": {"input_per_million": 1.0, "output_per_million": 4.0}}))
        assert [f.kind for f in findings] == ["promo_ended"]
        assert "header" in findings[0].detail.lower() or "advertis" in findings[0].detail.lower()

    def test_a_new_promo_is_reported(self):
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-alpha"]
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {"input_per_million": 2.0, "output_per_million": 6.0, "promo_input_per_million": 1.0, "promo_output_per_million": 3.0}}))
        assert [f.kind for f in findings] == ["promo_started"]

    def test_tiny_float_differences_are_not_findings(self):
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-alpha"]
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {"input_per_million": 2.0000001, "output_per_million": 5.9999998}}))
        assert findings == []

    def test_an_unreachable_provider_produces_no_findings_at_all(self):
        entries = audit.parse_marker_blocks(CONFIG_BLOCK)
        findings = audit.diff_against_catalog(entries, {"openrouter": {"models": {}, "reachable": False}})
        # Crucially not "every slug retired" — that is how an audit becomes noise.
        assert findings == []

    def test_a_provider_with_no_catalog_at_all_is_skipped(self):
        entries = audit.parse_marker_blocks(CONFIG_BLOCK)
        assert audit.diff_against_catalog(entries, {}) == []

    def test_a_catalog_without_prices_only_checks_slug_existence(self):
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-alpha"]
        assert audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {}})) == []
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/other": {}}))
        assert [f.kind for f in findings] == ["retired_slug"]


# ---------------------------------------------------------------------------
# Discovery: the only check that can grow the roster
# ---------------------------------------------------------------------------

DAY = 86400.0
# A fixed "today" so the window tests never depend on the wall clock.
NOW = 1_800_000_000.0

# The two slugs CONFIG_BLOCK bundles, dated well outside the candidate window so
# they act only as the lab's baseline and never as candidates themselves.
BASELINE = {"vendor/alpha": {"created": NOW - 400 * DAY}, "vendor/beta": {"created": NOW - 300 * DAY}}


def candidates(*, now=NOW, **slugs):
    entries = audit.parse_marker_blocks(CONFIG_BLOCK)
    return audit.find_new_candidates(entries, catalog(**slugs), now=now)


class TestNewCandidates:
    """FORK.md's discovery step, the half a machine can do.

    Every other check in this audit asks about models the bundle already
    carries, so a lab shipping a new flagship is invisible to all of them: the
    2026-08-20 pass found *four* labs a generation behind at once, caught by eye
    rather than by any gate. This reports "something newer exists under a lab you
    already bundle" and stops there — whether it belongs is the acclaim
    judgement FORK.md reserves for a human reading OpenRouter's rankings.
    """

    def test_a_newer_model_from_a_bundled_lab_is_reported(self):
        findings = candidates(**BASELINE, **{"vendor/gamma": {"created": NOW - 5 * DAY}})
        assert [f.kind for f in findings] == ["new_candidate"]
        assert findings[0].slug == "vendor/gamma"

    def test_it_proposes_and_never_instructs(self):
        # The finding is evidence of existence, not of merit. If it ever starts
        # reading as "add this", the roster grows on a catalog's say-so.
        finding = candidates(**BASELINE, **{"vendor/gamma": {"created": NOW - 5 * DAY}})[0]
        text = (finding.detail + " " + finding.suggestion).lower()
        assert "acclaim" in text
        assert "model-audit-log" in text

    def test_a_model_older_than_the_lab_baseline_is_not_a_candidate(self):
        # Every lab has a back catalogue. Reporting it would bury the one entry
        # that actually shipped this month.
        assert candidates(**BASELINE, **{"vendor/ancient": {"created": NOW - 500 * DAY}}) == []

    def test_a_candidate_ages_out_of_the_window(self):
        """A declined candidate must stop being reported on its own.

        This is the property that keeps the weekly job closable: without it, a
        model the maintainer looked at and rejected reappears in the issue every
        Monday forever, which is precisely how a job becomes one people mute.
        """
        recent = candidates(**BASELINE, **{"vendor/gamma": {"created": NOW - 59 * DAY}})
        assert [f.slug for f in recent] == ["vendor/gamma"]
        assert candidates(**BASELINE, **{"vendor/gamma": {"created": NOW - 61 * DAY}}) == []

    def test_a_variant_slug_is_never_a_candidate(self):
        # `:free`/`:nitro` are routing variants of a model, not a new model.
        assert candidates(**BASELINE, **{"vendor/alpha:free": {"created": NOW - 2 * DAY}, "vendor/gamma:nitro": {"created": NOW - 2 * DAY}}) == []

    def test_an_already_bundled_slug_is_not_a_candidate(self):
        fresh_baseline = {"vendor/alpha": {"created": NOW - 400 * DAY}, "vendor/beta": {"created": NOW - 2 * DAY}}
        assert candidates(**fresh_baseline) == []

    def test_a_lab_the_bundle_does_not_carry_is_ignored(self):
        # Discovering a whole new lab is step 2's third question and a human
        # judgement; the catalog has hundreds, so reporting them is noise.
        assert candidates(**BASELINE, **{"otherlab/flagship": {"created": NOW - 2 * DAY}}) == []

    def test_a_lab_with_no_dated_baseline_is_skipped(self):
        # Nothing to compare against. Silence beats treating every slug in the
        # lab as newer than the bundle.
        assert candidates(**{"vendor/alpha": {}, "vendor/beta": {}, "vendor/gamma": {"created": NOW - 2 * DAY}}) == []

    def test_an_unreachable_catalog_produces_no_candidates(self):
        entries = audit.parse_marker_blocks(CONFIG_BLOCK)
        assert audit.find_new_candidates(entries, {"openrouter": {"models": {"vendor/gamma": {"created": NOW}}, "reachable": False}}, now=NOW) == []

    def test_candidates_are_newest_first_and_capped_per_lab(self):
        flood = {f"vendor/new-{n}": {"created": NOW - n * DAY} for n in range(1, 8)}
        findings = candidates(**BASELINE, **flood)
        assert [f.slug for f in findings] == ["vendor/new-1", "vendor/new-2", "vendor/new-3"]

    def test_the_catalog_name_is_used_when_the_catalog_has_one(self):
        findings = candidates(**BASELINE, **{"vendor/gamma": {"created": NOW - 2 * DAY, "name": "Vendor Gamma"}})
        assert findings[0].name == "Vendor Gamma"

    def test_the_live_parse_keeps_the_release_date(self):
        # Without `created` surviving the parse, discovery has nothing to sort
        # on and silently reports nothing.
        payload = {"data": [{"id": "vendor/alpha", "name": "Vendor Alpha", "created": 1700000000, "pricing": {"prompt": "0.000002", "completion": "0.000006"}}]}
        models = audit.parse_openrouter_catalog(payload)
        assert models["vendor/alpha"]["created"] == 1700000000.0
        assert models["vendor/alpha"]["name"] == "Vendor Alpha"

    def test_a_candidate_reaches_the_report_under_its_own_heading(self):
        body = audit.render_report(candidates(**BASELINE, **{"vendor/gamma": {"created": NOW - 2 * DAY}}), skipped=[])
        assert "vendor/gamma" in body
        assert audit._KIND_TITLE["new_candidate"] in body


class TestInternalConsistency:
    def test_a_price_in_a_display_name_is_a_finding(self):
        """The regression guard for the change that moved prices out of names.

        A price in the name is a second copy of a number that is already data;
        re-adding one brings back the drift where the figure a user reads and
        the figure they are billed against can disagree.
        """
        text = CONFIG_BLOCK.replace("display_name: Alpha", "display_name: Alpha ($9/6)")
        findings = audit.check_internal_consistency(audit.parse_marker_blocks(text))
        assert [f.kind for f in findings] == ["price_in_display_name"]

    def test_a_starred_promo_pair_in_a_name_is_also_a_finding(self):
        text = CONFIG_BLOCK.replace("display_name: Alpha", "display_name: Alpha ($2/6 -> $1/3*)".replace("->", "\u2192"))
        findings = audit.check_internal_consistency(audit.parse_marker_blocks(text))
        assert [f.kind for f in findings] == ["price_in_display_name"]

    def test_the_shipped_config_carries_no_price_in_any_name(self):
        entries = audit.parse_marker_blocks((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
        assert audit.check_internal_consistency(entries) == []

    def test_an_open_ended_discount_is_not_reported(self):
        """Deliberately quiet: several providers run promotions with no end date.

        A weekly issue for a condition the maintainer cannot resolve is how this
        job becomes one people learn to ignore, which costs more than the drift
        it detects. FORK.md's checklist covers the human review instead.
        """
        entries = audit.parse_marker_blocks((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
        open_ended = [e for e in entries if e.promo_input_per_million is not None and not e.discount_until]
        assert open_ended, "fixture assumption: the bundle still ships an open-ended discount"
        assert audit.check_internal_consistency(entries) == []

    def test_the_two_synced_sources_agree_today(self):
        config_entries = audit.parse_marker_blocks((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
        wizard_entries = audit.load_wizard_bundles()
        assert audit.check_source_parity(config_entries, wizard_entries) == []

    def test_source_parity_reports_a_price_that_moved_in_only_one_source(self):
        config_entries = audit.parse_marker_blocks(CONFIG_BLOCK)
        wizard_entries = [
            audit.BundledModel(
                provider="openrouter",
                name="openrouter-alpha",
                slug="vendor/alpha",
                display_name="Alpha ($7/6) (OpenRouter) (p)",
                input_per_million=7.0,
                output_per_million=6.0,
                promo_input_per_million=None,
                promo_output_per_million=None,
                source="scripts/wizard/providers.py",
            )
        ]
        findings = audit.check_source_parity(config_entries, wizard_entries)
        assert [f.kind for f in findings] == ["source_disagreement"]
        assert "config.example.yaml" in findings[0].detail
        assert "providers.py" in findings[0].detail


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class TestReport:
    def test_a_clean_report_says_so_and_suggests_nothing(self):
        body = audit.render_report([], skipped=["openai (no key)"])
        assert "No drift" in body
        assert "openai (no key)" in body

    def test_findings_render_with_a_suggested_diff(self):
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-alpha"]
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {"input_per_million": 3.0, "output_per_million": 6.0}}))
        body = audit.render_report(findings, skipped=[])
        assert "openrouter-alpha" in body
        assert "```diff" in body
        assert "input_per_million: 3.0" in body

    def test_the_report_refuses_to_present_itself_as_authoritative(self):
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-alpha"]
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {"input_per_million": 3.0, "output_per_million": 6.0}}))
        body = audit.render_report(findings, skipped=[])
        # A wrong automated price is worse than a stale one — the report must
        # send a human to the provider's own page rather than invite a merge.
        assert "provider's own page" in body
        assert "not auto-applied" in body.lower() or "do not auto" in body.lower()

    def test_both_sources_are_named_in_the_suggested_edit(self):
        entries = [e for e in audit.parse_marker_blocks(CONFIG_BLOCK) if e.name == "openrouter-alpha"]
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {"input_per_million": 3.0, "output_per_million": 6.0}}))
        body = audit.render_report(findings, skipped=[])
        assert "config.example.yaml" in body
        assert "scripts/wizard/providers.py" in body


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


class TestFetchOpenRouter:
    def test_converts_per_token_strings_to_per_million(self):
        payload = {"data": [{"id": "vendor/alpha", "pricing": {"prompt": "0.000002", "completion": "0.000006"}}]}
        models = audit.parse_openrouter_catalog(payload)
        assert models["vendor/alpha"]["input_per_million"] == 2.0
        assert models["vendor/alpha"]["output_per_million"] == 6.0

    def test_a_free_variant_is_not_read_as_a_promo_on_the_paid_slug(self):
        payload = {
            "data": [
                {"id": "vendor/alpha", "pricing": {"prompt": "0.000002", "completion": "0.000006"}},
                {"id": "vendor/alpha:free", "pricing": {"prompt": "0", "completion": "0"}},
            ]
        }
        models = audit.parse_openrouter_catalog(payload)
        assert models["vendor/alpha"]["input_per_million"] == 2.0
        assert "promo_input_per_million" not in models["vendor/alpha"]

    def test_malformed_entries_are_skipped_rather_than_crashing(self):
        payload = {"data": [{"id": "ok", "pricing": {"prompt": "0.000001", "completion": "0.000002"}}, {"no_id": True}, {"id": "bad", "pricing": {"prompt": "abc"}}]}
        models = audit.parse_openrouter_catalog(payload)
        assert "ok" in models
        assert "bad" not in models

    def test_an_unreachable_endpoint_reports_unreachable_not_empty(self):
        def failing_get(url, timeout):
            raise OSError("no network")

        result = audit.fetch_openrouter(get=failing_get)
        assert result["reachable"] is False
        assert result["models"] == {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_runs_offline_against_a_catalog_fixture(self, tmp_path, capsys):
        fixture = tmp_path / "catalog.json"
        fixture.write_text(json.dumps({"openrouter": {"reachable": True, "models": {}}}), encoding="utf-8")
        code = audit.main(["--catalog", str(fixture), "--format", "markdown"])
        out = capsys.readouterr().out
        assert code == 0
        assert "retired" in out.lower() or "No drift" in out

    def test_exit_code_is_zero_even_with_findings_by_default(self, tmp_path, capsys):
        fixture = tmp_path / "catalog.json"
        fixture.write_text(json.dumps({"openrouter": {"reachable": True, "models": {}}}), encoding="utf-8")
        assert audit.main(["--catalog", str(fixture)]) == 0
        capsys.readouterr()

    def test_fail_on_findings_is_opt_in(self, tmp_path, capsys):
        fixture = tmp_path / "catalog.json"
        fixture.write_text(json.dumps({"openrouter": {"reachable": True, "models": {}}}), encoding="utf-8")
        code = audit.main(["--catalog", str(fixture), "--fail-on-findings"])
        capsys.readouterr()
        assert code == 1

    def test_an_all_unreachable_run_never_fails(self, tmp_path, capsys):
        fixture = tmp_path / "catalog.json"
        fixture.write_text(json.dumps({"openrouter": {"reachable": False, "models": {}}}), encoding="utf-8")
        code = audit.main(["--catalog", str(fixture), "--fail-on-findings"])
        out = capsys.readouterr().out
        assert code == 0
        assert "skipped" in out.lower()

    def test_json_output_is_machine_readable(self, tmp_path, capsys):
        fixture = tmp_path / "catalog.json"
        fixture.write_text(json.dumps({"openrouter": {"reachable": True, "models": {}}}), encoding="utf-8")
        audit.main(["--catalog", str(fixture), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert "findings" in payload and "skipped" in payload


class TestStaleFixture:
    """The workflow's own self-test: a deliberately stale fixture must produce findings."""

    def test_the_committed_stale_fixture_produces_a_readable_issue(self, capsys):
        fixture = REPO_ROOT / "scripts" / "fixtures" / "model_audit_stale_catalog.json"
        assert fixture.exists(), "the stale fixture is what proves the audit still detects drift"
        code = audit.main(["--catalog", str(fixture), "--format", "markdown"])
        body = capsys.readouterr().out
        assert code == 0
        assert "No drift" not in body
        assert "```diff" in body


class TestLegacyPricingBlock:
    """A config written before prices moved out of `display_name`.

    `config_upgrade.py` cannot add or rewrite a key inside an existing list
    entry, so every install that predates the change still carries the old
    `pricing:` block and the old name. The audit must keep reading those, or it
    goes quiet on exactly the configs most likely to have drifted.
    """

    def test_a_legacy_pricing_block_is_still_read(self):
        entries = audit.parse_marker_blocks(LEGACY_CONFIG_BLOCK)
        assert len(entries) == 1
        assert entries[0].input_per_million == 2.0
        assert entries[0].output_per_million == 6.0

    def test_a_legacy_entry_still_diffs_against_the_catalog(self):
        entries = audit.parse_marker_blocks(LEGACY_CONFIG_BLOCK)
        findings = audit.diff_against_catalog(entries, catalog(**{"vendor/alpha": {"input_per_million": 9.0, "output_per_million": 6.0}}))
        assert [f.kind for f in findings] == ["price_changed"]

    def test_a_legacy_name_is_reported_so_it_gets_migrated(self):
        # Its price lives in the name, which is the thing being moved away from.
        findings = audit.check_internal_consistency(audit.parse_marker_blocks(LEGACY_CONFIG_BLOCK))
        assert [f.kind for f in findings] == ["price_in_display_name"]
