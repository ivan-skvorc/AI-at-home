"""Tailnet detection that drives the publish and the origin allowlists.

``scripts/detect_tailscale.py`` is the single answer to "if this machine is on a
tailnet, what addresses do peers reach it at?". Three launch scripts call it, so
the properties that matter most here are the *degradation* ones: a host without
Tailscale, with a stopped daemon, or with a wedged CLI must all come back as
"absent" rather than raising — otherwise a detector failure takes out
``make docker-start`` for everyone.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import detect_tailscale as dt  # noqa: E402


def _status(*, ipv4: str = "100.101.102.103", dns: str = "box.tailnet-name.ts.net.", state: str = "Running", extra_ips: list[str] | None = None) -> dict:
    ips = [ipv4, *(extra_ips or ["fd7a:115c:a1e0::1234"])]
    return {
        "BackendState": state,
        "MagicDNSSuffix": "tailnet-name.ts.net",
        "Self": {"HostName": "box", "DNSName": dns, "TailscaleIPs": ips, "Online": True},
    }


class TestParseStatus:
    def test_reads_the_ipv4_and_magic_dns_name(self) -> None:
        identity = dt.parse_status(_status())
        assert identity is not None
        assert identity.ipv4 == "100.101.102.103"
        # The daemon reports a rooted FQDN; a URL must not carry the trailing dot.
        assert identity.magic_dns == "box.tailnet-name.ts.net"
        assert identity.ipv6 == "fd7a:115c:a1e0::1234"

    @pytest.mark.parametrize("state", ["Stopped", "NeedsLogin", "NoState"])
    def test_a_daemon_that_is_not_running_is_absent(self, state: str) -> None:
        # Installed-but-logged-out is indistinguishable from not installed as far
        # as publishing goes: there is no address to publish on.
        assert dt.parse_status(_status(state=state)) is None

    def test_missing_backend_state_is_tolerated(self) -> None:
        payload = _status()
        del payload["BackendState"]
        assert dt.parse_status(payload) is not None

    def test_no_ipv4_is_absent(self) -> None:
        # The compatibility URL (`http://100.x:port`) is the whole point; a
        # v6-only tailnet cannot serve it, so there is nothing to publish.
        payload = _status()
        payload["Self"]["TailscaleIPs"] = ["fd7a:115c:a1e0::1234"]
        assert dt.parse_status(payload) is None

    def test_magic_dns_may_be_absent(self) -> None:
        identity = dt.parse_status(_status(dns=""))
        assert identity is not None
        assert identity.ipv4 == "100.101.102.103"
        assert identity.magic_dns is None

    @pytest.mark.parametrize("payload", [None, [], "", 42, {}, {"Self": {}}, {"Self": {"TailscaleIPs": "100.1.2.3"}}])
    def test_malformed_payloads_are_absent_not_errors(self, payload: object) -> None:
        assert dt.parse_status(payload) is None


class TestReadStatus:
    def test_explicit_payload_short_circuits_the_cli(self) -> None:
        detection = dt.read_status(json.dumps(_status()))
        assert detection.present
        assert detection.identity is not None
        assert detection.identity.ipv4 == "100.101.102.103"

    def test_invalid_json_degrades_to_absent(self) -> None:
        detection = dt.read_status("{not json")
        assert not detection.present
        assert detection.notes

    def test_missing_binary_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dt.shutil, "which", lambda _name: None)
        detection = dt.read_status()
        assert not detection.present

    def test_a_cli_that_raises_never_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A wedged daemon must not take down `make docker-start`.
        monkeypatch.setattr(dt.shutil, "which", lambda _name: "/usr/bin/tailscale")

        def _boom(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="tailscale", timeout=5)

        detection = dt.read_status(runner=_boom)
        assert not detection.present
        assert detection.notes

    def test_nonzero_exit_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dt.shutil, "which", lambda _name: "/usr/bin/tailscale")
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="not logged in")
        assert not dt.read_status(runner=lambda *a, **k: result).present


class TestTailnetOrigins:
    def test_emits_the_compatibility_ip_origin_with_the_port(self) -> None:
        identity = dt.TailnetIdentity(ipv4="100.1.2.3", magic_dns="box.example.ts.net")
        assert "http://100.1.2.3:2026" in dt.tailnet_origins(identity, 2026)

    def test_emits_the_serve_https_origin_without_a_port(self) -> None:
        # Serve terminates TLS on 443 and forwards to loopback, so the browser's
        # Origin carries no port.
        identity = dt.TailnetIdentity(ipv4="100.1.2.3", magic_dns="box.example.ts.net")
        assert "https://box.example.ts.net" in dt.tailnet_origins(identity, 2026)

    def test_never_offers_https_on_the_bare_ip(self) -> None:
        # Serve's cert is issued for the MagicDNS name; https://100.x is a
        # certificate error every time, so allowlisting it only helps someone
        # reach a page that cannot load.
        identity = dt.TailnetIdentity(ipv4="100.1.2.3", magic_dns="box.example.ts.net")
        assert not any(o.startswith("https://100.") for o in dt.tailnet_origins(identity, 2026))

    def test_without_magic_dns_only_the_ip_origin_is_emitted(self) -> None:
        identity = dt.TailnetIdentity(ipv4="100.1.2.3", magic_dns=None)
        assert dt.tailnet_origins(identity, 2026) == ["http://100.1.2.3:2026"]


class TestMergeOrigins:
    def test_user_entries_survive_and_come_first(self) -> None:
        merged = dt.merge_origins("http://localhost:3000,https://mine.example", ["http://100.1.2.3:2026"])
        assert merged.split(",")[:2] == ["http://localhost:3000", "https://mine.example"]
        assert "http://100.1.2.3:2026" in merged

    def test_is_idempotent_across_restarts(self) -> None:
        # Launch scripts re-run on every start; the list must not grow each time.
        once = dt.merge_origins("http://localhost:3000", ["http://100.1.2.3:2026"])
        twice = dt.merge_origins(once, ["http://100.1.2.3:2026"])
        assert once == twice

    def test_duplicate_detection_ignores_case_and_trailing_slash(self) -> None:
        merged = dt.merge_origins("HTTP://100.1.2.3:2026/", ["http://100.1.2.3:2026"])
        # The user's spelling is kept verbatim rather than rewritten.
        assert merged == "HTTP://100.1.2.3:2026/"

    def test_empty_existing_list_yields_just_the_additions(self) -> None:
        assert dt.merge_origins("", ["http://100.1.2.3:2026"]) == "http://100.1.2.3:2026"
        assert dt.merge_origins(None, ["http://100.1.2.3:2026"]) == "http://100.1.2.3:2026"

    def test_blank_entries_are_dropped(self) -> None:
        assert dt.merge_origins("http://a, ,,http://b", []) == "http://a,http://b"


class TestPublishToggle:
    def test_defaults_on(self) -> None:
        # Default-on is safe because it only ever acts when detection finds a
        # live tailnet: a host without Tailscale publishes nothing either way.
        assert dt.publish_enabled({}) is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
    def test_explicit_opt_out(self, value: str) -> None:
        assert dt.publish_enabled({dt.ENV_PUBLISH_TOGGLE: value}) is False


class TestCli:
    def test_env_format_emits_the_three_keys(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        payload = tmp_path / "status.json"
        payload.write_text(json.dumps(_status()), encoding="utf-8")
        assert dt.main(["--status-json", str(payload), "--port", "2026"]) == 0
        out = capsys.readouterr().out
        assert f"{dt.ENV_IPV4}=100.101.102.103" in out
        assert f"{dt.ENV_HOSTNAME}=box.tailnet-name.ts.net" in out
        assert f"{dt.ENV_ORIGINS}=" in out

    def test_absent_tailscale_prints_nothing_and_exits_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        payload = tmp_path / "status.json"
        payload.write_text(json.dumps(_status(state="Stopped")), encoding="utf-8")
        assert dt.main(["--status-json", str(payload)]) == 0
        assert capsys.readouterr().out.strip() == ""

    def test_unreadable_status_file_exits_zero(self, tmp_path: Path) -> None:
        assert dt.main(["--status-json", str(tmp_path / "nope.json")]) == 0

    def test_opt_out_suppresses_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setenv(dt.ENV_PUBLISH_TOGGLE, "0")
        payload = tmp_path / "status.json"
        payload.write_text(json.dumps(_status()), encoding="utf-8")
        assert dt.main(["--status-json", str(payload)]) == 0
        assert capsys.readouterr().out.strip() == ""

    def test_json_format(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        payload = tmp_path / "status.json"
        payload.write_text(json.dumps(_status()), encoding="utf-8")
        assert dt.main(["--status-json", str(payload), "--format", "json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["present"] is True
        assert data["ipv4"] == "100.101.102.103"
        assert "https://box.tailnet-name.ts.net" in data["origins"]
