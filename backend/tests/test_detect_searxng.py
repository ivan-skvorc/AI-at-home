"""Unit tests for scripts/detect_searxng.py.

Run from repo root:
    cd backend && uv run pytest tests/test_detect_searxng.py -v
"""

from __future__ import annotations

import detect_searxng
from detect_searxng import (
    ENV_VAR,
    IN_NETWORK_URL,
    config_uses_searxng,
    parse_env_file,
    resolve,
    translate_for_docker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEARXNG_CONFIG = """
tools:
  - name: web_search
    group: web
    use: deerflow.community.searxng.tools:web_search_tool
    base_url: http://localhost:8088
"""

DDG_CONFIG = """
tools:
  # SearXNG entry left commented out:
  # - name: web_search
  #   use: deerflow.community.searxng.tools:web_search_tool
  - name: web_search
    group: web
    use: deerflow.community.ddg_search.tools:web_search_tool
"""


def make_probe(live_urls: set[str]):
    """Probe fake: a URL answers iff it is in live_urls (ignoring trailing /)."""

    def probe(url: str) -> bool:
        return url.rstrip("/") in live_urls

    return probe


def make_docker(
    *,
    bundled_ports: set[int] = frozenset(),
    bridge_ip: str | None = "172.17.0.1",
    desktop: bool = False,
):
    """Fake for the docker CLI runner used by resolve()."""

    def docker(args: list[str]) -> str | None:
        if args[0] == "ps":
            port_filters = [a for a in args if a.startswith("publish=")]
            port = int(port_filters[0].removeprefix("publish=")) if port_filters else None
            if port in bundled_ports:
                return "deer-flow-searxng\n"
            return ""
        if args[0] == "network":
            return f"{bridge_ip}\n" if bridge_ip else None
        if args[0] == "info":
            return "Docker Desktop\n" if desktop else "Ubuntu 24.04 LTS\n"
        return None

    return docker


# ---------------------------------------------------------------------------
# config_uses_searxng
# ---------------------------------------------------------------------------


class TestConfigUsesSearxng:
    def test_active_provider_line(self):
        assert config_uses_searxng(SEARXNG_CONFIG) is True

    def test_commented_out_provider_is_inactive(self):
        assert config_uses_searxng(DDG_CONFIG) is False

    def test_absent_provider(self):
        assert config_uses_searxng("tools: []\n") is False


# ---------------------------------------------------------------------------
# parse_env_file
# ---------------------------------------------------------------------------


class TestParseEnvFile:
    def test_basic_quotes_export_and_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nPLAIN=value\nQUOTED=\"http://localhost:9999\"\nexport EXPORTED='single'\nnot a kv line\n")
        parsed = parse_env_file(env_file)
        assert parsed == {
            "PLAIN": "value",
            "QUOTED": "http://localhost:9999",
            "EXPORTED": "single",
        }

    def test_missing_file(self, tmp_path):
        assert parse_env_file(tmp_path / "nope.env") == {}


# ---------------------------------------------------------------------------
# translate_for_docker
# ---------------------------------------------------------------------------


class TestTranslateForDocker:
    def test_loopback_hosts_are_rewritten(self):
        assert translate_for_docker("http://localhost:8080") == "http://host.docker.internal:8080"
        assert translate_for_docker("http://127.0.0.1:8088") == "http://host.docker.internal:8088"

    def test_other_hosts_untouched(self):
        assert translate_for_docker("http://searxng.lan:8080") == "http://searxng.lan:8080"
        assert translate_for_docker("https://search.example.com") == "https://search.example.com"


# ---------------------------------------------------------------------------
# resolve — provider gating
# ---------------------------------------------------------------------------


class TestResolveSkip:
    def test_skips_when_config_does_not_use_searxng(self):
        mode, url = resolve(
            context="docker",
            env={},
            config_text=DDG_CONFIG,
            probe=make_probe(set()),
            docker=make_docker(),
        )
        assert (mode, url) == ("skip", None)

    def test_unreadable_config_does_not_skip(self):
        mode, _ = resolve(
            context="docker",
            env={},
            config_text=None,
            probe=make_probe(set()),
            docker=make_docker(),
        )
        assert mode == "bundled"


# ---------------------------------------------------------------------------
# resolve — explicit DEER_FLOW_SEARXNG_BASE_URL
# ---------------------------------------------------------------------------


class TestResolveExplicitEnv:
    def test_in_network_default_is_treated_as_unset(self):
        mode, _ = resolve(
            context="docker",
            env={ENV_VAR: IN_NETWORK_URL},
            config_text=SEARXNG_CONFIG,
            probe=make_probe(set()),
            docker=make_docker(),
        )
        assert mode == "bundled"

    def test_live_loopback_url_is_translated_for_docker(self):
        probe = make_probe({"http://localhost:9090", "http://172.17.0.1:9090"})
        mode, url = resolve(
            context="docker",
            env={ENV_VAR: "http://localhost:9090"},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(),
        )
        assert (mode, url) == ("external", "http://host.docker.internal:9090")

    def test_live_loopback_url_kept_verbatim_for_host(self):
        probe = make_probe({"http://localhost:9090"})
        mode, url = resolve(
            context="host",
            env={ENV_VAR: "http://localhost:9090"},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(),
        )
        assert (mode, url) == ("external", "http://localhost:9090")

    def test_dead_loopback_url_falls_back_to_bundled(self):
        mode, url = resolve(
            context="docker",
            env={ENV_VAR: "http://localhost:9090"},
            config_text=SEARXNG_CONFIG,
            probe=make_probe(set()),
            docker=make_docker(),
        )
        assert (mode, url) == ("bundled", None)

    def test_loopback_url_unreachable_from_containers_falls_back(self):
        # Answers on the host but not on the bridge IP, non-Desktop daemon.
        probe = make_probe({"http://localhost:9090"})
        mode, url = resolve(
            context="docker",
            env={ENV_VAR: "http://localhost:9090"},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(desktop=False),
        )
        assert (mode, url) == ("bundled", None)

    def test_non_loopback_url_is_respected_even_when_unverifiable(self):
        # e.g. a compose-network hostname that only resolves inside docker.
        mode, url = resolve(
            context="docker",
            env={ENV_VAR: "http://my-searxng:8080"},
            config_text=SEARXNG_CONFIG,
            probe=make_probe(set()),
            docker=make_docker(),
        )
        assert (mode, url) == ("external", "http://my-searxng:8080")


# ---------------------------------------------------------------------------
# resolve — auto-detection of local instances
# ---------------------------------------------------------------------------


class TestResolveAutoDetect:
    def test_nothing_running_starts_bundled(self):
        mode, url = resolve(
            context="docker",
            env={},
            config_text=SEARXNG_CONFIG,
            probe=make_probe(set()),
            docker=make_docker(),
        )
        assert (mode, url) == ("bundled", None)

    def test_own_bundled_container_resolves_to_bundled(self):
        probe = make_probe({"http://127.0.0.1:8088"})
        mode, url = resolve(
            context="docker",
            env={},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(bundled_ports={8088}),
        )
        assert (mode, url) == ("bundled", None)

    def test_foreign_instance_reachable_from_bridge_is_external(self):
        probe = make_probe({"http://127.0.0.1:8080", "http://172.17.0.1:8080"})
        mode, url = resolve(
            context="docker",
            env={},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(),
        )
        assert (mode, url) == ("external", "http://host.docker.internal:8080")

    def test_loopback_only_instance_on_linux_falls_back_to_bundled(self):
        probe = make_probe({"http://127.0.0.1:8080"})
        mode, url = resolve(
            context="docker",
            env={},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(desktop=False),
        )
        assert (mode, url) == ("bundled", None)

    def test_loopback_only_instance_on_docker_desktop_is_external(self):
        # Docker Desktop's host.docker.internal proxies host loopback ports.
        probe = make_probe({"http://127.0.0.1:8080"})
        mode, url = resolve(
            context="docker",
            env={},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(bridge_ip=None, desktop=True),
        )
        assert (mode, url) == ("external", "http://host.docker.internal:8080")

    def test_repo_port_wins_over_searxng_default_port(self):
        probe = make_probe(
            {
                "http://127.0.0.1:8088",
                "http://172.17.0.1:8088",
                "http://127.0.0.1:8080",
                "http://172.17.0.1:8080",
            }
        )
        mode, url = resolve(
            context="docker",
            env={},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(),
        )
        assert (mode, url) == ("external", "http://host.docker.internal:8088")

    def test_host_context_uses_local_url_directly(self):
        probe = make_probe({"http://127.0.0.1:8080"})
        mode, url = resolve(
            context="host",
            env={},
            config_text=SEARXNG_CONFIG,
            probe=probe,
            docker=make_docker(),
        )
        assert (mode, url) == ("external", "http://127.0.0.1:8080")


# ---------------------------------------------------------------------------
# main — output protocol
# ---------------------------------------------------------------------------


class TestMainOutput:
    def test_prints_single_resolution_line(self, tmp_path, capsys, monkeypatch):
        config = tmp_path / "config.yaml"
        config.write_text(DDG_CONFIG)
        monkeypatch.delenv(ENV_VAR, raising=False)
        rc = detect_searxng.main(["--context", "docker", "--config", str(config)])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "skip"

    def test_env_file_feeds_explicit_override(self, tmp_path, capsys, monkeypatch):
        config = tmp_path / "config.yaml"
        config.write_text(SEARXNG_CONFIG)
        env_file = tmp_path / ".env"
        env_file.write_text(f"{ENV_VAR}=http://my-searxng:8080\n")
        monkeypatch.delenv(ENV_VAR, raising=False)
        # Keep the test hermetic: no real network probing or docker calls.
        monkeypatch.setattr(detect_searxng, "probe_searxng", make_probe(set()))
        monkeypatch.setattr(detect_searxng, "run_docker", make_docker())
        # Non-loopback URLs are respected even when unverifiable, so the
        # dead probe cannot change the resolution here.
        rc = detect_searxng.main(["--context", "docker", "--config", str(config), "--env-file", str(env_file)])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "external http://my-searxng:8080"


class TestDispatcherConfigIsRecognized:
    """`web_search` reaches SearXNG through the dispatcher, not only directly.

    The dispatcher entry names `deerflow.community.web_search` and selects the
    engine with a `backend:` / `fallback:` key. Matching only the provider
    module would read the shipped config as "no SearXNG", and every launch path
    would quietly stop starting the container that web_search depends on — with
    no error anywhere, because "skip" is a legitimate outcome.
    """

    LEGACY = "tools:\n  - name: web_search\n    use: deerflow.community.searxng.tools:web_search_tool\n"
    DISPATCHER = "tools:\n  - name: web_search\n    use: deerflow.community.web_search.tools:web_search_tool\n"

    def test_the_legacy_direct_entry_still_counts(self):
        assert detect_searxng.config_uses_searxng(self.LEGACY) is True

    def test_the_shipped_example_config_counts(self):
        import pathlib

        example = pathlib.Path(__file__).resolve().parents[2] / "config.example.yaml"
        assert detect_searxng.config_uses_searxng(example.read_text(encoding="utf-8")) is True

    def test_an_omitted_backend_counts_because_searxng_is_the_default(self):
        """The dispatcher defaults to searxng, so an entry without `backend:` uses it."""
        assert detect_searxng.config_uses_searxng(self.DISPATCHER) is True

    def test_an_explicit_searxng_backend_counts(self):
        assert detect_searxng.config_uses_searxng(self.DISPATCHER + "    backend: searxng\n") is True

    def test_searxng_as_the_fallback_counts(self):
        """A stack primarily on Tavily still needs the container for its backup."""
        config = self.DISPATCHER + "    backend: tavily\n    fallback: searxng\n"
        assert detect_searxng.config_uses_searxng(config) is True

    def test_a_stack_that_never_reaches_searxng_does_not_count(self):
        config = self.DISPATCHER + "    backend: tavily\n"
        assert detect_searxng.config_uses_searxng(config) is False

    def test_a_commented_out_dispatcher_entry_does_not_count(self):
        config = "tools:\n  # - name: web_search\n  #   use: deerflow.community.web_search.tools:web_search_tool\n"
        assert detect_searxng.config_uses_searxng(config) is False

    def test_a_neighbouring_tools_backend_key_does_not_leak_in(self):
        """`backend:` is not unique to web_search — web_fetch carries one too.

        A file-wide scan for `backend: searxng` would read web_fetch's key as
        web_search's and start a container nothing is going to use.
        """
        config = self.DISPATCHER + "    backend: tavily\n  - name: web_fetch\n    backend: searxng\n"
        assert detect_searxng.config_uses_searxng(config) is False
