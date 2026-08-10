"""Unit tests for scripts/exposure.py — the effective-exposure calculator.

Run from repo root:
    cd backend && uv run pytest tests/test_exposure.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import exposure


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# classify_bind_host
# ---------------------------------------------------------------------------


class TestClassifyBindHost:
    def test_loopback_spellings(self):
        for value in ("127.0.0.1", "127.1.2.3", "::1", "localhost"):
            assert exposure.classify_bind_host(value) == "loopback", value

    def test_wildcards(self):
        for value in ("0.0.0.0", "::", "*", "", None):
            assert exposure.classify_bind_host(value) == "wildcard", value

    def test_tailscale_is_not_reported_as_a_plain_private_lan(self):
        # 100.64.0.0/10 is CGNAT, which Python also reports as "private"; the
        # ordering in classify_bind_host is what keeps the two apart.
        assert exposure.classify_bind_host("100.101.102.103") == "tailscale"
        assert exposure.classify_bind_host("fd7a:115c:a1e0::1") == "tailscale"

    def test_private_lan(self):
        for value in ("192.168.1.10", "10.0.0.5", "172.16.3.4", "169.254.1.1"):
            assert exposure.classify_bind_host(value) == "private", value

    def test_public(self):
        # 203.0.113.0/24 (TEST-NET-3) is deliberately not used here: Python's
        # is_private covers the documentation ranges, so it classifies as private.
        assert exposure.classify_bind_host("8.8.8.8") == "public"
        assert exposure.classify_bind_host("2606:4700:4700::1111") == "public"

    def test_hostname_is_unknown_rather_than_guessed(self):
        assert exposure.classify_bind_host("deerflow.example.com") == "unknown"


# ---------------------------------------------------------------------------
# resolve_facts
# ---------------------------------------------------------------------------


class TestResolveFacts:
    def test_docker_surface_defaults_to_loopback(self, tmp_path):
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={})
        assert facts.bind_host == "127.0.0.1"
        assert facts.reach == "loopback"
        assert facts.bind_source == "default"

    def test_local_surface_is_always_the_wildcard(self, tmp_path):
        # scripts/serve.sh runs docker/nginx/nginx.local.conf, whose `listen 2026;`
        # has no address — BIND_HOST does not apply to `make dev` at all.
        facts = exposure.resolve_facts(tmp_path, surface="local", env={"BIND_HOST": "127.0.0.1"})
        assert facts.reach == "wildcard"
        assert facts.bind_source == "nginx.local.conf"

    def test_dotenv_supplies_bind_host_when_the_environment_does_not(self, tmp_path):
        (tmp_path / ".env").write_text("BIND_HOST=100.64.1.2\n", encoding="utf-8")
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={})
        assert facts.bind_host == "100.64.1.2"
        assert facts.reach == "tailscale"
        assert facts.bind_source == ".env"

    def test_process_environment_wins_over_dotenv(self, tmp_path):
        (tmp_path / ".env").write_text("BIND_HOST=192.168.1.5\n", encoding="utf-8")
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={"BIND_HOST": "127.0.0.1"})
        assert facts.bind_host == "127.0.0.1"
        assert facts.bind_source == "environment"

    def test_auth_is_disabled_by_default_on_both_launch_paths(self, tmp_path):
        # serve.sh and deploy.sh both default DEER_FLOW_AUTH_DISABLED to 1.
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={})
        assert facts.auth_disabled_requested is True
        assert facts.auth_disabled_effective is True

    def test_explicit_opt_out_restores_the_login_wall(self, tmp_path):
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={"DEER_FLOW_AUTH_DISABLED": "0"})
        assert facts.auth_disabled_requested is False
        assert facts.auth_disabled_effective is False

    def test_production_environment_neutralizes_the_passwordless_default(self, tmp_path):
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={"DEER_FLOW_ENV": "production"})
        assert facts.auth_disabled_requested is True
        assert facts.auth_disabled_effective is False
        assert facts.production_env is True

    def test_multi_user_mode_defaults_to_on(self, tmp_path):
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={})
        assert facts.multi_user_mode is True

    def test_multi_user_mode_is_read_from_runtime_settings(self, tmp_path):
        home = tmp_path / "backend" / ".deer-flow"
        home.mkdir(parents=True)
        (home / "runtime_settings.json").write_text(json.dumps({"multi_user_mode": False}), encoding="utf-8")
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={})
        assert facts.multi_user_mode is False

    def test_deer_flow_home_overrides_the_search(self, tmp_path):
        home = tmp_path / "elsewhere"
        home.mkdir()
        (home / "runtime_settings.json").write_text(json.dumps({"multi_user_mode": False}), encoding="utf-8")
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={"DEER_FLOW_HOME": str(home)})
        assert facts.multi_user_mode is False

    def test_sandbox_isolation_is_read_from_config(self, tmp_path):
        write_config(tmp_path, "sandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\n")
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={})
        assert facts.sandbox_isolated is True
        assert facts.host_bash is False

    def test_local_sandbox_with_host_bash_is_host_code_execution(self, tmp_path):
        write_config(tmp_path, "sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n  allow_host_bash: true\n")
        facts = exposure.resolve_facts(tmp_path, surface="docker", env={})
        assert facts.sandbox_isolated is False
        assert facts.host_bash is True


# ---------------------------------------------------------------------------
# assess — the tiers
# ---------------------------------------------------------------------------


def facts(**overrides) -> exposure.DeploymentFacts:
    base = dict(
        surface="docker",
        bind_host="127.0.0.1",
        bind_source="default",
        reach="loopback",
        auth_disabled_requested=True,
        auth_disabled_effective=True,
        production_env=False,
        multi_user_mode=True,
        sandbox_isolated=True,
        host_bash=False,
        config_present=True,
    )
    base.update(overrides)
    return exposure.DeploymentFacts(**base)


class TestAssess:
    def test_loopback_with_auth_off_is_fine_and_says_so(self):
        result = exposure.assess(facts())
        assert result.tier == "local-only"
        assert result.status == "ok"
        # The fork's happy path must not nag.
        assert not any(f.contributes for f in result.factors)
        assert "this machine" in result.headline

    def test_loopback_stays_ok_even_with_every_other_setting_relaxed(self):
        result = exposure.assess(facts(multi_user_mode=False, sandbox_isolated=False, host_bash=True))
        assert result.tier == "local-only"
        assert result.status == "ok"

    def test_tailscale_bind_with_auth_off_warns_but_names_the_overlay(self):
        result = exposure.assess(facts(bind_host="100.64.1.2", reach="tailscale"))
        assert result.tier == "trusted-network"
        assert result.status == "warn"
        assert "tailnet" in result.headline.lower()

    def test_wildcard_bind_with_auth_off_is_the_loud_one(self):
        result = exposure.assess(facts(bind_host="0.0.0.0", reach="wildcard"))
        assert result.tier == "open-network"
        assert result.status == "warn"

    def test_the_warning_names_every_contributing_setting_and_a_fix(self):
        result = exposure.assess(
            facts(
                bind_host="0.0.0.0",
                reach="wildcard",
                multi_user_mode=False,
                sandbox_isolated=False,
                host_bash=True,
            )
        )
        contributing = {f.name for f in result.factors if f.contributes}
        assert contributing == {"bind", "auth", "multi-user", "sandbox"}
        for factor in result.factors:
            if factor.contributes:
                assert factor.fix, f"{factor.name} contributes but offers no fix"

    def test_auth_on_keeps_a_public_bind_out_of_the_loud_tier(self):
        result = exposure.assess(facts(bind_host="203.0.113.7", reach="public", auth_disabled_effective=False))
        assert result.tier == "trusted-network"
        assert result.status == "warn"
        assert not any(f.name == "auth" and f.contributes for f in result.factors)

    def test_production_environment_is_credited_for_re_enabling_auth(self):
        result = exposure.assess(
            facts(
                bind_host="0.0.0.0",
                reach="wildcard",
                auth_disabled_requested=True,
                auth_disabled_effective=False,
                production_env=True,
            )
        )
        auth = next(f for f in result.factors if f.name == "auth")
        assert auth.contributes is False
        assert "production" in auth.detail.lower()

    def test_multi_user_off_alone_does_not_contribute_when_nobody_can_reach_it(self):
        result = exposure.assess(facts(multi_user_mode=False))
        assert not any(f.name == "multi-user" and f.contributes for f in result.factors)

    def test_an_unknown_bind_host_is_treated_as_reachable_rather_than_assumed_safe(self):
        result = exposure.assess(facts(bind_host="deerflow.example.com", reach="unknown"))
        assert result.tier != "local-only"

    def test_summary_line_is_single_line_and_names_the_tier(self):
        result = exposure.assess(facts())
        assert "\n" not in result.summary_line()
        assert "local-only" in result.summary_line()


# ---------------------------------------------------------------------------
# Rendering + CLI
# ---------------------------------------------------------------------------


class TestRender:
    def test_report_lines_include_the_fixes_for_contributing_settings(self):
        result = exposure.assess(facts(bind_host="0.0.0.0", reach="wildcard", multi_user_mode=False))
        text = "\n".join(exposure.report_lines(result))
        assert "0.0.0.0" in text
        assert "DEER_FLOW_AUTH_DISABLED=0" in text

    def test_ok_report_is_short(self):
        result = exposure.assess(facts())
        assert len(exposure.report_lines(result)) == 1

    def test_cli_json_round_trips(self, tmp_path, capsys):
        code = exposure.main(["--surface", "docker", "--format", "json", "--project-root", str(tmp_path)])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["tier"] == "local-only"
        assert payload["surface"] == "docker"
        assert isinstance(payload["factors"], list)

    def test_cli_never_fails_the_caller(self, tmp_path, capsys):
        # The launch scripts call this inline; a diagnosis must not break a start.
        code = exposure.main(["--surface", "local", "--project-root", str(tmp_path)])
        capsys.readouterr()
        assert code == 0


# ---------------------------------------------------------------------------
# doctor integration
# ---------------------------------------------------------------------------


class TestDoctorExposureCheck:
    def test_loopback_default_reports_ok(self, tmp_path):
        import doctor

        results = doctor.check_deployment_exposure(tmp_path, env={})
        assert [r.status for r in results] == ["ok", "warn"]  # docker entry, then local dev entry
        assert results[0].label == "network exposure (make up)"
        assert results[1].label == "network exposure (make dev)"

    def test_exposed_docker_entry_warns_with_the_fix(self, tmp_path):
        import doctor

        (tmp_path / ".env").write_text("BIND_HOST=0.0.0.0\n", encoding="utf-8")
        results = doctor.check_deployment_exposure(tmp_path, env={})
        assert results[0].status == "warn"
        assert "DEER_FLOW_AUTH_DISABLED=0" in (results[0].fix or "")

    def test_exposure_never_fails_the_doctor_exit_code(self, tmp_path):
        import doctor

        (tmp_path / ".env").write_text("BIND_HOST=0.0.0.0\n", encoding="utf-8")
        results = doctor.check_deployment_exposure(tmp_path, env={})
        assert all(r.status != "fail" for r in results)
