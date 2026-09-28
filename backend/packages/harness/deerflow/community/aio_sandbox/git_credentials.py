"""In-container git credential setup for GitHub access.

When an AIO sandbox container starts, DeerFlow installs a small git credential
helper inside it so the agent can run a plain
``git clone https://github.com/owner/repo.git`` against private repos. The
helper reads ``GITHUB_TOKEN`` from the *container's* environment at call time
(forwarded via ``sandbox.environment`` in config.yaml), which keeps the token
out of:

- clone URLs and shell history (no ``https://token@github.com`` rewriting),
- agent-visible tool output (git talks to the helper over a pipe),
- any ``.git/config`` (git never persists credentials supplied by a helper),
- host-side logs (the helper script itself contains no secret, and the
  container-run command line is already env-redacted by the local backend).

The helper is installed unconditionally: without a token it emits an
actionable hint on stderr instead of leaving the agent with git's bare
"could not read Username" failure, and public-repo clones are unaffected
because git only consults credential helpers after the server asks for auth.

The token is still readable by anything executing inside the sandbox
container (it is ordinary process environment there) — that exposure is
inherent to giving the agent authenticated git, which is why the docs insist
on a fine-grained PAT scoped to selected repos with Contents permission only.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from .aio_sandbox import AioSandbox

logger = logging.getLogger(__name__)

TOKEN_ENV_VAR = "GITHUB_TOKEN"
# Relative to the sandbox user's $HOME. The pinned image (agent-infra/sandbox
# 1.11.0) runs unprivileged, so the former /usr/local/bin location raised
# PermissionError, the helper was never installed, and git ignored the token.
# The user's own home is the one place its shell can always write.
CREDENTIAL_HELPER_HOME_PATH = ".local/bin/deer-flow-git-credential"
_SETUP_OK_MARKER = "DEER_FLOW_GIT_CREDENTIALS_OK"

# POSIX sh, no bashisms. The script deliberately contains no secret material:
# it resolves the token from the container environment on every invocation.
# Hint lines use single quotes so `$GITHUB_TOKEN` is printed literally.
CREDENTIAL_HELPER_SCRIPT = """#!/bin/sh
# Installed by DeerFlow at sandbox creation (deerflow.community.aio_sandbox).
# Supplies GITHUB_TOKEN from the container environment to git for github.com,
# so the token never appears in clone URLs, shell history, or .git/config.
if [ "$1" != "get" ]; then
    exit 0
fi
if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo 'deer-flow: GITHUB_TOKEN is not set in the sandbox environment;' >&2
    echo 'deer-flow: cloning private github.com repos requires it. Set it in .env' >&2
    echo 'deer-flow: and forward it via sandbox.environment in config.yaml' >&2
    echo 'deer-flow: (GITHUB_TOKEN: $GITHUB_TOKEN) — see .env.example.' >&2
    exit 0
fi
printf 'protocol=https\\n'
printf 'host=github.com\\n'
printf 'username=x-access-token\\n'
printf 'password=%s\\n' "$GITHUB_TOKEN"
"""


def build_setup_command() -> str:
    """One shell line that installs the helper and scopes it to github.com.

    It runs through the shell rather than the file API so the file is created
    by the same user whose ``~/.gitconfig`` git reads, in a directory that user
    owns. Constraints, since it runs in the agent's persistent shell session:

    - one line (the script travels base64-encoded), so it is one prompt;
    - a subshell, so ``helper`` never leaks into the agent's later commands;
    - the success marker is assembled at run time (``_"OK"``), so a shell that
      echoes the command back cannot fake success;
    - ``--replace-all`` keeps re-runs (a re-created container reusing a
      persisted home) from accumulating duplicate helper entries.
    """
    encoded = base64.b64encode(CREDENTIAL_HELPER_SCRIPT.encode("utf-8")).decode("ascii")
    marker_prefix, marker_tail = _SETUP_OK_MARKER.rsplit("_", 1)
    steps = [
        '[ -n "$HOME" ]',
        f'helper="$HOME/{CREDENTIAL_HELPER_HOME_PATH}"',
        'mkdir -p "${helper%/*}"',
        f"printf '%s' '{encoded}' | base64 -d > \"$helper\"",
        'chmod 755 "$helper"',
        'git config --global --replace-all credential.https://github.com.helper "$helper"',
        f'echo {marker_prefix}_"{marker_tail}"',
    ]
    return "(" + " && ".join(steps) + ")"


def setup_github_credentials(sandbox: AioSandbox, *, token_configured: bool) -> bool:
    """Install the GitHub credential helper inside a freshly created sandbox.

    Best-effort: failures are logged and reported via the return value, never
    raised — a sandbox without git (custom image) must still come up fine.
    Neither the token value nor any command containing it is ever written,
    executed, or logged here; the helper resolves it from the container
    environment at git-invocation time.

    Args:
        sandbox: The ready sandbox to configure.
        token_configured: Whether a non-empty GITHUB_TOKEN is being injected
            into the container environment (used only for logging).

    Returns:
        True when the helper was installed and git accepted the config.
    """
    try:
        output = sandbox.execute_command(build_setup_command())
    except Exception as e:
        logger.warning(f"Sandbox {sandbox.id}: could not run git credential helper setup: {e}")
        return False
    if _SETUP_OK_MARKER not in output:
        # Output of the setup command contains no secret (the command embeds
        # none), so the shell's own error is safe to log as the cause.
        logger.warning(f"Sandbox {sandbox.id}: git credential helper setup did not complete (unwritable $HOME, or git/base64 missing in image?): {output.strip()[:500]}")
        return False

    logger.info(f"Sandbox {sandbox.id}: GitHub credential helper installed (token configured: {token_configured})")
    return True
