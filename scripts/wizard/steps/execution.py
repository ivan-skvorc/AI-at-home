"""Step: execution mode and safety-related capabilities."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from wizard.ui import ask_choice, ask_yes_no, print_header, print_info, print_warning

LOCAL_SANDBOX = "deerflow.sandbox.local:LocalSandboxProvider"
CONTAINER_SANDBOX = "deerflow.community.aio_sandbox:AioSandboxProvider"


@dataclass
class ExecutionStepResult:
    sandbox_use: str
    allow_host_bash: bool
    include_bash_tool: bool
    include_write_tools: bool


def container_runtime_available() -> bool:
    """Return True when Docker or Apple Container is on PATH."""
    return bool(shutil.which("docker") or shutil.which("container"))


def run_execution_step(step_label: str = "Step 3/4") -> ExecutionStepResult:
    print_header(f"{step_label} · Execution & Safety")
    print_info("Choose how much execution power DeerFlow should have in this workspace.")

    options = [
        "Local sandbox  —  fastest, uses host filesystem paths",
        "Container sandbox  —  more isolated, requires Docker or Apple Container",
    ]
    # Default to the container sandbox when a runtime is present: it is the only
    # mode where bash (and therefore git/clone-and-debug) is safe out of the box.
    default_mode = 1 if container_runtime_available() else 0
    sandbox_idx = ask_choice("Execution mode", options, default=default_mode)
    sandbox_use = LOCAL_SANDBOX if sandbox_idx == 0 else CONTAINER_SANDBOX

    print()
    if sandbox_use == LOCAL_SANDBOX:
        print_warning("Local sandbox is convenient but not a secure shell isolation boundary.")
        print_info("Keep host bash disabled unless this is a fully trusted local workflow.")
        print_info("Without bash the agent cannot run git or execute programs (no clone-and-debug).")
        include_bash_tool = ask_yes_no("Enable bash command execution (host bash)?", default=False)
    else:
        print_info("Container sandbox isolates shell execution better than host-local mode.")
        print_info("Bash runs inside the per-thread container, so git/clone and debug runs work out of the box.")
        include_bash_tool = ask_yes_no("Enable bash command execution?", default=True)

    include_write_tools = ask_yes_no("Enable file write tools (write_file, str_replace)?", default=True)

    return ExecutionStepResult(
        sandbox_use=sandbox_use,
        allow_host_bash=sandbox_use == LOCAL_SANDBOX and include_bash_tool,
        include_bash_tool=include_bash_tool,
        include_write_tools=include_write_tools,
    )
