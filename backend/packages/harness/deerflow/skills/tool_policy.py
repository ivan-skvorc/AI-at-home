import logging
from typing import Protocol

from deerflow.skills.types import Skill

logger = logging.getLogger(__name__)


class NamedTool(Protocol):
    name: str


# Framework built-ins that remain available even when an active skill declares
# allowed-tools. They support controlled file/review/discovery workflows rather
# than extending the reviewed/activated skill's own business-tool authority.
# In particular, promotion through tool_search does not restore a tool removed
# by SkillToolPolicyMiddleware, and describe_skill only returns catalog metadata.
ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES = frozenset(
    {
        "describe_skill",
        "read_file",
        "review_skill_package",
        "tool_search",
    }
)


def allowed_tool_names_for_skills(
    skills: list[Skill],
    *,
    framework_tool_names: set[str] | frozenset[str] = frozenset(),
    exempt_framework_only: bool = True,
) -> set[str] | None:
    """Return the union of explicit skill allowed-tools declarations.

    None means legacy allow-all behavior. It is returned when no loaded skill
    scopes the agent to a *business* toolset. Once a skill declares at least one
    non-framework tool, legacy skills without the field contribute no tools
    instead of disabling the explicit restrictions from other skills.

    ``exempt_framework_only`` (default ``True``) controls the framework-only
    exemption used by the **static** (subagent / build-time) filter path: the
    always-available framework built-ins (``ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES``,
    plus any extra ``framework_tool_names`` the caller passes) never count as a
    business-tool declaration, so a declaration naming only those tools — or an
    empty declaration — does **not** scope the agent to a business toolset and is
    ignored for the purpose of deciding whether restrictions apply. Without this,
    merely *enabling* a framework skill such as the built-in ``skill-reviewer``
    (whose only allowed-tool, ``review_skill_package``, is already always-available)
    would strip every other tool from the lead agent **and every subagent**,
    leaving them with just the framework built-ins — even though the skill was
    never activated. The framework built-ins are folded in here (not only at the
    ``filter_tools_by_skill_allowed_tools`` caller) so the exemption also holds on
    the subagent path, which calls that filter without an explicit framework set.

    ``SkillToolPolicyMiddleware`` (the lead agent's **dynamic** policy) passes
    ``exempt_framework_only=False`` because it only ever sees *actively* invoked
    skills (slash-activated, or read into ``skill_context``). For those, an
    explicit empty ``allowed-tools`` is a deliberate "framework tools only"
    scoping and must restrict — unlike the passive enabled-skill case the
    exemption protects — so the two paths intentionally differ here.
    """
    if not skills:
        return None

    framework = set(framework_tool_names) | ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES
    allowed: set[str] = set()
    has_explicit_declaration = False
    for skill in skills:
        if skill.allowed_tools is None:
            continue
        if exempt_framework_only:
            business_tools = set(skill.allowed_tools) - framework
            if not business_tools:
                # Only framework tools (or none): not a real business-tool scoping.
                logger.info(
                    "Skill %s declares only framework/empty allowed-tools (%s); not restricting the global toolset",
                    skill.name,
                    sorted(skill.allowed_tools),
                )
                continue
        has_explicit_declaration = True
        allowed.update(skill.allowed_tools)

    if not has_explicit_declaration:
        return None
    return allowed


def filter_tools_by_skill_allowed_tools[ToolT: NamedTool](
    tools: list[ToolT],
    skills: list[Skill],
    *,
    always_allowed_tool_names: set[str] | frozenset[str] = frozenset(),
) -> list[ToolT]:
    allowed = allowed_tool_names_for_skills(skills, framework_tool_names=always_allowed_tool_names)
    if allowed is None:
        return tools

    allowed_with_framework_tools = allowed | set(always_allowed_tool_names)
    return [tool for tool in tools if tool.name in allowed_with_framework_tools]
