"""Explicit backend dotenv selection, independent of configuration imports."""

import os
from io import StringIO
from pathlib import Path

from dotenv import load_dotenv

#: One GitHub token, read under two names: the sandbox's git credential helper
#: and the bundled skills read GITHUB_TOKEN, GitHub's MCP servers read
#: GITHUB_PERSONAL_ACCESS_TOKEN. scripts/doctor.py mirrors this tuple.
GITHUB_TOKEN_NAMES = ("GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN")


def config_env_value(name: str) -> str | None:
    """Return what a ``$name`` config reference resolves to; None when unset.

    Every name reads the process environment, except the GitHub token names:
    each falls back to the other, so ``.env`` may use either, and neither set
    resolves to an empty string. The token is optional (GitHub stays anonymous
    without it), and the generated container-sandbox config forwards
    ``$GITHUB_TOKEN`` whether or not one exists, so an unset token must not stop
    the Gateway from loading its config.
    """
    value = os.environ.get(name)
    if name not in GITHUB_TOKEN_NAMES or value:
        return value
    return next((os.environ[alias] for alias in GITHUB_TOKEN_NAMES if os.environ.get(alias)), "")


def load_selected_env_file() -> bool:
    """Load DEER_FLOW_ENV_FILE; return False only when the option is unset.

    Relative paths use the process working directory. Callers retain their
    original load_dotenv() call for default discovery when this returns False.
    Existing process variables (including empty values) always take precedence.
    """
    selected = os.environ.get("DEER_FLOW_ENV_FILE")
    if selected is None:
        return False
    # Match python-dotenv's switch without silently ignoring explicit selection.
    if os.environ.get("PYTHON_DOTENV_DISABLED", "").casefold() in {"1", "true", "t", "yes", "y"}:
        raise ValueError("DEER_FLOW_ENV_FILE cannot be used while PYTHON_DOTENV_DISABLED disables dotenv loading. Unset PYTHON_DOTENV_DISABLED or DEER_FLOW_ENV_FILE.")

    try:
        path = Path(selected)
        if not selected or not path.is_file():
            raise ValueError("Expected a regular file")
        # Read fully before parsing so decode failures cannot partially load env.
        # utf-8-sig consumes a leading BOM (Notepad / PowerShell-written files):
        # plain utf-8 keeps U+FEFF, and dotenv then parses the first variable
        # under a BOM-prefixed key that no consumer reads.
        contents = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        raise ValueError("DEER_FLOW_ENV_FILE must point to a readable UTF-8 regular file. Check the path and permissions; relative paths use the backend process working directory.") from None

    load_dotenv(stream=StringIO(contents), override=False)
    return True
