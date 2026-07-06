"""External sandbox backend — binds to one pre-existing AIO sandbox container.

Instead of auto-spawning a container per conversation (LocalContainerBackend)
or delegating Pod lifecycle to the provisioner (RemoteSandboxBackend), this
backend connects to a single externally-managed AIO sandbox container whose
URL is configured via ``sandbox.base_url`` in config.yaml::

    sandbox:
      use: deerflow.community.aio_sandbox:AioSandboxProvider
      base_url: http://localhost:8091

The container is typically started with ``make sandbox-up``
(docker/docker-compose.sandbox.yml) and its lifecycle belongs to the user:
this backend NEVER creates, stops, or removes it — ``destroy()`` is a no-op,
and no docker CLI command is ever executed. Health is checked over HTTP
(``GET {base_url}/v1/sandbox``), the same readiness endpoint the provider
polls after creation.

Because there is exactly one container, every thread shares it: ``create``
and ``discover`` both return the same static :class:`SandboxInfo` with a
stable sandbox id derived from the base URL. Consequences the provider layer
absorbs:

- ``mounts`` are ignored (declare volumes in docker-compose.sandbox.yml),
- ``environment`` entries cannot be injected by DeerFlow (the exec API has no
  per-command env support) — they must be set on the container itself; the
  bundled compose file passes ``GITHUB_TOKEN`` through from the host env,
- warm-pool eviction / idle destruction / shutdown all funnel into the no-op
  ``destroy()``, so provider lifecycle management can stay backend-agnostic.
"""

from __future__ import annotations

import hashlib
import logging

import requests

from .backend import SandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)

_HEALTH_CHECK_TIMEOUT = 5  # seconds


class ExternalSandboxBackend(SandboxBackend):
    """Backend bound to a single externally-managed AIO sandbox container.

    Typical config.yaml::

        sandbox:
          use: deerflow.community.aio_sandbox:AioSandboxProvider
          base_url: http://localhost:8091
    """

    #: The external container pre-exists, so DeerFlow's per-creation session
    #: init (git credential helper) must also run when the sandbox is merely
    #: discovered/adopted rather than created by this process.
    session_init_on_discover = True

    def __init__(self, base_url: str):
        """Initialize with the external sandbox URL.

        Args:
            base_url: URL of the externally-managed sandbox API
                      (e.g., ``http://localhost:8091``).
        """
        self._base_url = base_url.rstrip("/")
        # Stable id derived from the base URL: every thread and every process
        # maps to the same external sandbox entry.
        self._sandbox_id = f"external-{hashlib.sha256(self._base_url.encode()).hexdigest()[:8]}"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def external_sandbox_id(self) -> str:
        return self._sandbox_id

    def _static_info(self) -> SandboxInfo:
        return SandboxInfo(sandbox_id=self._sandbox_id, sandbox_url=self._base_url)

    def _is_healthy(self) -> bool:
        """GET {base_url}/v1/sandbox — same readiness endpoint the provider polls."""
        try:
            response = requests.get(f"{self._base_url}/v1/sandbox", timeout=_HEALTH_CHECK_TIMEOUT)
            return response.status_code == 200
        except requests.RequestException as exc:
            logger.debug(f"External sandbox health check failed for {self._base_url}: {exc}")
            return False

    # ── SandboxBackend interface ──────────────────────────────────────────

    def create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        user_id: str | None = None,
    ) -> SandboxInfo:
        """Return the static info for the external container.

        Nothing is provisioned — the container already exists. The
        thread-derived ``sandbox_id`` is ignored in favour of the stable
        external id so all threads converge on one tracked sandbox.
        ``extra_mounts`` are ignored (mounts belong in the compose file).
        """
        del thread_id, sandbox_id, extra_mounts, user_id
        return self._static_info()

    def destroy(self, info: SandboxInfo) -> None:
        """NO-OP: never touch the user's externally-managed container.

        Idle destruction, warm-pool eviction, and shutdown all land here;
        absorbing them keeps the provider free of external-mode special
        cases while guaranteeing the container survives DeerFlow restarts.
        """
        logger.debug(f"External sandbox backend: skipping destroy of externally-managed sandbox {info.sandbox_id} at {info.sandbox_url}")

    def is_alive(self, info: SandboxInfo) -> bool:
        """HTTP health check against the external sandbox API."""
        del info
        return self._is_healthy()

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """Return the static entry when the external sandbox is healthy."""
        del sandbox_id
        if self._is_healthy():
            return self._static_info()
        return None

    def list_running(self) -> list[SandboxInfo]:
        """Return the static entry when healthy, else an empty list."""
        if self._is_healthy():
            return [self._static_info()]
        return []
