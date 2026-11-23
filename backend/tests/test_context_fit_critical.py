"""Critical check: a fresh request fits a synced 32K Ollama model in every composer mode.

change_cycle.md runs this before the ordinary suites (its *Critical checks*):
when it fails, local models are broken for everyone, whatever else is green.

The reported failure was a brand-new Flash chat on ``deepseek-r1:14b`` refused
with "needs about 22,910 tokens, and the window leaves 24,576". Nothing about
the conversation was large: the system prompt and the tool schemas alone had
grown past what a synced entry (``num_ctx: 32768``, ``num_predict: 8192``) can
take. No test measured that sum on the real build, so each added tool,
skill and prompt paragraph was harmless on its own and the total crept over.

This builds the real lead agent from ``config.example.yaml`` plus such an entry,
in every mode the composer offers, and measures the fixed part of the request
the way the context guard sends it: system prompt, mode additions (plan mode's
todo section, the Ultracode brief) and tool schemas in their small-window short
form. Pinned:

- the fixed part stays within ``FIXED_REQUEST_ALLOWANCE_TOKENS`` in every mode;
- the guard sends a first message in every mode instead of refusing it;
- compaction's token trigger fires before the guard would have to refuse a long
  chat in the heaviest mode.

When this fails, make the prompt or the tools smaller (FORK.md §47); raise the
allowance only together with what it costs a 32K model's conversation room.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.agents.middlewares.context_window_guard_middleware import ContextWindowGuardMiddleware, estimate_request_tokens, short_tool_schema
from deerflow.utils.context_budget import FIXED_REQUEST_ALLOWANCE_TOKENS, REQUEST_FIT_SHARE, ContextBudget, estimate_tokens

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_NAME = "local-32k"
# What scripts/sync-ollama-models.py writes for a model on a GPU of unknown size.
LARGE_MODEL_NAME = "local-128k"
OLLAMA_ENTRY = f"""models:
  - name: {MODEL_NAME}
    display_name: Local 32K (Ollama)
    use: langchain_ollama:ChatOllama
    model: qwen3:8b
    base_url: http://localhost:11434
    num_ctx: 32768
    num_predict: 8192
    reasoning: true
    supports_thinking: true
    supports_vision: false
  - name: {LARGE_MODEL_NAME}
    display_name: Local 128K (Ollama)
    use: langchain_ollama:ChatOllama
    model: qwen3:32b
    base_url: http://localhost:11434
    num_ctx: 131072
    num_predict: 8192
    supports_vision: false
"""
BUDGET = ContextBudget(context_window=32_768, reserved_output=8_192)
LIMIT = int(BUDGET.prompt_tokens * REQUEST_FIT_SHARE)

ULTRA = {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": True}
# The run context each composer mode sends (frontend/src/core/threads/run-context.ts).
MODES = {
    "flash": {"thinking_enabled": False, "is_plan_mode": False, "subagent_enabled": False},
    "thinking": {"thinking_enabled": True, "is_plan_mode": False, "subagent_enabled": False},
    "pro": {"thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": False},
    "ultra": ULTRA,
    "ultracode": ULTRA,
    "double_ultracode": ULTRA,
}


@pytest.fixture
def stock_config(tmp_path, monkeypatch):
    """config.example.yaml with one synced 32K Ollama entry, as a fresh install has it."""
    from deerflow.config.app_config import reset_app_config

    example = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")
    config = re.sub(r"(?m)^models:\n", OLLAMA_ENTRY, example, count=1)
    assert config != example, "config.example.yaml no longer has a top-level models: key"
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")
    (tmp_path / "extensions_config.json").write_text((REPO_ROOT / "extensions_config.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(tmp_path / "extensions_config.json"))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    reset_app_config()
    yield
    reset_app_config()


def _workflow_additions(mode: str, shared_workspace: str = "off") -> tuple[list[str], list[dict]]:
    """The bundled workflows extension's brief and tools on an Ultracode run.

    The plugin host loads them at Gateway start, which a bare assembly does not;
    they are taken from the extension itself so this stays the real text.
    """
    import os

    from deerflow_extension_api import AGENT_RUNS_CONTEXT_KEY
    from deerflow_extension_workflows import install

    from deerflow.extensions.plugin_tools import _model_facing_schema, plugin_tool_name

    contributed: dict = {}

    class Registry:
        def plugin(self, contribution):
            contributed["plugin"] = contribution
            return True

        def service(self, service):
            pass

        def middlewares(self, contributor):
            contributed["contributor"] = contributor

    # The operator ceilings config.example.yaml ships (FORK.md §46).
    install(
        Registry(),
        {"enabled": True, "storage_path": "workflows/workflows.sqlite", "agents": ["lead_agent"], "concurrency": 16, "global_concurrency": 32, "max_calls": 256, "timeout_seconds": 14400, "shared_workspace": shared_workspace},
    )
    plugin = contributed["plugin"]
    tools = [{"type": "function", "function": {"name": plugin_tool_name(plugin.namespace, tool.name), "description": tool.description, "parameters": _model_facing_schema(tool.input_schema)}} for tool in plugin.tools]
    from deerflow_extension_workflows.ultracode import UltracodeMode

    middleware = UltracodeMode(contributed["contributor"].config)
    options = {"community.workflows": {"mode": mode, "max_agents": 256, "max_parallel": 16, "max_minutes": 240}}
    request = SimpleNamespace(runtime=SimpleNamespace(context={"plugin_options": options, AGENT_RUNS_CONTEXT_KEY: object(), "mode": mode}), messages=[])
    notes = middleware.notes(request)
    assert notes and "Ultracode mode" in notes[0], "the brief did not render"
    assert os.environ["DEER_FLOW_HOME"]
    return notes, tools


def _assemble(mode: str, model_name: str = MODEL_NAME) -> dict:
    """Build the real lead agent and return what it handed ``create_agent``."""
    import deerflow.agents.lead_agent.agent as lead

    captured: dict = {}
    real_create_agent = lead.create_agent

    def capture(**kwargs):
        captured.update(kwargs)
        return real_create_agent(**kwargs)

    original = lead.create_agent
    lead.create_agent = capture
    try:
        lead.assemble_lead_agent({"configurable": {"model_name": model_name, "thread_id": f"critical-{mode}", **MODES[mode]}, "metadata": {}})
    finally:
        lead.create_agent = original
    return captured


def _fresh_request(mode: str, shared_workspace: str = "off", workflow_brief: bool = True) -> ModelRequest:
    """The first model request of a new chat in *mode*, as the context guard receives it.

    ``workflow_brief=False`` leaves the Ultracode brief out but keeps the workflow
    tools: a run whose context carries no workflows options (a CAD design run) gets
    the mode's flags without the brief.
    """
    captured = _assemble(mode)
    system = [captured["system_prompt"]]
    tools = list(captured["tools"])
    for middleware in captured["middleware"]:
        # Plan mode's todo section rides the system message; its tool is bound by the middleware.
        if getattr(middleware, "system_prompt", None) and type(middleware).__name__ == "TodoMiddleware":
            system.append(middleware.system_prompt)
        tools.extend(getattr(middleware, "tools", None) or [])
    if mode in ("ultracode", "double_ultracode"):
        notes, workflow_tools = _workflow_additions(mode, shared_workspace)
        if workflow_brief:
            system.extend(notes)
        tools.extend(workflow_tools)
    # Fork: the CAD module ships installed and enabled (FORK.md §51), so its tool rides every request.
    tools.extend(_cad_tools())
    model = SimpleNamespace(model="qwen3:8b", num_ctx=32_768, num_predict=8_192)
    return ModelRequest(model=model, messages=[HumanMessage("Summarise what you can do for me.")], system_message=SystemMessage(content="\n\n".join(system)), tools=tools, state={})


def _fixed_tokens(request: ModelRequest) -> int:
    """System prompt plus tool schemas in the short form a small window gets."""
    return estimate_request_tokens(request.override(messages=[], tools=[short_tool_schema(tool) for tool in request.tools]))


# deepseek-r1:14b as /api/show and /api/tags describe it: the sync's input when
# it sizes a window from a GPU budget.
SHOW_14B = {
    "model_info": {
        "general.architecture": "qwen2",
        "qwen2.block_count": 48,
        "qwen2.context_length": 131072,
        "qwen2.embedding_length": 5120,
        "qwen2.attention.head_count": 40,
        "qwen2.attention.head_count_kv": 8,
    }
}
WEIGHTS_14B = 8_988_112_040
GIB = 1024**3


def _sync_script():
    spec = importlib.util.spec_from_file_location("sync_ollama_models_fit", REPO_ROOT / "scripts" / "sync-ollama-models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("vram_gib", "num_parallel"),
    [(None, 1), (4, 1), (8, 1), (12, 1), (24, 4)],
    ids=["gpu-unknown", "offloaded-4gib", "offloaded-8gib", "barely-fits-12gib", "four-slots-24gib"],
)
def test_no_window_the_launch_sync_writes_is_smaller_than_this_one(vram_gib, num_parallel):
    """The window every test here measures is the smallest the sync can write.

    Proving the agent fits a 32K entry is worth nothing if the sync writes a
    smaller one. Its GPU sizing did: 4096 for a model that barely fit, 16384
    for one that did not, and less per slot with several slots. With up to
    half the window kept for the reply, none left room for the system prompt.
    """
    sync = _sync_script()
    limit = sync.vram_num_ctx_limit(SHOW_14B, WEIGHTS_14B, vram_gib * GIB, "f16", num_parallel) if vram_gib else None
    window = sync.resolve_num_ctx(131072, cap=sync.effective_num_ctx_cap(None, limit), vram_limit=limit)
    entry = sync.render_entry("local", ["tools"], "http://localhost:11434", window)
    num_ctx = int(re.search(r"num_ctx: (\d+)", entry).group(1))
    num_predict = int(re.search(r"num_predict: (\d+)", entry).group(1))
    prompt = ContextBudget(context_window=num_ctx, reserved_output=num_predict).prompt_tokens
    assert prompt >= BUDGET.prompt_tokens, f"the sync wrote num_ctx {num_ctx} with num_predict {num_predict}: {prompt:,} prompt tokens, under the {BUDGET.prompt_tokens:,} this file proves the agent needs"


@pytest.mark.parametrize("mode", list(MODES))
def test_a_fresh_request_leaves_room_for_the_conversation_on_a_32k_model(stock_config, mode):
    request = _fresh_request(mode)
    fixed = _fixed_tokens(request)
    assert fixed <= FIXED_REQUEST_ALLOWANCE_TOKENS, (
        f"{mode}: the system prompt and tool schemas cost ~{fixed:,} tokens before the conversation, over the "
        f"{FIXED_REQUEST_ALLOWANCE_TOKENS:,} a 32K local model can spare (room for ~{LIMIT:,}). Make the prompt or the tools smaller (FORK.md §47)."
    )

    sent: list[ModelRequest] = []

    def handler(guarded):
        sent.append(guarded)
        return AIMessage(content="ok")

    result = asyncio.run(asyncio.to_thread(ContextWindowGuardMiddleware(app_config=SimpleNamespace(models=[])).wrap_model_call, request, handler))
    assert sent, f"{mode}: the context guard refused a new chat's first message: {getattr(result, 'content', result)}"


def _cad_tools() -> list[dict]:
    """The CAD module's tool as a model sees it, taken from the extension itself (roadmap item 44)."""
    from deerflow_extension_cad import install

    from deerflow.extensions.plugin_tools import _model_facing_schema, plugin_tool_name

    contributed: dict = {}

    class Registry:
        def plugin(self, contribution):
            contributed["plugin"] = contribution
            return True

    install(Registry(), {})
    plugin = contributed["plugin"]
    return [{"type": "function", "function": {"name": plugin_tool_name(plugin.namespace, tool.name), "description": tool.description, "parameters": _model_facing_schema(tool.input_schema)}} for tool in plugin.tools]


@pytest.mark.parametrize("shared_workspace", ["read", "write"])
def test_the_heaviest_mode_fits_with_every_workflows_option_the_example_documents(stock_config, shared_workspace):
    # config.example.yaml offers shared_workspace "read" and "write"; each lengthens the Ultracode brief.
    # With the CAD tool on every request, "read" went 17 tokens over the allowance while the stock check,
    # which only measures the shipped "off", stayed green.
    fixed = _fixed_tokens(_fresh_request("double_ultracode", shared_workspace))
    assert fixed <= FIXED_REQUEST_ALLOWANCE_TOKENS, f"double_ultracode with shared_workspace={shared_workspace}: ~{fixed:,} fixed tokens, over the {FIXED_REQUEST_ALLOWANCE_TOKENS:,} a 32K local model can spare"


@pytest.mark.parametrize("mode", list(MODES))
def test_the_bundled_cad_tool_stays_cheap_on_every_request(stock_config, mode):
    # The module ships installed, so the stock request above carries its tool in every mode
    # and on every model. What it costs is what a 32K model loses of its conversation.
    request = _fresh_request(mode)
    from deerflow.extensions.plugin_tools import plugin_tool_name

    # Exact: the CAD design page's tool (ext_cad_design_...) shares the prefix and is measured below.
    cad = [tool for tool in request.tools if isinstance(tool, dict) and tool.get("function", {}).get("name") == plugin_tool_name("cad", "cad_build")]
    assert len(cad) == 1
    without_cad = request.override(tools=[tool for tool in request.tools if tool not in cad])
    cost = _fixed_tokens(request) - _fixed_tokens(without_cad)
    # The heaviest mode has under 200 tokens to spare on a 32K model, so the tool may not grow.
    assert 0 < cost <= 150, f"cad_build costs ~{cost:,} tokens of every request; keep its description and schema short"


def _cad_design_additions():
    """The CAD design page's tool and its lead middleware, taken from the extension itself.

    The host binds the drafting tool on every request; the middleware removes it
    from every model call that is not a design run, and on a design run adds the
    brief and the version note to the system message (roadmap items 61-64).
    """
    from deerflow_extension_api import AgentBuildContext, AgentScope
    from deerflow_extension_cad_design import install

    from deerflow.extensions.plugin_tools import _model_facing_schema, plugin_tool_name

    contributed: dict = {}

    class Registry:
        def plugin(self, contribution):
            contributed["plugin"] = contribution
            return True

        def middlewares(self, contributor):
            contributed["contributor"] = contributor

        def routers(self, routers):
            pass

    install(Registry(), {"enabled": True, "storage_path": "cad-design/designs.sqlite", "max_source_bytes": 65536})
    plugin = contributed["plugin"]
    tools = [{"type": "function", "function": {"name": plugin_tool_name(plugin.namespace, tool.name), "description": tool.description, "parameters": _model_facing_schema(tool.input_schema)}} for tool in plugin.tools]
    (placed,) = contributed["contributor"].contribute_middlewares(None, AgentBuildContext(scope=AgentScope.LEAD, agent_name=None, model_name=MODEL_NAME, policy=None))
    return tools, placed


def _through(placed, request: ModelRequest, context: dict) -> ModelRequest:
    """What the contribution hands on for *request* on a run with *context*.

    Through the host's isolation wrapper, built the way the host injects it: the
    wrapper, not the middleware, decides what reaches the model.
    """
    from deerflow.extensions.injection import isolate

    diagnostics: list = []
    sent: list[ModelRequest] = []
    isolate(placed, "cad-design", diagnostics.append).wrap_model_call(request.override(runtime=SimpleNamespace(context=context)), lambda guarded: sent.append(guarded) or AIMessage(content="ok"))
    assert not diagnostics, diagnostics
    return sent[0]


@pytest.mark.parametrize("mode", list(MODES))
def test_the_cad_design_page_adds_nothing_outside_a_design_run(stock_config, mode):
    request = _fresh_request(mode)
    tools, placed = _cad_design_additions()
    bound = request.override(tools=[*request.tools, *tools])
    options = {"community.workflows": {"mode": mode}} if mode in ("ultracode", "double_ultracode") else {}
    for context in ({"thread_id": f"critical-{mode}", **MODES[mode]}, {"thread_id": f"critical-{mode}", "plugin_options": options, **MODES[mode]}):
        sent = _through(placed, bound, context)
        assert _fixed_tokens(sent) == _fixed_tokens(request), f"{mode}: the CAD design page costs tokens outside a design run"
    # A design flag the run's own thread does not back is no design run either.
    forged = {"thread_id": f"critical-{mode}", "plugin_options": {"cad-design": {"design_id": "a" * 32, "phase": "draft"}}, **MODES[mode]}
    assert _fixed_tokens(_through(placed, bound, forged)) == _fixed_tokens(request)


@pytest.mark.parametrize("phase", ["draft", "finalize"])
@pytest.mark.parametrize("mode", list(MODES))
def test_a_cad_design_run_fits_in_every_mode(stock_config, mode, phase):
    # A design run's context comes from the page's prompt action: the mode's flags and the
    # cad-design options, never the workflows options, so the Ultracode brief is not on it.
    # The note is at its bound: a long hand edit (cut diff) and a failed render.
    tools, placed = _cad_design_additions()
    store = placed.middleware.store
    thread = f"design-{mode}"
    store.create_design("critical", "a" * 32, "Bracket", thread)
    base = store.add_version("critical", "a" * 32, parent_id=None, source="model", scad="\n".join(f"p{i} = {i}; // [0:1:1000]" for i in range(400)), params={})
    head = store.add_version("critical", "a" * 32, parent_id=base["id"], source="hand", scad="\n".join(f"p{i} = {i + 1}; // [0:1:1000]" for i in range(400)), params={})
    store.set_render("critical", "a" * 32, head["id"], {"ok": False, "partial": False, "error": "x" * 4000, "error_lines": list(range(50)), "bbox_mm": [100.0, 100.0, 100.0]})
    request = _fresh_request(mode, workflow_brief=False)
    bound = request.override(tools=[*request.tools, *tools])
    context = {"thread_id": thread, "plugin_options": {"cad-design": {"design_id": "a" * 32, "head": head["id"], "phase": phase}}, **MODES[mode]}
    sent = _through(placed, bound, context)
    assert "## Design page" in sent.system_message.content, "the design brief did not render"
    fixed = _fixed_tokens(sent)
    assert fixed <= FIXED_REQUEST_ALLOWANCE_TOKENS, f"{mode} {phase}: a CAD design run costs ~{fixed:,} fixed tokens, over the {FIXED_REQUEST_ALLOWANCE_TOKENS:,} a 32K local model can spare"
    if phase == "draft":
        drafting = [tool for tool in sent.tools if isinstance(tool, dict) and tool["function"]["name"] == tools[0]["function"]["name"]]
        cost = _fixed_tokens(request.override(tools=[*request.tools, *drafting])) - _fixed_tokens(request)
        assert 0 < cost <= 150, f"scad_draft costs ~{cost:,} tokens of a design run's every request; keep its description and schema short"


def test_compaction_fires_before_the_guard_would_refuse_a_long_chat(stock_config, monkeypatch):
    """Messages past the trigger are compacted; the guard refuses past LIMIT - fixed.

    The trigger must sit below that in the heaviest mode, or a long text-only
    chat on a 32K model is refused instead of compacted.
    """
    from unittest.mock import MagicMock

    from deerflow.agents.middlewares.summarization_middleware import create_summarization_middleware
    from deerflow.config.app_config import get_app_config

    heaviest = max(_fixed_tokens(_fresh_request(mode)) for mode in ("ultra", "double_ultracode"))
    model = MagicMock(num_ctx=32_768, num_predict=8_192)
    model.with_config.return_value = model
    monkeypatch.setattr("deerflow.agents.middlewares.summarization_middleware.create_chat_model", lambda **kwargs: model)
    trigger = create_summarization_middleware(app_config=get_app_config(), run_model_name=MODEL_NAME).trigger
    clauses = trigger if isinstance(trigger, list) else [trigger]
    token_triggers = [value for kind, value in clauses if kind == "tokens"]
    assert token_triggers, "config.example.yaml no longer compacts on a token count"
    assert max(token_triggers) <= LIMIT - heaviest, f"compaction fires at {max(token_triggers):,} message tokens, but the guard refuses past {LIMIT - heaviest:,}"
    # Sanity: the estimate is the guard's own.
    assert estimate_tokens("a" * 400) == 100


@pytest.mark.parametrize(("model_name", "small"), [(MODEL_NAME, True), (LARGE_MODEL_NAME, False)], ids=["32k", "128k"])
def test_a_small_window_lists_skills_by_name_and_keeps_mcp_schemas_behind_tool_search(stock_config, monkeypatch, model_name, small):
    """Decided from the serving model's window, whatever the config says (FORK.md §47).

    An enabled MCP server binds every schema it has — GitHub's alone is dozens —
    and the full skill catalog is ~3.7K tokens; on a 32K model either can be the
    difference between a chat that starts and one that is refused.
    """
    from langchain_core.tools import StructuredTool

    import deerflow.tools as tools_module
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    mcp_tool = tag_mcp_tool(StructuredTool.from_function(func=lambda name: name, name="github_create_repository", description="Create a GitHub repository."), server_name="github", transport="stdio")
    real_get_available_tools = tools_module.get_available_tools
    monkeypatch.setattr(tools_module, "get_available_tools", lambda *args, **kwargs: [*real_get_available_tools(*args, **kwargs), mcp_tool])

    captured = _assemble("flash", model_name)
    names = {tool.name for tool in captured["tools"]}
    deferred = set().union(*(middleware._deferred for middleware in captured["middleware"] if isinstance(middleware, DeferredToolFilterMiddleware)))

    if small:
        assert "<skill_index>" in captured["system_prompt"] and "<available_skills>" not in captured["system_prompt"]
        assert {"describe_skill", "tool_search"} <= names
        assert "github_create_repository" in deferred, "the MCP schema must wait behind tool_search on a small window"
    else:
        assert "<available_skills>" in captured["system_prompt"]
        assert "tool_search" not in names and not deferred


# ---------------------------------------------------------------------------
# The chat clean-up pass (deerflow.utils.chat_organize)
# ---------------------------------------------------------------------------
#
# Its two one-shot calls bypass ContextWindowGuardMiddleware (they call the model
# directly), so their size limit is built into the prompt builders. These pin
# the worst case a request can carry on the same synced 32K entry: the longest
# folder names the registry allows, the most folders, the longest digest, and
# CJK text, which the estimate prices at ~1.25 tokens a character.

_CJK = "整理对话文件夹分类标题摘要"


def _cjk(length: int, seed: int = 0) -> str:
    text = f"{seed:03d}" + _CJK * (length // len(_CJK) + 1)
    return text[:length]


def _worst_case_conversation(text) -> list:
    messages: list = []
    for index in range(12):
        messages.append(HumanMessage(content=text(2_000, index)))
        messages.append(AIMessage(content=text(2_000, index + 100)))
    return messages


@pytest.mark.parametrize("script", ["ascii", "cjk"])
@pytest.mark.parametrize("mode", ["targets", "auto"])
def test_the_organize_suggest_prompt_fits_a_32k_model_at_its_worst(script, mode):
    from deerflow.config.user_ui_state import MAX_CHAT_FOLDERS, MAX_FOLDER_NAME_CHARS
    from deerflow.utils import chat_organize as organize

    text = _cjk if script == "cjk" else (lambda length, seed=0: (f"{seed:03d} " + "lorem ipsum " * length)[:length])
    digest = organize.build_conversation_digest(
        _worst_case_conversation(text),
        summary_text=text(5_000, 999),
        current_title=text(500, 998),
        max_chars=organize.digest_char_budget(BUDGET),
    )
    folders = [organize.FolderChoice(id=f"f{index}", name=text(MAX_FOLDER_NAME_CHARS, index)) for index in range(MAX_CHAT_FOLDERS)]

    system, user = organize.build_suggest_messages(
        digest,
        mode=mode,
        rename=True,
        max_words=20,
        targets=folders if mode == "targets" else (),
        existing=folders if mode == "auto" else (),
        budget=BUDGET,
    )

    tokens = estimate_tokens(system) + estimate_tokens(user)
    assert tokens <= LIMIT, f"{script}/{mode}: the organize prompt costs ~{tokens:,} tokens, over the {LIMIT:,} a 32K model takes"
    assert digest.text in user, f"{script}/{mode}: the digest had to be cut to fit; a 32K model should read all of it"


@pytest.mark.parametrize("script", ["ascii", "cjk"])
def test_the_organize_consolidation_prompt_fits_a_32k_model_at_its_worst(script):
    from deerflow.config.user_ui_state import MAX_CHAT_FOLDERS, MAX_FOLDER_NAME_CHARS
    from deerflow.utils import chat_organize as organize

    text = _cjk if script == "cjk" else (lambda length, seed=0: (f"{seed:03d} " + "lorem ipsum " * length)[:length])
    items = [organize.ConsolidationItem(thread_id=f"t{index}", category=text(organize.MAX_CATEGORY_CHARS, index), title=text(1_000, index), summary=text(1_000, index)) for index in range(organize.MAX_CONSOLIDATE_ITEMS)]
    groups, _ = organize.group_categories(items, [])
    assert len(groups) == organize.MAX_CONSOLIDATE_ITEMS, "every label must be distinct for the worst case"
    existing = [organize.FolderChoice(id=f"f{index}", name=text(MAX_FOLDER_NAME_CHARS, 500 + index)) for index in range(MAX_CHAT_FOLDERS)]

    prompt = organize.build_consolidate_messages(groups, existing, new_folder_cap=organize.MAX_NEW_FOLDERS_LIMIT, budget=BUDGET)

    tokens = estimate_tokens(prompt.system) + estimate_tokens(prompt.user)
    assert tokens <= LIMIT, f"{script}: the consolidation prompt costs ~{tokens:,} tokens, over the {LIMIT:,} a 32K model takes"
    assert f"{organize.MAX_CONSOLIDATE_ITEMS}. " in prompt.user, "every label must be in the prompt"
    if script == "ascii":
        assert "e.g." in prompt.user, "ASCII examples fit a 32K model and should not have been dropped"
