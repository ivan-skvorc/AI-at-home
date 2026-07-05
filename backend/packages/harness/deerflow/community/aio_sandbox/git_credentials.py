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

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from .aio_sandbox import AioSandbox

logger = logging.getLogger(__name__)

TOKEN_ENV_VAR = "GITHUB_TOKEN"
CREDENTIAL_HELPER_PATH = "/usr/local/bin/deer-flow-git-credential"
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

# Single command string: install the helper and scope it to github.com over
# https. `--replace-all` keeps re-runs (e.g. re-created containers reusing a
# persisted home) idempotent instead of accumulating duplicate helper entries.
_SETUP_COMMAND = f"chmod 755 {CREDENTIAL_HELPER_PATH} && git config --global --replace-all credential.https://github.com.helper {CREDENTIAL_HELPER_PATH} && echo {_SETUP_OK_MARKER}"


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
        sandbox.write_file(CREDENTIAL_HELPER_PATH, CREDENTIAL_HELPER_SCRIPT)
    except Exception as e:
        logger.warning(f"Sandbox {sandbox.id}: could not write git credential helper: {e}")
        return False

    output = sandbox.execute_command(_SETUP_COMMAND)
    if _SETUP_OK_MARKER not in output:
        # Output of the setup command contains no secret (the command embeds
        # none), so it is safe to include for diagnosis.
        logger.warning(f"Sandbox {sandbox.id}: git credential helper setup did not complete (git missing in image?): {output.strip()[:500]}")
        return False

    logger.info(f"Sandbox {sandbox.id}: GitHub credential helper installed (token configured: {token_configured})")
    return True
