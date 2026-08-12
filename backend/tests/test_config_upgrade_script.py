"""Tests for scripts/config_upgrade.py (invoked by scripts/config-upgrade.sh).

Pins the config-regeneration integrity guarantees:
- duplicate-keyed configs are refused (named key + both line numbers), never
  silently collapsed by the merge round-trip;
- the upgrade is idempotent — an up-to-date config is left byte-identical with
  no backup churn;
- a version-stamp-only upgrade preserves user comments;
- the merge only ever adds missing keys (it cannot append a duplicate section).
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "config_upgrade.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("config_upgrade", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config_upgrade = _load_script()


def _write_example(tmp_path: Path, version: int = 3) -> Path:
    example = tmp_path / "config.example.yaml"
    example.write_text(
        textwrap.dedent(
            f"""\
            config_version: {version}
            sandbox:
              use: deerflow.sandbox.local:LocalSandboxProvider
            models: []
            new_section:
              enabled: true
            """
        ),
        encoding="utf-8",
    )
    return example


class TestUpToDateConfig:
    def test_no_write_and_no_backup(self, tmp_path, capsys):
        example = _write_example(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        # "Up to date" means complete, not merely stamped: this config carries
        # every section the example ships. A config at the same version that is
        # *missing* a section is a different case, covered by
        # TestUpstreamSectionDelivery.
        original = "config_version: 3\n# my comment\nsandbox:\n  use: custom\nmodels: []\nnew_section:\n  enabled: false\n"
        config.write_text(original, encoding="utf-8")

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 0
        assert config.read_text(encoding="utf-8") == original
        assert not (tmp_path / "config.yaml.bak").exists()
        assert "already up to date" in capsys.readouterr().out


class TestDuplicateKeys:
    def test_duplicate_top_level_key_aborts_without_writing(self, tmp_path, capsys):
        example = _write_example(tmp_path)
        config = tmp_path / "config.yaml"
        original = textwrap.dedent(
            """\
            config_version: 1
            sandbox:
              use: deerflow.community.aio_sandbox:AioSandboxProvider
            sandbox:
              use: deerflow.sandbox.local:LocalSandboxProvider
            """
        )
        config.write_text(original, encoding="utf-8")

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 1
        out = capsys.readouterr().out
        assert "duplicate top-level key 'sandbox'" in out
        assert "first defined at line 2" in out
        assert "duplicated at line 4" in out
        # File untouched, no backup created
        assert config.read_text(encoding="utf-8") == original
        assert not (tmp_path / "config.yaml.bak").exists()


class TestVersionBumpOnly:
    def test_comments_survive_a_version_stamp_upgrade(self, tmp_path):
        example = _write_example(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                config_version: 2
                # user comment that must survive
                sandbox:
                  use: custom  # inline note
                models: []
                new_section:
                  enabled: false
                """
            ),
            encoding="utf-8",
        )

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 0
        text = config.read_text(encoding="utf-8")
        assert "config_version: 3" in text
        assert "# user comment that must survive" in text
        assert "# inline note" in text
        # user values untouched
        assert "enabled: false" in text
        assert (tmp_path / "config.yaml.bak").exists()


class TestMergeMissingKeys:
    def test_missing_section_is_added_once(self, tmp_path, capsys):
        example = _write_example(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        config.write_text(
            "config_version: 1\nsandbox:\n  use: custom\nmodels: []\n",
            encoding="utf-8",
        )

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 0
        text = config.read_text(encoding="utf-8")
        assert text.count("new_section:") == 1
        assert text.count("sandbox:") == 1  # never appends an existing section
        assert "use: custom" in text  # user value wins over example default
        assert "+ new_section" in capsys.readouterr().out

    def test_second_run_is_a_byte_identical_no_op(self, tmp_path):
        example = _write_example(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        config.write_text(
            "config_version: 1\nsandbox:\n  use: custom\nmodels: []\n",
            encoding="utf-8",
        )

        assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
        after_first = config.read_text(encoding="utf-8")
        backup_after_first = (tmp_path / "config.yaml.bak").read_text(encoding="utf-8")

        assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
        assert config.read_text(encoding="utf-8") == after_first
        # backup untouched by the no-op second run
        assert (tmp_path / "config.yaml.bak").read_text(encoding="utf-8") == backup_after_first


class TestMigrations:
    def test_src_module_paths_are_rewritten(self, tmp_path):
        example = _write_example(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        config.write_text(
            "config_version: 0\nsandbox:\n  use: src.sandbox.local:LocalSandboxProvider\nmodels: []\nnew_section:\n  enabled: true\n",
            encoding="utf-8",
        )

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 0
        text = config.read_text(encoding="utf-8")
        assert "deerflow.sandbox.local:LocalSandboxProvider" in text
        assert "src.sandbox" not in text


def _write_example_with_tools(tmp_path: Path, version: int = 3) -> Path:
    example = tmp_path / "config.example.yaml"
    example.write_text(
        textwrap.dedent(
            f"""\
            config_version: {version}
            sandbox:
              use: deerflow.sandbox.local:LocalSandboxProvider
            models: []
            tools:
              - name: web_search
                group: web
                use: deerflow.community.searxng.tools:web_search_tool
              - name: web_fetch
                group: web
                use: deerflow.community.web_fetch.tools:web_fetch_tool
                backend: camoufox
              - name: bash
                group: bash
                use: deerflow.sandbox.tools:bash_tool
            """
        ),
        encoding="utf-8",
    )
    return example


class TestDefaultToolsBackfill:
    """An existing `tools:` list regains missing default entries on upgrade.

    merge_missing is dict-based and cannot heal a reduced list, so configs from
    older bootstraps (e.g. a wizard run that declined bash) stayed tool-less
    forever — the "agent says it has no tools" failure mode.
    """

    def test_missing_default_tools_are_appended(self, tmp_path, capsys):
        import yaml

        example = _write_example_with_tools(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                config_version: 1
                sandbox:
                  use: custom
                models: []
                tools:
                  - name: web_search
                    group: web
                    use: deerflow.community.ddg_search.tools:web_search_tool
                """
            ),
            encoding="utf-8",
        )

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 0
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        tools_by_name = {tool["name"]: tool for tool in data["tools"]}
        # Existing entry untouched (user's provider choice wins), no duplicate.
        assert sum(1 for tool in data["tools"] if tool["name"] == "web_search") == 1
        assert tools_by_name["web_search"]["use"] == "deerflow.community.ddg_search.tools:web_search_tool"
        # Missing defaults appended from the example.
        assert tools_by_name["web_fetch"]["backend"] == "camoufox"
        assert tools_by_name["bash"]["use"] == "deerflow.sandbox.tools:bash_tool"
        out = capsys.readouterr().out
        assert "+ tools[web_fetch]" in out
        assert "+ tools[bash]" in out
        assert "+ tools[web_search]" not in out

    def test_backfill_second_run_is_a_no_op(self, tmp_path):
        example = _write_example_with_tools(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        config.write_text(
            "config_version: 1\nsandbox:\n  use: custom\nmodels: []\ntools:\n  - name: web_search\n    group: web\n    use: deerflow.community.ddg_search.tools:web_search_tool\n",
            encoding="utf-8",
        )

        assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
        after_first = config.read_text(encoding="utf-8")
        assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
        assert config.read_text(encoding="utf-8") == after_first

    def test_absent_tools_section_is_added_wholesale(self, tmp_path):
        import yaml

        example = _write_example_with_tools(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        config.write_text("config_version: 1\nsandbox:\n  use: custom\nmodels: []\n", encoding="utf-8")

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 0
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        assert [tool["name"] for tool in data["tools"]] == ["web_search", "web_fetch", "bash"]

    def test_backfill_helper_ignores_non_dict_entries(self):
        user = {"tools": ["not-a-dict", {"name": "bash"}]}
        example = {"tools": [{"name": "bash"}, {"name": "web_fetch", "backend": "camoufox"}, "also-not-a-dict"]}
        added = config_upgrade.backfill_missing_default_tools(user, example)
        assert added == ["tools[web_fetch]"]
        assert user["tools"][-1] == {"name": "web_fetch", "backend": "camoufox"}


class TestUpstreamSectionDelivery:
    """The delivery trap that an upstream sync re-arms every time.

    `config_version` is the *only* thing that makes the upgrade do any work, and
    upstream's copy of it sits permanently behind the fork's — the fork bumps for
    its own sections, upstream never sees them. So when an upstream merge adds a
    top-level section, the two versions can be equal, `upgrade()` short-circuits
    on "already up to date", and every existing install keeps a config that is
    silently missing the new section forever.

    Caught live on the 2026-08-12 sync: upstream added `mcp_tasks:` while leaving
    its own `config_version` at 33; the fork was at 36, so the upgrade delivered
    nothing until the fork bumped to 37. These tests make that mechanical instead
    of a human remembering to diff the two examples.
    """

    def test_an_equal_version_config_missing_a_section_says_so_loudly(self, tmp_path, capsys):
        """The exact shape of the live failure: same version, missing section.

        A version comparison cannot see this, and it is the case that actually
        reaches users -- their config is already stamped current, so nothing marks
        it as outdated. It must not pass in silence.

        It deliberately does *not* auto-deliver: this script runs on every launch
        and the merge path would rewrite the file through `yaml.dump`, stripping
        every comment. Naming the gap and leaving the file alone is the trade.
        """
        example = _write_example(tmp_path, version=3)
        example.write_text(example.read_text(encoding="utf-8") + "mcp_tasks:\n  enabled: false\n", encoding="utf-8")
        config = tmp_path / "config.yaml"
        original = "config_version: 3\n# a comment\nsandbox:\n  use: custom\nmodels: []\nnew_section:\n  enabled: false\n"
        config.write_text(original, encoding="utf-8")

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        out = capsys.readouterr().out
        assert rc == 0
        assert "mcp_tasks" in out, "a missing section must be named, not passed over in silence"
        assert "bump `config_version`" in out
        assert config.read_text(encoding="utf-8") == original  # untouched
        assert not (tmp_path / "config.yaml.bak").exists()

    def test_an_equal_version_config_with_nothing_missing_is_still_a_byte_identical_no_op(self, tmp_path):
        """The invariant the shape check must not cost: no spurious rewrites.

        Every launch path runs this script, so an up-to-date config must come out
        untouched -- no rewrite, no `.bak` churn, and above all no comment loss.
        """
        example = _write_example(tmp_path, version=3)
        config = tmp_path / "config.yaml"
        original = "config_version: 3\n# a comment that must survive\nsandbox:\n  use: custom\nmodels: []\nnew_section:\n  enabled: false\n"
        config.write_text(original, encoding="utf-8")

        rc = config_upgrade.upgrade(config, example, REPO_ROOT)

        assert rc == 0
        assert config.read_text(encoding="utf-8") == original
        assert not (tmp_path / "config.yaml.bak").exists()

    def test_a_version_bump_delivers_every_section_the_real_example_ships(self):
        """Runs against the actual `config.example.yaml`: when a bump does happen, everything lands.

        Guards the delivery mechanism itself -- that no top-level key in the real
        example is shaped in a way `merge_missing` skips, so bumping the version
        is always sufficient to reach an existing install.

        What this deliberately does *not* guard: whether someone *remembered* to
        bump after upstream added a section. That needs the previous example to
        compare against, so it is a git-diff step in FORK.md's post-sync
        checklist, not a unit test.
        """
        import tempfile

        import yaml

        real_example = REPO_ROOT / "config.example.yaml"
        example_data = yaml.safe_load(real_example.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(f"config_version: {example_data['config_version'] - 1}\nmodels: []\n", encoding="utf-8")

            rc = config_upgrade.upgrade(config, real_example, REPO_ROOT)

            assert rc == 0
            delivered = yaml.safe_load(config.read_text(encoding="utf-8"))

        missing = sorted(set(example_data) - set(delivered))
        assert not missing, f"config.example.yaml ships top-level keys a version bump never delivers: {missing}"
