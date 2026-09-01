"""Fork: the per-conversation internet switch (FORK.md §27).

The composer carries a globe toggle. Turning it off sends ``internet_enabled:
false`` in the run context, and this module is the single place that decides
what that means for a run's tool surface.

Three properties are load-bearing and every one of them is silent when broken:

* **Only an explicit ``False`` opts out.** Absent means "no opinion", so IM
  channels, the TUI, the scheduler, and embedded callers — none of which have a
  composer — keep the operator's configured tool list unchanged. A missing key
  must never be read as "offline", or a Feishu thread loses web search the day
  this ships.
* **The classification fails closed.** Offline keeps a named allowlist of tool
  groups that cannot reach the internet on the model's behalf; *everything else*
  — an unknown group, a group added by a future upstream merge, a group an
  operator invented for a custom tool — is treated as network-reaching and
  dropped. A blocklist would silently pass the next provider someone adds.
* **It is a capability filter, not a request-time veto.** The tools are removed
  before the agent is assembled, so deferred tool search cannot promote one back
  into the catalog, a skill's ``allowed-tools`` cannot re-admit one, and the
  model never sees a schema for a tool it may not call. Enforcement that lives
  in a middleware would be one exemption away from being bypassed.

Scope, stated plainly because the toggle's whole value is that it is honest:
this removes the tools that *fetch from the internet for the model* — the
``web`` and ``browser`` groups, every MCP tool (an MCP server is a network
endpoint by construction, and a local one still proxies to remote APIs) and the
ACP agent tool (an external agent with its own uncontrolled network access). It
does not sever a sandbox shell's own network, which belongs to the container
the operator runs; see FORK.md §27 for that boundary and how to close it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Run-context key written by the composer's toggle.
INTERNET_ENABLED_CONTEXT_KEY = "internet_enabled"

# Tool groups that stay available while the internet is off. This is an
# allowlist on purpose (see the module docstring): a group that is not named
# here is assumed to reach the internet and is dropped.
#
# ``bash`` is in the list because a shell is the sandbox's local execution
# surface — removing it would break running code, not browsing — and because
# whether that shell has a route to the internet is a property of the sandbox
# container, not of this switch. The offline notice tells the model not to use
# it as a network workaround.
OFFLINE_ALLOWED_TOOL_GROUPS: frozenset[str] = frozenset(
    {
        "file:read",
        "file:write",
        "bash",
        # Local ComfyUI image/video generation (FORK.md §23/§26).
        "media",
        # Self-hosted knowledge base (RAGFlow); reads an operator-run index.
        "knowledge",
    }
)

# Appended to the rendered system prompt when the run is offline. Deliberately
# appended rather than rendered through a ``{placeholder}``: the system prompt
# template is user-editable (FORK.md §19), so a new placeholder would simply not
# exist in an operator's saved SYSTEM_PROMPT.md and the notice would vanish for
# exactly the people who customized their prompt.
OFFLINE_SYSTEM_PROMPT_NOTICE = """

## Internet Access: OFF

The user turned this conversation's internet switch off, so every tool that
reaches the internet (web search, web fetch, browser control, MCP servers,
external agents) has been removed from your toolset for this turn.

- Answer from the conversation, the user's files, and your own knowledge.
- Do not claim to have looked something up, and do not present recalled facts as
  fresh or verified. Say plainly when an answer needs a source you cannot reach.
- Do not try to route around the switch — no network calls from the shell, no
  installing packages from a remote index, no asking another tool to fetch a URL.
- If the task genuinely requires the internet, say so and let the user decide;
  they can turn the switch back on in the composer.
"""


def internet_access_enabled(context: Mapping[str, Any] | None) -> bool:
    """Return whether this run may use internet-reaching tools.

    Only an explicit boolean ``False`` opts out. Anything else — the key absent,
    ``None``, ``True``, or a non-boolean a client made up — leaves the operator's
    configured tool list alone.
    """
    if not isinstance(context, Mapping):
        return True
    return context.get(INTERNET_ENABLED_CONTEXT_KEY) is not False


def is_offline_safe_group(group: object) -> bool:
    """Return whether a tool group survives with the internet switched off."""
    return isinstance(group, str) and group in OFFLINE_ALLOWED_TOOL_GROUPS


def append_offline_notice(system_prompt: str) -> str:
    """Append the offline notice to an already-rendered system prompt."""
    if OFFLINE_SYSTEM_PROMPT_NOTICE.strip() in system_prompt:
        return system_prompt
    return f"{system_prompt.rstrip()}\n{OFFLINE_SYSTEM_PROMPT_NOTICE}"
