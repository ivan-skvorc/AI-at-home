"""project_host_policy: what the host tells extensions about its limits and sandbox mode."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.policy import project_host_policy

AIO = "deerflow.community.aio_sandbox:AioSandboxProvider"
LOCAL = "deerflow.sandbox.local:LocalSandboxProvider"


def _config(**sandbox) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(**sandbox))


@pytest.mark.parametrize(
    ("sandbox", "container"),
    [
        ({"use": AIO}, True),
        # What `make sandbox-enable MODE=container IMAGE=cad` writes: the image does not change the mode.
        ({"use": AIO, "image": "deerflow-sandbox-cad:local"}, True),
        # One shared container that `make sandbox-up` starts: no per-thread container, no host-backed outputs.
        ({"use": AIO, "base_url": "http://localhost:8091"}, False),
        ({"use": AIO, "provisioner_url": "http://provisioner:8002"}, False),
        ({"use": LOCAL}, False),
        ({"use": LOCAL, "allow_host_bash": True}, False),
        ({"use": "deerflow.community.e2b_sandbox:E2BSandboxProvider"}, False),
    ],
    ids=["aio-container", "aio-container-cad-image", "aio-external", "aio-provisioner", "local", "local-host-bash", "e2b"],
)
def test_the_sandbox_container_flag_follows_the_provider_mode(sandbox, container):
    assert project_host_policy(_config(**sandbox)).sandbox_container is container


def test_a_host_without_a_sandbox_section_reports_no_container():
    assert project_host_policy(SimpleNamespace()).sandbox_container is False


def test_the_sandbox_flag_does_not_disturb_the_limits():
    config = SimpleNamespace(
        sandbox=SimpleNamespace(use=AIO, base_url=None, provisioner_url=None),
        token_budget=SimpleNamespace(enabled=True, max_input_tokens=10, max_output_tokens=20, max_tokens=30, warn_threshold=0.5, hard_stop_threshold=0.9),
        subagents=SimpleNamespace(max_total_per_run=4),
    )
    policy = project_host_policy(config)
    assert (policy.token_budget_enabled, policy.max_input_tokens, policy.max_output_tokens, policy.max_total_tokens) == (True, 10, 20, 30)
    assert (policy.budget_warn_fraction, policy.budget_hard_fraction, policy.max_subagents_per_run) == (0.5, 0.9, 4)
    assert policy.sandbox_container is True
