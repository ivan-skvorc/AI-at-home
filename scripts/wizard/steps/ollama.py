"""Optional step: local Ollama context sizing (VRAM budget + KV-cache type).

Runs only when an Ollama provider was selected in the LLM step. The collected
values are written to config.yaml's ``ollama:`` section, which
``scripts/sync-ollama-models.py`` reads on every launch to compute a per-model
``num_ctx`` that actually fits the GPU (see FORK.md). Skipping the step keeps
the sync's flat default cap — no behavior change.
"""

from __future__ import annotations

import json
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wizard.ui import ask_text, ask_yes_no, cyan, print_header, print_info, print_success

# Fraction of Apple unified memory that Metal lets a process use by default
# (recommendedMaxWorkingSetSize ≈ 75% of RAM); used as the detected "VRAM".
APPLE_METAL_FRACTION = 0.75


@dataclass
class OllamaStepResult:
    vram_gb: float | None
    kv_cache_type: str | None  # None = leave unset (sync assumes f16)
    system_ram_gb: float | None = None  # None = leave unset (no offload warning)


def _run_command(args: list[str], timeout: float = 5.0) -> str | None:
    """Run a detection command, returning stdout or None on any failure."""
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def parse_nvidia_smi_gib(output: str) -> float | None:
    """Sum `nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits`
    lines (MiB, one per GPU) into GiB."""
    total_mib = 0.0
    found = False
    for line in output.splitlines():
        try:
            total_mib += float(line.strip())
            found = True
        except ValueError:
            continue
    return total_mib / 1024 if found else None


def parse_rocm_smi_gib(output: str) -> float | None:
    """Sum "VRAM Total Memory (B)" across cards from `rocm-smi --showmeminfo
    vram --json` output into GiB."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    total_bytes = 0.0
    found = False
    for card in data.values():
        if not isinstance(card, dict):
            continue
        raw = card.get("VRAM Total Memory (B)")
        try:
            total_bytes += float(raw)
            found = True
        except (TypeError, ValueError):
            continue
    return total_bytes / 1024**3 if found else None


def detect_vram_gb(run: Callable[[list[str]], str | None] = _run_command, system: Callable[[], str] = platform.system) -> tuple[float, str] | None:
    """Best-effort GPU memory detection: (GiB, human-readable source) or None."""
    output = run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    if output:
        gib = parse_nvidia_smi_gib(output)
        if gib:
            return gib, "nvidia-smi"
    output = run(["rocm-smi", "--showmeminfo", "vram", "--json"])
    if output:
        gib = parse_rocm_smi_gib(output)
        if gib:
            return gib, "rocm-smi"
    if system() == "Darwin":
        output = run(["sysctl", "-n", "hw.memsize"])
        try:
            total = float((output or "").strip())
        except ValueError:
            return None
        if total > 0:
            return total / 1024**3 * APPLE_METAL_FRACTION, f"unified memory ({APPLE_METAL_FRACTION:.0%} Metal budget)"
    return None


def parse_meminfo_gib(output: str) -> float | None:
    """Read ``MemTotal`` (kB) out of /proc/meminfo into GiB."""
    for line in output.splitlines():
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            return float(parts[1]) * 1024 / 1024**3
        except ValueError:
            return None
    return None


def _read_proc_meminfo() -> str | None:
    try:
        return Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return None


def detect_system_ram_gb(
    read_meminfo: Callable[[], str | None] = _read_proc_meminfo,
    run: Callable[[list[str]], str | None] = _run_command,
) -> float | None:
    """Best-effort total system RAM in GiB, or None.

    This is the pool MoE expert offload spills into; the sync only uses it to
    warn when a model's weights exceed VRAM + RAM and would page from disk.
    """
    output = read_meminfo()
    if output:
        gib = parse_meminfo_gib(output)
        if gib:
            return gib
    output = run(["sysctl", "-n", "hw.memsize"])
    try:
        total = float((output or "").strip())
    except ValueError:
        return None
    return total / 1024**3 if total > 0 else None


def run_ollama_step(step_label: str) -> OllamaStepResult:
    print_header(f"{step_label} · Local Ollama context sizing (optional)")
    print_info("With a GPU memory budget, every launch sizes each Ollama model's context window (num_ctx) to what actually fits next to its weights.")
    print_info("Leave blank to skip — models then use their native window capped at 32768 tokens.")
    print()

    detected = detect_vram_gb()
    default = ""
    if detected:
        gib, source = detected
        default = f"{gib:.0f}"
        print_success(f"Detected {gib:.1f} GiB GPU memory via {source}")

    raw = ask_text("GPU memory budget in GB (blank to skip)", default=default)
    try:
        vram_gb = float(raw.strip())
    except (AttributeError, ValueError):
        vram_gb = 0.0
    if vram_gb <= 0:
        print_info("Skipping VRAM sizing.")
        return OllamaStepResult(vram_gb=None, kv_cache_type=None)

    # Recorded, not asked: it only powers a warning, and a wrong guess here is
    # worse than silence. Detection failing simply leaves the setting unwritten.
    system_ram_gb = detect_system_ram_gb()
    if system_ram_gb:
        print_success(f"Detected {system_ram_gb:.0f} GiB system RAM — large MoE models offload their experts into it.")

    print()
    print_info("Ollama can quantize the KV cache to q8_0 — near-lossless, roughly half the per-token memory, so roughly double the affordable context window.")
    print_info("This is a server-side Ollama setting; DeerFlow can only assume it when sizing. Only answer yes if you set it on the daemon:")
    print(f'      systemd: {cyan("sudo systemctl edit ollama")}   # add:  [Service]  Environment="OLLAMA_KV_CACHE_TYPE=q8_0"')
    print(f"      manual:  {cyan('OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve')}")
    print("      (older Ollama also needs OLLAMA_FLASH_ATTENTION=1; unsupported models silently fall back to f16)")
    use_q8 = ask_yes_no("Size for a q8_0 KV cache (I have set / will set OLLAMA_KV_CACHE_TYPE=q8_0)?", default=False)
    if use_q8:
        print_success(f"Sizing for q8_0 across {vram_gb:g} GB.")
    else:
        print_success(f"Sizing for f16 (Ollama's default) across {vram_gb:g} GB.")
    if not use_q8:
        return OllamaStepResult(vram_gb=vram_gb, kv_cache_type=None, system_ram_gb=system_ram_gb)
    return OllamaStepResult(vram_gb=vram_gb, kv_cache_type="q8_0", system_ram_gb=system_ram_gb)
