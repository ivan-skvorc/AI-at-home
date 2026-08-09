#!/usr/bin/env python3
"""DeerFlow Health Check (make doctor).

Checks system requirements, configuration, LLM provider, and optional
components, then prints an actionable report.

Exit codes:
  0 — all required checks passed (warnings allowed)
  1 — one or more required checks failed
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

Status = Literal["ok", "warn", "fail", "skip"]
PNPM_SCRIPT_PATH = Path(__file__).with_name("pnpm.py")
FRONTEND_DIR = PNPM_SCRIPT_PATH.parent.parent / "frontend"


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if _supports_color():
        return f"\033[{code}m{text}\033[0m"
    return text


def green(t: str) -> str:
    return _c(t, "32")


def red(t: str) -> str:
    return _c(t, "31")


def yellow(t: str) -> str:
    return _c(t, "33")


def cyan(t: str) -> str:
    return _c(t, "36")


def bold(t: str) -> str:
    return _c(t, "1")


def _icon(status: Status) -> str:
    icons = {"ok": green("✓"), "warn": yellow("!"), "fail": red("✗"), "skip": "—"}
    return icons[status]


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return None


def _parse_major(version_text: str) -> int | None:
    v = version_text.lstrip("v").split(".", 1)[0]
    return int(v) if v.isdigit() else None


def _load_yaml_file(path: Path) -> dict:
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("top-level config must be a YAML mapping")
    return data


def _load_app_config(config_path: Path) -> object:
    from deerflow.config.app_config import AppConfig

    return AppConfig.from_file(str(config_path))


def _split_use_path(use: str) -> tuple[str, str] | None:
    if ":" not in use:
        return None
    module_name, attr_name = use.split(":", 1)
    if not module_name or not attr_name:
        return None
    return module_name, attr_name


# ---------------------------------------------------------------------------
# Check result container
# ---------------------------------------------------------------------------


class CheckResult:
    def __init__(
        self,
        label: str,
        status: Status,
        detail: str = "",
        fix: str | None = None,
    ) -> None:
        self.label = label
        self.status = status
        self.detail = detail
        self.fix = fix

    def print(self) -> None:
        icon = _icon(self.status)
        detail_str = f"  ({self.detail})" if self.detail else ""
        print(f"  {icon} {self.label}{detail_str}")
        if self.fix:
            for line in self.fix.splitlines():
                print(f"      {cyan('→')} {line}")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_python() -> CheckResult:
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 12):
        return CheckResult("Python", "ok", version_str)
    return CheckResult(
        "Python",
        "fail",
        version_str,
        fix="Python 3.12+ required. Install from https://www.python.org/",
    )


def check_node() -> CheckResult:
    node = shutil.which("node")
    if not node:
        return CheckResult(
            "Node.js",
            "fail",
            fix="Install Node.js 22+: https://nodejs.org/",
        )
    out = _run(["node", "-v"]) or ""
    major = _parse_major(out)
    if major is None or major < 22:
        return CheckResult(
            "Node.js",
            "fail",
            out or "unknown version",
            fix="Node.js 22+ required. Install from https://nodejs.org/",
        )
    return CheckResult("Node.js", "ok", out.lstrip("v"))


def check_pnpm() -> CheckResult:
    try:
        result = subprocess.run(
            [sys.executable, str(PNPM_SCRIPT_PATH), "-v"],
            cwd=FRONTEND_DIR,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except OSError as exc:
        return CheckResult(
            "pnpm",
            "fail",
            f"Unable to run pnpm resolver: {exc}",
            fix="Install pnpm, or install Corepack and ensure it is on PATH",
        )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = "\n".join(part for part in (stderr, stdout) if part)
        return CheckResult(
            "pnpm",
            "fail",
            detail or f"pnpm resolver exited with status {result.returncode}",
            fix="Install pnpm, or install Corepack and ensure it is on PATH",
        )
    if not stdout:
        return CheckResult(
            "pnpm",
            "fail",
            stderr or "pnpm resolver returned no version",
            fix="Install pnpm, or install Corepack and ensure it is on PATH",
        )
    return CheckResult("pnpm", "ok", stdout)


def check_uv() -> CheckResult:
    if not shutil.which("uv"):
        return CheckResult(
            "uv",
            "fail",
            fix="curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
    out = _run(["uv", "--version"]) or ""
    parts = out.split()
    version = parts[1] if len(parts) > 1 else out
    return CheckResult("uv", "ok", version)


def check_nginx() -> CheckResult:
    if shutil.which("nginx"):
        out = _run(["nginx", "-v"]) or ""
        version = out.split("/", 1)[-1] if "/" in out else out
        return CheckResult("nginx", "ok", version)
    return CheckResult(
        "nginx",
        "fail",
        fix=("macOS:   brew install nginx\nUbuntu:  sudo apt install nginx\nWindows: use WSL or Docker mode"),
    )


def check_config_exists(config_path: Path) -> CheckResult:
    if config_path.exists():
        return CheckResult("config.yaml found", "ok")
    return CheckResult(
        "config.yaml found",
        "fail",
        fix="Run 'make setup' to create it",
    )


def check_config_duplicate_keys(config_path: Path) -> CheckResult:
    """Fail loudly on duplicate YAML keys (PyYAML would silently keep the last).

    Motivating incident: a config.yaml with two top-level `sandbox:` blocks
    silently reverted the user to LocalSandboxProvider; the only runtime
    symptom was "bash is disabled" while their sandbox container ran fine.
    """
    if not config_path.exists():
        return CheckResult("config.yaml has no duplicate keys", "skip")
    try:
        from deerflow.config.yaml_guard import DuplicateKeyError, safe_load_guarded
    except ImportError as exc:
        return CheckResult("config.yaml has no duplicate keys", "skip", str(exc))

    try:
        with open(config_path, encoding="utf-8") as f:
            safe_load_guarded(f)
    except DuplicateKeyError as exc:
        return CheckResult(
            "config.yaml has no duplicate keys",
            "fail",
            str(exc),
            fix="Remove one of the duplicate sections from config.yaml",
        )
    except Exception:
        return CheckResult("config.yaml has no duplicate keys", "skip", "config.yaml is not parseable (see 'config.yaml loadable')")
    return CheckResult("config.yaml has no duplicate keys", "ok")


def check_config_unknown_keys(config_path: Path) -> list[CheckResult]:
    """Warn on unknown sandbox: keys and suspected typos in models: entries."""
    if not config_path.exists():
        return []
    try:
        from deerflow.config.config_lint import lint_unknown_config_keys

        data = _load_yaml_file(config_path)
    except Exception:
        return []

    return [
        CheckResult(
            "config.yaml key lint",
            "warn",
            message,
            fix="Compare with config.example.yaml",
        )
        for message in lint_unknown_config_keys(data)
    ]


def check_config_version(config_path: Path, project_root: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult("config.yaml version", "skip")

    try:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            user_data = yaml.safe_load(f) or {}
        user_ver = int(user_data.get("config_version", 0))
    except Exception as exc:
        return CheckResult("config.yaml version", "fail", str(exc))

    example_path = project_root / "config.example.yaml"
    if not example_path.exists():
        return CheckResult("config.yaml version", "skip", "config.example.yaml not found")

    try:
        import yaml

        with open(example_path, encoding="utf-8") as f:
            example_data = yaml.safe_load(f) or {}
        example_ver = int(example_data.get("config_version", 0))
    except Exception:
        return CheckResult("config.yaml version", "skip")

    if user_ver < example_ver:
        return CheckResult(
            "config.yaml version",
            "warn",
            f"v{user_ver} < v{example_ver} (latest)",
            fix="make config-upgrade",
        )
    return CheckResult("config.yaml version", "ok", f"v{user_ver}")


def check_models_configured(config_path: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult("models configured", "skip")
    try:
        data = _load_yaml_file(config_path)
        models = data.get("models", [])
        if models:
            return CheckResult("models configured", "ok", f"{len(models)} model(s)")
        return CheckResult(
            "models configured",
            "fail",
            "no models found",
            fix="Run 'make setup' to configure an LLM provider",
        )
    except Exception as exc:
        return CheckResult("models configured", "fail", str(exc))


# The `($<in>/<out>)` pair every bundled model carries in its display_name;
# `app/gateway/pricing.py` derives a price from it when no `pricing:` block
# is configured, so a name carrying one is priceable.
_PRICE_IN_DISPLAY_NAME_RE = re.compile(r"\(\$\d+(?:\.\d+)?/\d+(?:\.\d+)?")


def check_model_pricing(config_path: Path) -> CheckResult:
    """Can the chat header actually show a cost for the configured models?

    The cost estimate has no error path: an unpriceable model contributes
    nothing and the header renders a bare `—`. That has been mistaken for a
    broken feature three times, so surface it as a real check. A model is
    priceable from an explicit `pricing:` block *or* from the `($in/out)` pair
    in its `display_name`; local Ollama models are unpriced by design and are
    reported separately rather than as a problem.
    """
    if not config_path.exists():
        return CheckResult("model pricing", "skip")
    try:
        data = _load_yaml_file(config_path)
        models = data.get("models") or []
        if not models:
            return CheckResult("model pricing", "skip")

        priceable, unpriced = [], []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name") or "?"
            display_name = str(model.get("display_name") or "")
            if isinstance(model.get("pricing"), dict) or _PRICE_IN_DISPLAY_NAME_RE.search(display_name):
                priceable.append(name)
            else:
                unpriced.append(name)

        if not priceable:
            return CheckResult(
                "model pricing",
                "warn",
                f"no price for any of {len(models)} model(s) — the chat header will show '—'",
                fix="Give each paid model a `pricing:` block, or a ($in/out) price in its display_name",
            )
        if unpriced:
            # Local models are genuinely free; naming them keeps the note
            # actionable without implying every entry must be priced.
            shown = ", ".join(unpriced[:4]) + (", ..." if len(unpriced) > 4 else "")
            return CheckResult(
                "model pricing",
                "ok",
                f"{len(priceable)} priced; unpriced (free/local?): {shown}",
            )
        return CheckResult("model pricing", "ok", f"all {len(priceable)} model(s) priced")
    except Exception as exc:
        return CheckResult("model pricing", "warn", str(exc))


def check_config_loadable(config_path: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult("config.yaml loadable", "skip")

    try:
        _load_app_config(config_path)
        return CheckResult("config.yaml loadable", "ok")
    except Exception as exc:
        return CheckResult(
            "config.yaml loadable",
            "fail",
            str(exc),
            fix="Run 'make setup' again, or compare with config.example.yaml",
        )


def _section_disabled(section: dict) -> bool:
    """Mirror ``AppConfig._is_section_disabled`` without importing the harness.

    Only an explicit ``enabled: false`` (bool or the common string spellings)
    makes a section's missing ``$VAR`` references non-fatal at config load.
    """
    if "enabled" not in section:
        return False
    value = section.get("enabled")
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no", "off"}
    return False


def _collect_env_placeholders(obj: object, *, disabled: bool = False) -> list[tuple[str, bool]]:
    """Return ``(var_name, in_disabled_section)`` for every ``$VAR`` in the config.

    Leniency propagates to the whole subtree of an ``enabled: false`` section,
    matching ``AppConfig.resolve_env_variables``.
    """
    refs: list[tuple[str, bool]] = []
    if isinstance(obj, str):
        if obj.startswith("$"):
            refs.append((obj[1:], disabled))
    elif isinstance(obj, dict):
        child_disabled = disabled or _section_disabled(obj)
        for value in obj.values():
            refs.extend(_collect_env_placeholders(value, disabled=child_disabled))
    elif isinstance(obj, list):
        for item in obj:
            refs.extend(_collect_env_placeholders(item, disabled=disabled))
    return refs


def check_env_placeholders(config_path: Path) -> list[CheckResult]:
    """Surface ``$VAR`` references in config.yaml that are missing from the environment.

    A missing ``$VAR`` inside an **active** section crashes the Gateway on config
    load (``AppConfig.resolve_env_variables`` raises), which an operator sees only
    as a bare nginx 502. Listing these here — before ``make up`` — turns that into
    a clear, actionable message. Missing vars inside a **disabled**
    (``enabled: false``) section no longer crash the Gateway; they are reported as
    an informational note so the operator understands why an unused placeholder is
    tolerated.
    """
    if not config_path.exists():
        return []

    try:
        import yaml
        from dotenv import load_dotenv

        env_path = config_path.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        return [CheckResult("env placeholders", "fail", str(exc))]

    active_missing: list[str] = []
    disabled_missing: list[str] = []
    for var, in_disabled in _collect_env_placeholders(data):
        if os.environ.get(var):
            continue
        (disabled_missing if in_disabled else active_missing).append(var)

    results: list[CheckResult] = []
    if active_missing:
        names = ", ".join(sorted(set(active_missing)))
        results.append(
            CheckResult(
                "referenced env vars present",
                "fail",
                f"missing from environment/.env: {names}",
                fix=(
                    "The Gateway crashes on load (bare nginx 502) if an active section references an unset\n"
                    f"$VAR. Add the value(s) to .env, or set that section's `enabled: false`:\n  {names}"
                ),
            )
        )
    else:
        results.append(CheckResult("referenced env vars present", "ok"))

    if disabled_missing:
        names = ", ".join(sorted(set(disabled_missing)))
        results.append(
            CheckResult(
                "disabled-section placeholders",
                "ok",
                f"unset but tolerated (enabled: false): {names}",
            )
        )
    return results


def check_llm_api_key(config_path: Path) -> list[CheckResult]:
    """Check that each model's env var is set in the environment."""
    if not config_path.exists():
        return []

    results: list[CheckResult] = []
    try:
        import yaml
        from dotenv import load_dotenv

        env_path = config_path.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        for model in data.get("models", []):
            # Collect all values that look like $ENV_VAR references
            def _collect_env_refs(obj: object) -> list[str]:
                refs: list[str] = []
                if isinstance(obj, str) and obj.startswith("$"):
                    refs.append(obj[1:])
                elif isinstance(obj, dict):
                    for v in obj.values():
                        refs.extend(_collect_env_refs(v))
                elif isinstance(obj, list):
                    for item in obj:
                        refs.extend(_collect_env_refs(item))
                return refs

            env_refs = _collect_env_refs(model)
            model_name = model.get("name", "default")
            for var in env_refs:
                label = f"{var} set (model: {model_name})"
                if os.environ.get(var):
                    results.append(CheckResult(label, "ok"))
                else:
                    results.append(
                        CheckResult(
                            label,
                            "fail",
                            fix=f"Add {var}=<your-key> to your .env file",
                        )
                    )
    except Exception as exc:
        results.append(CheckResult("LLM API key check", "fail", str(exc)))

    return results


def check_llm_package(config_path: Path) -> list[CheckResult]:
    """Check that the LangChain provider package is installed."""
    if not config_path.exists():
        return []

    results: list[CheckResult] = []
    try:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        seen_packages: set[str] = set()
        for model in data.get("models", []):
            use = model.get("use", "")
            if ":" in use:
                package_path = use.split(":")[0]
                # e.g. langchain_openai → langchain-openai
                top_level = package_path.split(".")[0]
                pip_name = top_level.replace("_", "-")
                if pip_name in seen_packages:
                    continue
                seen_packages.add(pip_name)
                label = f"{pip_name} installed"
                try:
                    __import__(top_level)
                    results.append(CheckResult(label, "ok"))
                except ImportError:
                    results.append(
                        CheckResult(
                            label,
                            "fail",
                            fix=f"cd backend && uv add {pip_name}",
                        )
                    )
    except Exception as exc:
        results.append(CheckResult("LLM package check", "fail", str(exc)))

    return results


def check_llm_auth(config_path: Path) -> list[CheckResult]:
    if not config_path.exists():
        return []

    results: list[CheckResult] = []
    try:
        data = _load_yaml_file(config_path)
        for model in data.get("models", []):
            use = model.get("use", "")
            model_name = model.get("name", "default")

            if use == "deerflow.models.openai_codex_provider:CodexChatModel":
                auth_path = Path(os.environ.get("CODEX_AUTH_PATH", "~/.codex/auth.json")).expanduser()
                if auth_path.exists():
                    results.append(CheckResult(f"Codex CLI auth available (model: {model_name})", "ok", str(auth_path)))
                else:
                    results.append(
                        CheckResult(
                            f"Codex CLI auth available (model: {model_name})",
                            "fail",
                            str(auth_path),
                            fix="Run `codex login`, or set CODEX_AUTH_PATH to a valid auth.json",
                        )
                    )

            if use == "deerflow.models.claude_provider:ClaudeChatModel":
                credential_paths = [Path(os.environ["CLAUDE_CODE_CREDENTIALS_PATH"]).expanduser() for env_name in ("CLAUDE_CODE_CREDENTIALS_PATH",) if os.environ.get(env_name)]
                credential_paths.append(Path("~/.claude/.credentials.json").expanduser())
                has_oauth_env = any(
                    os.environ.get(name)
                    for name in (
                        "ANTHROPIC_API_KEY",
                        "CLAUDE_CODE_OAUTH_TOKEN",
                        "ANTHROPIC_AUTH_TOKEN",
                        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
                    )
                )
                existing_path = next((path for path in credential_paths if path.exists()), None)
                if has_oauth_env or existing_path is not None:
                    detail = "env var set" if has_oauth_env else str(existing_path)
                    results.append(CheckResult(f"Claude auth available (model: {model_name})", "ok", detail))
                else:
                    results.append(
                        CheckResult(
                            f"Claude auth available (model: {model_name})",
                            "fail",
                            fix=("Set ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN, or place credentials at ~/.claude/.credentials.json"),
                        )
                    )
    except Exception as exc:
        results.append(CheckResult("LLM auth check", "fail", str(exc)))
    return results


def check_web_search(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="web_search", label="web search configured")


def check_web_tool(config_path: Path, *, tool_name: str, label: str) -> CheckResult:
    """Warn (not fail) if a web capability is not configured."""
    if not config_path.exists():
        return CheckResult(label, "skip")

    try:
        from dotenv import load_dotenv

        env_path = config_path.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)

        data = _load_yaml_file(config_path)

        tool_entries = [t for t in data.get("tools", []) if t.get("name") == tool_name]
        if not tool_entries:
            return CheckResult(
                label,
                "warn",
                f"no {tool_name} tool in config",
                fix=f"Run 'make setup' to configure {tool_name}",
            )

        free_providers = {
            "web_search": {
                "searxng": "SearXNG (self-hosted, no key needed)",
                "ddg_search": "DuckDuckGo (no key needed)",
            },
            "web_fetch": {
                "community.web_fetch.tools": "web_fetch dispatcher (Camoufox local browser default, no key needed)",
                "jina_ai": "Jina AI Reader (no key needed)",
                "crawl4ai": "Crawl4AI (self-hosted, no key needed)",
            },
            "image_search": {"deerflow.community.image_search.tools": "DuckDuckGo Images (no key needed)"},
        }
        key_providers = {
            "web_search": {
                "tavily": "TAVILY_API_KEY",
                "infoquest": "INFOQUEST_API_KEY",
                "exa": "EXA_API_KEY",
                "firecrawl": "FIRECRAWL_API_KEY",
                "fastcrw": "CRW_API_KEY",
                "brave": "BRAVE_SEARCH_API_KEY",
                "serper": "SERPER_API_KEY",
            },
            "web_fetch": {
                "infoquest": "INFOQUEST_API_KEY",
                "exa": "EXA_API_KEY",
                "firecrawl": "FIRECRAWL_API_KEY",
                "fastcrw": "CRW_API_KEY",
            },
            "image_search": {
                "brave": "BRAVE_SEARCH_API_KEY",
                "infoquest": "INFOQUEST_API_KEY",
                "serper": "SERPER_API_KEY",
            },
            "web_capture": {
                "browserless": "BROWSERLESS_TOKEN",
            },
        }
        key_fields = {
            "web_capture": {
                "browserless": "token",
            },
        }

        def _configured_key_detail(tool: dict, default_var: str, key_field: str = "api_key") -> tuple[Status, str] | None:
            configured_key = tool.get(key_field)
            if isinstance(configured_key, str) and configured_key.strip():
                key = configured_key.strip()
                if key.startswith("$"):
                    env_name = key[1:]
                    val = os.environ.get(env_name)
                    if val and val.strip():
                        return ("ok", f"{env_name} set from config")
                    # The referenced var is unset; fall through to the default
                    # env var below, which tools use as a runtime fallback.
                else:
                    return ("warn", f"literal {key_field} set in config")

            val = os.environ.get(default_var)
            return ("ok", f"{default_var} set") if val and val.strip() else None

        def _browserless_self_hosted(tool: dict) -> bool:
            base_url = str(tool.get("base_url") or "http://localhost:3032").lower()
            return "browserless.io" not in base_url

        for tool in tool_entries:
            use = tool.get("use", "")
            for provider, detail in free_providers.get(tool_name, {}).items():
                if provider in use:
                    return CheckResult(label, "ok", detail)

        for tool in tool_entries:
            use = tool.get("use", "")
            for provider, var in key_providers.get(tool_name, {}).items():
                if provider in use:
                    key_field = key_fields.get(tool_name, {}).get(provider, "api_key")
                    key_status = _configured_key_detail(tool, var, key_field=key_field)
                    if key_status:
                        status, detail = key_status
                        if status == "warn":
                            return CheckResult(
                                label,
                                "warn",
                                f"{provider} ({detail})",
                                fix=f"Move the {key_field} to .env as {var}=<your-key> and reference it as ${var}",
                            )
                        return CheckResult(label, "ok", f"{provider} ({detail})")
                    if tool_name == "web_capture" and provider == "browserless" and _browserless_self_hosted(tool):
                        return CheckResult(label, "ok", "browserless (self-hosted, token optional)")
                    return CheckResult(
                        label,
                        "warn",
                        f"{provider} configured but {var} not set",
                        fix=f"Add {var}=<your-key> to .env, or run 'make setup'",
                    )

        for tool in tool_entries:
            use = tool.get("use", "")
            split = _split_use_path(use)
            if split is None:
                return CheckResult(
                    label,
                    "fail",
                    f"invalid use path: {use}",
                    fix="Use a valid module:path provider from config.example.yaml",
                )
            module_name, attr_name = split
            try:
                module = import_module(module_name)
                getattr(module, attr_name)
            except Exception as exc:
                return CheckResult(
                    label,
                    "fail",
                    f"provider import failed: {use} ({exc})",
                    fix="Install the provider dependency or pick a valid provider in `make setup`",
                )

        return CheckResult(label, "ok")
    except Exception as exc:
        return CheckResult(label, "warn", str(exc))


def check_web_fetch(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="web_fetch", label="web fetch configured")


def check_web_capture(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="web_capture", label="web capture configured")


def check_image_search(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="image_search", label="image search configured")


# The tool names every fresh config ships with (config.example.yaml's tools
# section). Doctor warns when one goes missing so "the agent says it has no
# tools" is diagnosable; `make config-upgrade` backfills them.
CORE_TOOL_NAMES = (
    "web_search",
    "web_fetch",
    "image_search",
    "ls",
    "read_file",
    "glob",
    "grep",
    "write_file",
    "str_replace",
    "bash",
)


def check_core_tools(config_path: Path) -> CheckResult:
    """Warn when default tools are missing from config.yaml's tools list."""
    if not config_path.exists():
        return CheckResult("default toolset present", "skip")
    try:
        data = _load_yaml_file(config_path)
        tools = data.get("tools")
        if not isinstance(tools, list) or not tools:
            return CheckResult(
                "default toolset present",
                "fail",
                "no tools section — the agent has no web/file/bash tools",
                fix="Run 'make config-upgrade' to restore the default toolset",
            )
        names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        missing = [name for name in CORE_TOOL_NAMES if name not in names]
        if missing:
            return CheckResult(
                "default toolset present",
                "warn",
                f"missing: {', '.join(missing)}",
                fix="Run 'make config-upgrade' to backfill the default toolset",
            )
        return CheckResult("default toolset present", "ok", f"{len(tools)} tool(s)")
    except Exception as exc:
        return CheckResult("default toolset present", "warn", str(exc))


def check_frontend_env(project_root: Path) -> CheckResult:
    env_path = project_root / "frontend" / ".env"
    if env_path.exists():
        return CheckResult("frontend/.env found", "ok")
    return CheckResult(
        "frontend/.env found",
        "warn",
        fix="Run 'make setup' or copy frontend/.env.example to frontend/.env",
    )


def check_sandbox(config_path: Path) -> list[CheckResult]:
    if not config_path.exists():
        return [CheckResult("sandbox configured", "skip")]

    try:
        data = _load_yaml_file(config_path)
        sandbox = data.get("sandbox")
        if not isinstance(sandbox, dict):
            return [
                CheckResult(
                    "sandbox configured",
                    "fail",
                    "missing sandbox section",
                    fix="Run 'make setup' to choose an execution mode",
                )
            ]

        sandbox_use = sandbox.get("use", "")
        tools = data.get("tools", [])
        tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        results: list[CheckResult] = []

        if "LocalSandboxProvider" in sandbox_use:
            results.append(CheckResult("sandbox configured", "ok", "Local sandbox"))
            has_bash_tool = "bash" in tool_names
            allow_host_bash = bool(sandbox.get("allow_host_bash", False))
            if has_bash_tool and not allow_host_bash:
                results.append(
                    CheckResult(
                        "bash compatibility",
                        "warn",
                        "bash tool configured but inactive: local sandbox with host bash disabled (agent cannot run git or programs)",
                        fix="Run 'make sandbox-enable MODE=container' for isolated bash, or set sandbox.allow_host_bash: true only in a fully trusted environment",
                    )
                )
            elif allow_host_bash:
                results.append(
                    CheckResult(
                        "bash compatibility",
                        "warn",
                        "host bash enabled on LocalSandboxProvider",
                        fix="Use container sandbox for stronger isolation when bash is required",
                    )
                )
        elif "AioSandboxProvider" in sandbox_use:
            results.append(CheckResult("sandbox configured", "ok", "Container sandbox"))
            if "bash" not in tool_names:
                results.append(
                    CheckResult(
                        "bash tool present",
                        "warn",
                        "container sandbox without a bash tool — the agent cannot run commands (git, program runs)",
                        fix="Run 'make config-upgrade' to backfill the default toolset",
                    )
                )
            if not sandbox.get("provisioner_url") and not (shutil.which("docker") or shutil.which("container")):
                results.append(
                    CheckResult(
                        "container runtime available",
                        "warn",
                        "no Docker/Apple Container runtime detected",
                        fix="Install Docker Desktop / Apple Container, or switch to local sandbox",
                    )
                )
        elif sandbox_use:
            results.append(CheckResult("sandbox configured", "ok", sandbox_use))
        else:
            results.append(
                CheckResult(
                    "sandbox configured",
                    "fail",
                    "sandbox.use is empty",
                    fix="Run 'make setup' to choose an execution mode",
                )
            )
        return results
    except Exception as exc:
        return [CheckResult("sandbox configured", "fail", str(exc))]


def check_env_file(project_root: Path) -> CheckResult:
    env_path = project_root / ".env"
    if env_path.exists():
        return CheckResult(".env found", "ok")
    return CheckResult(
        ".env found",
        "warn",
        fix="Run 'make setup' or copy .env.example to .env",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    config_path = project_root / "config.yaml"

    # Load .env early so key checks work
    try:
        from dotenv import load_dotenv

        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass

    print()
    print(bold("DeerFlow Health Check"))
    print("═" * 40)

    sections: list[tuple[str, list[CheckResult]]] = []

    # ── System Requirements ────────────────────────────────────────────────────
    sys_checks = [
        check_python(),
        check_node(),
        check_pnpm(),
        check_uv(),
        check_nginx(),
    ]
    sections.append(("System Requirements", sys_checks))

    # ── Configuration ─────────────────────────────────────────────────────────
    cfg_checks: list[CheckResult] = [
        check_env_file(project_root),
        check_frontend_env(project_root),
        check_config_exists(config_path),
        check_config_duplicate_keys(config_path),
        check_config_version(config_path, project_root),
        check_config_loadable(config_path),
        check_models_configured(config_path),
        check_model_pricing(config_path),
        check_core_tools(config_path),
        *check_env_placeholders(config_path),
        *check_config_unknown_keys(config_path),
    ]
    sections.append(("Configuration", cfg_checks))

    # ── LLM Provider ──────────────────────────────────────────────────────────
    llm_checks: list[CheckResult] = [
        *check_llm_api_key(config_path),
        *check_llm_auth(config_path),
        *check_llm_package(config_path),
    ]
    sections.append(("LLM Provider", llm_checks))

    # ── Web Capabilities ─────────────────────────────────────────────────────
    search_checks = [
        check_web_search(config_path),
        check_web_fetch(config_path),
        check_web_capture(config_path),
        check_image_search(config_path),
    ]
    sections.append(("Web Capabilities", search_checks))

    # ── Sandbox ──────────────────────────────────────────────────────────────
    sandbox_checks = check_sandbox(config_path)
    sections.append(("Sandbox", sandbox_checks))

    # ── Render ────────────────────────────────────────────────────────────────
    total_fails = 0
    total_warns = 0

    for section_title, checks in sections:
        print()
        print(bold(section_title))
        for cr in checks:
            cr.print()
            if cr.status == "fail":
                total_fails += 1
            elif cr.status == "warn":
                total_warns += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("═" * 40)
    if total_fails == 0 and total_warns == 0:
        print(f"Status: {green('Ready')}")
        print(f"Run {cyan('make dev')} to start DeerFlow")
    elif total_fails == 0:
        print(f"Status: {yellow(f'Ready ({total_warns} warning(s))')}")
        print(f"Run {cyan('make dev')} to start DeerFlow")
    else:
        print(f"Status: {red(f'{total_fails} error(s), {total_warns} warning(s)')}")
        print("Fix the errors above, then run 'make doctor' again.")

    print()
    return 0 if total_fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
