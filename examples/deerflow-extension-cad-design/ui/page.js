import { prepareInWorker } from "../../deerflow-extension-cad-preview/ui/worker-client.js";

import { createEditor } from "./editor.js";
import {
  appendOnly,
  isDraftSource,
  isEngineFailure,
  shouldRepair,
  shouldReport,
  shouldRetrySave,
} from "./outcomes.js";
import { parseParameters, withValues } from "./params.js";
import {
  assistantMessages,
  createRunState,
  foldRunEvent,
  isScadDraft,
  scadCalls,
} from "./run-stream.js";
import { LIMITS_MS, createScadRunner } from "./scad-client.js";
import { capFn, completePrefix } from "./scad-text.js";
import { STYLE } from "./style.js";
import { strings } from "./text.js";
import { timeline } from "./versions.js";
import { VIEWS, createViewer } from "./viewer.js";
import { WASM_INFO } from "./wasm-info.js";
import { loadWasm } from "./wasm-loader.js";

const LIVE_FN_CAP = 24;
const LIVE_DEBOUNCE_MS = 300;
const EDIT_DEBOUNCE_MS = 500;
const SLIDER_DEBOUNCE_MS = 80;
// Arrow keys on a slider fire `change` per step: save once the keys rest.
const SLIDER_COMMIT_MS = 600;
const MODEL_RETRY_MS = 1000;
const MODEL_RETRIES = 30;
const LEFT_DEFAULT = 38;
const POLL_MS = 2000;
const NARROW_PX = 768;
const ACTIVE = new Set(["pending", "running"]);
const ID = /^[A-Za-z0-9_-]{1,128}$/;

const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const button = (label, onClick, className) => {
  const node = element("button", className, label);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
};
const storage = {
  get(key) {
    try {
      return window.localStorage.getItem(`cad-design:${key}`);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(`cad-design:${key}`, value);
    } catch {
      /* Private mode: preferences are not kept. */
    }
  },
};

/** Mount the Designs page into `root` (inside the host's shadow root); returns dispose(). */
export function mountPage(root, context) {
  const text = strings(context.locale);
  const { signal } = context;
  const number = new Intl.NumberFormat(context.locale, {
    maximumFractionDigits: 2,
  });
  const when = new Intl.DateTimeFormat(context.locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const formatTime = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : when.format(date);
  };
  const triple = (values) => values.map((v) => number.format(v)).join(" × ");

  const S = {
    trash: false,
    design: null,
    versions: [],
    headId: null,
    source: "",
    savedSource: "",
    messages: [],
    run: null,
    saving: null,
    shown: null,
    lastGood: null,
    stl: null,
    finalKey: null,
    compare: "both",
    phone: "preview",
    narrow: false,
    note: null,
  };
  // Created with the first design view; the viewer is released when it closes.
  let viewer = null;
  let editor = null;
  let editTimer = 0;
  const timers = new Set();
  const later = (fn, ms) => {
    const id = setTimeout(() => {
      timers.delete(id);
      fn();
    }, ms);
    timers.add(id);
    return id;
  };
  const cancel = (id) => {
    clearTimeout(id);
    timers.delete(id);
  };

  // -- engine ------------------------------------------------------------------

  let wasmBytes = null;
  const getWasm = () => {
    wasmBytes ??= loadWasm(WASM_INFO, { base: import.meta.url, signal }).catch(
      (error) => {
        wasmBytes = null;
        throw error;
      },
    );
    return wasmBytes;
  };
  let runner = null;
  const engine = () => (runner ??= createScadRunner({ getWasm }));

  const errorText = (code) => {
    if (code === "timeout") return null;
    if (code === "load:integrity") return text.errors.integrity;
    if (typeof code === "string" && code.startsWith("load:"))
      return text.errors.load;
    if (code === "worker") return text.errors.worker;
    if (code === "wasm") return text.errors.wasm;
    return code;
  };

  /** Render OpenSCAD source and prepare the mesh; resolves an outcome, never rejects unless the page closed. */
  async function renderSource(code, mode) {
    const result = await engine().render(
      mode === "live" ? capFn(code, LIVE_FN_CAP) : code,
      { mode },
    );
    if (result.superseded) return { superseded: true };
    if (!result.ok) {
      const limit = Math.round((LIMITS_MS[mode] ?? LIMITS_MS.final) / 1000);
      return {
        ok: false,
        error:
          result.error === "timeout"
            ? text.errors.timeout(limit)
            : errorText(result.error),
        errorLines: result.errorLines,
        warnings: result.warnings,
        ms: result.ms,
        engine: isEngineFailure(result.error),
      };
    }
    return {
      ok: true,
      model: result.model,
      metrics: result.metrics,
      stl: result.stl,
      errorLines: result.errorLines,
      warnings: result.warnings,
      ms: result.ms,
    };
  }

  const record = (outcome) =>
    outcome.ok
      ? {
          ok: true,
          partial: false,
          bbox_mm: outcome.metrics.bbox_mm,
          bbox_min_mm: outcome.metrics.bbox_min_mm,
          bbox_max_mm: outcome.metrics.bbox_max_mm,
          volume_mm3: outcome.metrics.volume_mm3,
          manifold: outcome.metrics.manifold,
          triangles: outcome.metrics.triangles,
          error_lines: (outcome.errorLines ?? []).slice(0, 50),
          ms: Math.max(0, Math.round(outcome.ms ?? 0)),
        }
      : {
          ok: false,
          partial: false,
          error: String(outcome.error ?? "render failed").slice(0, 4000),
          error_lines: (outcome.errorLines ?? []).slice(0, 50),
          ms: Math.max(0, Math.round(outcome.ms ?? 0)),
        };

  let displaySeq = 0;
  /**
   * Render and show. Only the newest request updates the view; a failure keeps
   * the last good mesh on screen. Resolves the outcome.
   */
  async function show(code, mode, { partial = false } = {}) {
    const seq = ++displaySeq;
    setOverlay(
      partial ? text.partial : wasmBytes ? text.rendering : text.loadingEngine,
    );
    let outcome;
    try {
      outcome = await renderSource(code, mode);
    } catch {
      return { ok: false, error: "closed" };
    }
    if (signal.aborted || outcome.superseded) return outcome;
    if (seq !== displaySeq) return outcome;
    if (outcome.ok) {
      S.shown = {
        partial,
        metrics: outcome.metrics,
        warnings: outcome.warnings,
      };
      S.lastGood = S.shown;
      if (!partial && outcome.stl) S.stl = outcome.stl;
      stlButton.disabled = !S.stl;
      drawDraft(outcome.model, partial);
      editor?.markErrors(partial ? [] : outcome.errorLines);
      setOverlay(partial ? text.partial : null);
      if (S.narrow && S.phone !== "preview") phoneDot.hidden = false;
    } else {
      S.shown = {
        error: outcome.error,
        errorLines: outcome.errorLines,
        partial,
      };
      if (!partial) editor?.markErrors(outcome.errorLines);
      // A partial prefix that fails is expected mid-stream: keep quiet and keep the last mesh.
      setOverlay(
        partial
          ? text.partial
          : `${text.renderFailed}. ${viewer?.hasDraft() ? text.lastGood : ""}`,
        !partial,
      );
    }
    renderInfo();
    renderErrors();
    return outcome;
  }

  /** A viewer failure (no WebGL) must not keep a render from being reported. */
  function drawDraft(model, partial) {
    try {
      viewerReady()?.setDraft(model, { partial });
    } catch {
      setOverlay(text.errors.webgl, true);
    }
  }

  // -- shell -------------------------------------------------------------------

  const style = element("style");
  style.textContent = STYLE;
  const app = element("div", "app");
  root.replaceChildren(style, app);

  const listView = element("div", "design");
  const listBar = element("header", "bar");
  const listTitle = element("h1", "", text.designs);
  const trashToggle = button(text.trash, () => {
    S.trash = !S.trash;
    trashToggle.setAttribute("aria-pressed", String(S.trash));
    loadList();
  });
  trashToggle.setAttribute("aria-pressed", "false");
  const newButton = button(text.newDesign, () => createDesign(), "primary");
  listBar.append(listTitle, element("span", "grow"), trashToggle, newButton);
  const listNotice = element("div", "notice");
  listNotice.hidden = true;
  listNotice.setAttribute("role", "status");
  const list = element("ul", "list");
  listView.append(listBar, listNotice, list);

  const designView = element("div", "design");
  designView.hidden = true;
  const designBar = element("header", "bar");
  const back = button(`← ${text.backToDesigns}`, () => closeDesign());
  const title = element("h1");
  const renameButton = button(text.rename, () => renameDesign(S.design, title));
  const runStatus = element("span", "muted");
  runStatus.setAttribute("role", "status");
  const finalizeButton = button(text.finalize, () => finalize(), "primary");
  finalizeButton.title = text.finalizeHint;
  designBar.append(
    back,
    title,
    renameButton,
    element("span", "grow"),
    runStatus,
    finalizeButton,
  );
  const designNotice = element("div", "notice");
  designNotice.hidden = true;
  designNotice.setAttribute("role", "status");

  const phoneTabs = element("nav", "phone-tabs");
  phoneTabs.setAttribute("role", "tablist");
  const phoneButtons = {};
  for (const key of ["prompt", "preview", "code"]) {
    const node = button(text.tabs[key], () => setPhone(key));
    node.setAttribute("role", "tab");
    phoneButtons[key] = node;
    phoneTabs.append(node);
  }
  const phoneDot = element("span", "dot");
  phoneDot.hidden = true;
  phoneButtons.preview.append(phoneDot);

  const split = element("div", "split");
  const chat = element("section", "chat");
  chat.setAttribute("aria-label", text.conversation);
  const messages = element("div", "messages");
  messages.setAttribute("role", "log");
  messages.setAttribute("aria-live", "polite");
  // History is appended to, never rebuilt while it only grows, so assistive
  // technology announces new turns once; the streaming turn below it is
  // redrawn per frame under aria-busy and announced when the run ends.
  const historyBox = element("div", "history");
  const liveBox = element("div", "live");
  messages.append(historyBox, liveBox);
  let shownIds = [];
  const composer = element("form", "composer");
  const promptBox = element("textarea");
  promptBox.placeholder = text.promptPlaceholder;
  promptBox.setAttribute("aria-label", text.promptPlaceholder);
  promptBox.maxLength = 8000;
  const modelSelect = element("select");
  modelSelect.setAttribute("aria-label", text.model);
  const thinkingLabel = element("label");
  const thinking = element("input");
  thinking.type = "checkbox";
  thinking.checked = storage.get("thinking") === "1";
  thinking.addEventListener("change", () =>
    storage.set("thinking", thinking.checked ? "1" : "0"),
  );
  thinkingLabel.append(thinking, ` ${text.thinking}`);
  const stopButton = button(text.stop, () => stopRun());
  stopButton.hidden = true;
  const sendButton = element("button", "primary", text.send);
  sendButton.type = "submit";
  const composerRow = element("div", "row");
  composerRow.append(
    modelSelect,
    thinkingLabel,
    element("span", "grow"),
    stopButton,
    sendButton,
  );
  composer.append(promptBox, composerRow);
  chat.append(messages, composer);

  const divider = element("button", "divider");
  divider.type = "button";
  divider.setAttribute("role", "separator");
  divider.setAttribute("aria-orientation", "vertical");
  divider.setAttribute("aria-label", text.resize);
  divider.setAttribute("aria-valuemin", "20");
  divider.setAttribute("aria-valuemax", "75");

  const work = element("section", "work");
  work.dataset.tab = "preview";
  const tabs = element("div", "tabs");
  tabs.setAttribute("role", "tablist");
  const tabButtons = {};
  for (const key of ["preview", "code", "parameters", "versions"]) {
    const node = button(text.tabs[key], () => setTab(key));
    node.setAttribute("role", "tab");
    tabButtons[key] = node;
    tabs.append(node);
  }

  // Preview panel
  const previewPanel = element("div", "panel preview");
  const toolbar = element("div", "toolbar");
  const viewButton = (label, direction) => {
    const node = button(label, () => viewer?.fit(direction));
    node.setAttribute("aria-label", text.viewLabel(label));
    return node;
  };
  const compareButtons = {};
  const compareGroup = element("span");
  compareGroup.hidden = true;
  for (const key of ["draft", "final", "both"]) {
    compareButtons[key] = button(text.compare[key], () => setCompare(key));
    compareGroup.append(compareButtons[key]);
  }
  // The draft as rendered, for a slicer or another CAD tool.
  const stlButton = button(text.downloadStl, () => {
    if (!S.stl) return;
    const url = URL.createObjectURL(new Blob([S.stl], { type: "model/stl" }));
    const link = element("a");
    link.href = url;
    link.download = `${(S.design?.title || "design").replace(/[^\p{L}\p{N}._-]+/gu, "-").slice(0, 80)}.stl`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  stlButton.disabled = true;
  toolbar.append(
    button(text.fit, () => viewer?.fit()),
    viewButton(text.top, VIEWS.top),
    viewButton(text.front, VIEWS.front),
    viewButton(text.iso, VIEWS.iso),
    stlButton,
    element("span", "grow"),
    compareGroup,
  );
  const viewport = element("div", "viewport");
  const placeholder = element("div", "placeholder", text.noModel);
  const overlay = element("div", "overlay");
  overlay.hidden = true;
  overlay.setAttribute("role", "status");
  viewport.append(placeholder, overlay);
  const info = element("div", "info");
  const finalBox = element("div", "final");
  finalBox.hidden = true;
  previewPanel.append(toolbar, viewport, info, finalBox);

  // Code panel
  const codePanel = element("div", "panel code");
  const held = element("div", "held", text.held);
  held.hidden = true;
  const editorHost = element("div", "editor");
  const errors = element("div", "errors");
  errors.hidden = true;
  const codeBar = element("div", "codebar");
  const saveState = element("span", "muted");
  const saveButton = button(text.save, () => saveEdits());
  codeBar.append(
    saveState,
    element("span", "grow"),
    element("span", "muted", text.saveHint),
    saveButton,
  );
  codePanel.append(held, editorHost, errors, codeBar);

  // Parameters and versions panels
  const paramsPanel = element("div", "panel parameters");
  const paramsList = element("div", "params");
  paramsPanel.append(paramsList);
  const versionsPanel = element("div", "panel versions");
  const versionsList = element("ol");
  versionsPanel.append(versionsList);

  work.append(tabs, previewPanel, codePanel, paramsPanel, versionsPanel);
  split.append(chat, divider, work);
  designView.append(designBar, designNotice, phoneTabs, split);
  app.append(listView, designView);

  const storedLeft = Number(storage.get("left"));
  const leftWidth =
    storedLeft >= 20 && storedLeft <= 75 ? storedLeft : LEFT_DEFAULT;
  if (leftWidth !== LEFT_DEFAULT)
    split.style.setProperty("--left", `${leftWidth}%`);
  divider.setAttribute("aria-valuenow", String(Math.round(leftWidth)));

  // -- small view helpers --------------------------------------------------------

  const setNotice = (node, message, kind = "error") => {
    node.hidden = !message;
    node.className = kind === "info" ? "notice info" : "notice";
    node.textContent = message ?? "";
  };
  const busy = (error) => /\(409\)/.test(String(error?.message ?? ""));
  const call = async (action, payload) => {
    const result = await context.callBackend(action, payload);
    if (signal.aborted) throw new DOMException("closed", "AbortError");
    return result;
  };
  const failNotice = (node, error) => {
    if (signal.aborted) return;
    setNotice(node, busy(error) ? text.errors.busy : text.errors.action);
  };

  function setOverlay(message, isError = false) {
    overlay.hidden = !message;
    overlay.textContent = message ?? "";
    overlay.classList.toggle("error", isError);
  }

  function setTab(key) {
    work.dataset.tab = key;
    for (const [name, node] of Object.entries(tabButtons))
      node.setAttribute("aria-selected", String(name === key));
    if (key === "preview") viewer?.resize();
  }
  function setPhone(key) {
    S.phone = key;
    app.dataset.phone = key;
    for (const [name, node] of Object.entries(phoneButtons))
      node.setAttribute("aria-selected", String(name === key));
    if (key === "preview") phoneDot.hidden = true;
    if (key !== "prompt") setTab(key);
    if (S.finalKey) renderFinal();
  }
  setTab("preview");
  setPhone("preview");

  // -- viewer and editor (created with the design view, released with it) --------

  function viewerReady() {
    if (viewer) return viewer;
    try {
      viewer = createViewer(viewport, {
        label: text.viewport,
        onLost: () => setOverlay(text.errors.webgl, true),
      });
    } catch {
      setOverlay(text.errors.webgl, true);
      return null;
    }
    return viewer;
  }

  function ensureEditor() {
    if (editor) return editor;
    editor = createEditor(editorHost, {
      doc: S.source,
      root: root.getRootNode(),
      label: text.tabs.code,
      onChange(value) {
        if (S.run) return;
        S.source = value;
        renderSaveState();
        cancel(editTimer);
        editTimer = later(() => {
          if (S.source.trim()) show(S.source, "live");
          renderParams();
        }, EDIT_DEBOUNCE_MS);
      },
      onSave: () => saveEdits(),
    });
    return editor;
  }

  function renderSaveState() {
    const dirty = S.source !== S.savedSource;
    saveState.textContent = dirty ? text.unsaved : S.design ? text.saved : "";
    saveButton.disabled = !dirty || !!S.run || !!S.saving;
  }

  function renderInfo() {
    info.replaceChildren();
    const shown = S.shown?.metrics ? S.shown : S.lastGood;
    placeholder.hidden = !!viewer?.hasDraft();
    if (!shown?.metrics) return;
    const m = shown.metrics;
    info.append(
      element("span", "", text.size(...m.bbox_mm.map((v) => number.format(v)))),
      element("span", "", text.volume(number.format(m.volume_mm3))),
      element("span", m.manifold ? "" : "error", text.manifold(m.manifold)),
    );
    if (shown.partial) info.append(element("span", "muted", text.partial));
  }

  function renderErrors() {
    const shown = S.shown;
    errors.replaceChildren();
    errors.hidden = !shown?.error || shown.partial;
    if (errors.hidden) return;
    errors.append(element("div", "", shown.error));
    for (const line of shown.errorLines ?? [])
      errors.append(
        button(text.line(line), () => editor?.goToLine(line), "link"),
      );
  }

  // -- divider and width ----------------------------------------------------------

  const setLeft = (percent) => {
    const clamped = Math.min(75, Math.max(20, percent));
    split.style.setProperty("--left", `${clamped}%`);
    divider.setAttribute("aria-valuenow", String(Math.round(clamped)));
    storage.set("left", String(Math.round(clamped)));
    viewer?.resize();
  };
  divider.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    divider.setPointerCapture(event.pointerId);
    const move = (moved) => {
      const rect = split.getBoundingClientRect();
      if (rect.width > 0)
        setLeft(((moved.clientX - rect.left) / rect.width) * 100);
    };
    const up = () => {
      divider.removeEventListener("pointermove", move);
      divider.removeEventListener("pointerup", up);
      divider.removeEventListener("pointercancel", up);
    };
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", up);
    divider.addEventListener("pointercancel", up);
  });
  divider.addEventListener("keydown", (event) => {
    const current =
      Number(divider.getAttribute("aria-valuenow")) || LEFT_DEFAULT;
    if (event.key === "ArrowLeft") setLeft(current - 2);
    else if (event.key === "ArrowRight") setLeft(current + 2);
    else return;
    event.preventDefault();
  });

  const widthObserver = new ResizeObserver(() => {
    const narrow = app.clientWidth > 0 && app.clientWidth <= NARROW_PX;
    if (narrow === S.narrow) return;
    S.narrow = narrow;
    app.classList.toggle("narrow", narrow);
    setPhone(narrow ? S.phone : "preview");
    if (!narrow) setTab(work.dataset.tab === "code" ? "code" : "preview");
    if (S.finalKey) renderFinal();
  });
  widthObserver.observe(app);

  // -- models -----------------------------------------------------------------------

  function renderModels() {
    const models = context.models;
    // The user's last pick on this page, else the host's current model.
    const chosen = storage.get("model") ?? models?.defaultName ?? "";
    modelSelect.replaceChildren(new Option(text.defaultModel, ""));
    for (const model of models?.list ?? []) {
      if (typeof model?.name !== "string") continue;
      modelSelect.append(
        new Option(model.display_name || model.name, model.name),
      );
    }
    const names = new Set([...modelSelect.options].map((o) => o.value));
    modelSelect.value = names.has(chosen)
      ? chosen
      : names.has(models?.defaultName ?? "")
        ? models.defaultName
        : "";
    if (!modelSelect.value) modelSelect.value = "";
    modelSelect.hidden = modelSelect.options.length <= 1;
    // A hidden select cannot take focus, so a list that had not loaded yet is
    // looked up again here rather than on focus.
    cancel(modelTimer);
    if (modelSelect.hidden && S.design && modelTries < MODEL_RETRIES) {
      modelTries += 1;
      modelTimer = later(renderModels, MODEL_RETRY_MS);
    }
  }
  let modelTimer = 0;
  let modelTries = 0;
  promptBox.addEventListener("focus", () => {
    if (modelSelect.hidden) renderModels();
  });
  modelSelect.addEventListener("change", () =>
    storage.set("model", modelSelect.value),
  );
  modelSelect.addEventListener("focus", renderModels);
  const runOptions = () => ({
    ...(modelSelect.value ? { model_name: modelSelect.value } : {}),
    mode: thinking.checked ? "thinking" : "flash",
  });

  // -- list view ---------------------------------------------------------------------

  async function loadList() {
    setNotice(listNotice, null);
    list.replaceChildren(element("li", "empty", text.loading));
    let designs;
    try {
      ({ designs } = await call("list_designs", { trash: S.trash }));
    } catch (error) {
      list.replaceChildren();
      failNotice(listNotice, error);
      return;
    }
    list.replaceChildren();
    if (!Array.isArray(designs) || !designs.length) {
      list.append(
        element("li", "empty", S.trash ? text.emptyTrash : text.emptyList),
      );
      return;
    }
    for (const design of designs) {
      if (!design || !ID.test(design.id ?? "")) continue;
      const card = element("li", "card");
      const name = element("span", "name", design.title || text.untitled);
      const meta = element(
        "span",
        "meta",
        `${text.versionCount(design.versions ?? 0)} · ${formatTime(design.deleted_at ?? design.updated_at)}`,
      );
      const actions = element("div", "actions");
      if (S.trash) {
        card.append(name, meta);
        actions.append(
          button(text.restore, () => designAction("restore_design", design)),
          button(text.purge, () => {
            if (
              window.confirm(text.confirmPurge(design.title || text.untitled))
            )
              designAction("purge_design", design);
          }),
        );
      } else {
        const open = element("button", "open");
        open.type = "button";
        open.append(name, meta);
        open.addEventListener("click", () => openDesign(design.id));
        card.append(open);
        actions.append(
          button(text.rename, () => renameDesign(design, name)),
          button(text.delete, () => designAction("delete_design", design)),
        );
      }
      card.append(actions);
      list.append(card);
    }
  }

  async function designAction(action, design) {
    try {
      await call(action, { design_id: design.id });
    } catch (error) {
      failNotice(listNotice, error);
      return;
    }
    loadList();
  }

  /** Swap a title for an input; Enter or leaving saves, Escape cancels. */
  function renameDesign(design, label) {
    if (!design || label.querySelector("input")) return;
    const previous = label.textContent;
    const input = element("input");
    input.type = "text";
    input.value = design.title || "";
    input.maxLength = 200;
    input.setAttribute("aria-label", text.renamePrompt);
    label.replaceChildren(input);
    input.focus();
    input.select();
    let done = false;
    const finish = async (commit) => {
      if (done) return;
      done = true;
      const value = input.value.trim();
      label.textContent = commit && value ? value : previous;
      if (!commit || !value || value === design.title) return;
      try {
        const { design: updated } = await call("rename_design", {
          design_id: design.id,
          title: value,
        });
        design.title = updated?.title ?? value;
        label.textContent = design.title;
      } catch (error) {
        label.textContent = previous;
        failNotice(S.design ? designNotice : listNotice, error);
      }
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") finish(true);
      else if (event.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
  }

  async function createDesign() {
    newButton.disabled = true;
    try {
      const { design } = await call("create_design", {});
      if (design?.id) await openDesign(design.id);
    } catch (error) {
      failNotice(listNotice, error);
    } finally {
      newButton.disabled = false;
    }
  }

  // -- design view ---------------------------------------------------------------------

  const headVersion = () => S.versions.find((v) => v.id === S.headId) ?? null;

  async function openDesign(designId) {
    setNotice(listNotice, null);
    let loaded;
    try {
      loaded = await call("get_design", { design_id: designId });
    } catch (error) {
      failNotice(listNotice, error);
      return;
    }
    listView.hidden = true;
    designView.hidden = false;
    setNotice(designNotice, null);
    S.design = loaded.design;
    S.versions = Array.isArray(loaded.versions) ? loaded.versions : [];
    S.headId = S.design.head_version_id ?? null;
    S.shown = S.lastGood = S.stl = null;
    stlButton.disabled = true;
    S.finalKey = null;
    S.note = null;
    S.messages = [];
    title.textContent = S.design.title || text.untitled;
    viewer?.reset();
    modelTries = 0;
    renderModels();
    const head = headVersion();
    let scad = head?.scad ?? "";
    if (head && head.scad == null)
      scad = (await fetchVersion(head.id))?.scad ?? "";
    setSource(scad);
    ensureEditor().setDoc(scad);
    renderAll();
    loadMessages();
    if (head && scad.trim()) renderVersion(head, scad);
    resumeRun();
  }

  function closeDesign() {
    stopFollowing();
    S.design = null;
    designView.hidden = true;
    listView.hidden = false;
    viewer?.dispose();
    viewer = null;
    loadList();
  }

  function setSource(scad) {
    S.source = scad;
    S.savedSource = scad;
    editor?.setDoc(scad);
    renderSaveState();
    renderParams();
  }

  async function fetchVersion(versionId) {
    try {
      const { version } = await call("get_version", {
        design_id: S.design.id,
        version_id: versionId,
      });
      return version;
    } catch (error) {
      failNotice(designNotice, error);
      return null;
    }
  }

  /** Render a stored version; report the result when none is stored yet. */
  async function renderVersion(version, scad) {
    const outcome = await show(scad, "final");
    if (shouldReport(version, outcome)) await report(version.id, outcome);
    return outcome;
  }

  async function report(versionId, outcome) {
    try {
      const { version } = await call("report_render", {
        design_id: S.design.id,
        version_id: versionId,
        render: record(outcome),
      });
      upsertVersion(version);
    } catch (error) {
      failNotice(designNotice, error);
    }
  }

  function upsertVersion(version) {
    if (!version || typeof version.id !== "string") return;
    const index = S.versions.findIndex((v) => v.id === version.id);
    if (index >= 0) S.versions[index] = { ...S.versions[index], ...version };
    else S.versions.push(version);
    renderVersions();
    renderFinalizeButton();
  }

  async function reloadDesign() {
    if (!S.design) return;
    try {
      const loaded = await call("get_design", { design_id: S.design.id });
      S.design = loaded.design;
      S.versions = Array.isArray(loaded.versions) ? loaded.versions : [];
      S.headId = S.design.head_version_id ?? null;
      title.textContent = S.design.title || text.untitled;
    } catch (error) {
      failNotice(designNotice, error);
    }
    renderAll();
  }

  function renderAll() {
    renderVersions();
    renderFinalizeButton();
    renderFinal();
    renderRunState();
    renderInfo();
    renderMessages();
  }

  // -- parameters ---------------------------------------------------------------------

  let sliderTimer = 0;
  let commitTimer = 0;
  const paramValues = (scad) =>
    Object.fromEntries(
      parseParameters(scad)
        .slice(0, 100)
        .map((p) => [p.name, p.value]),
    );

  function renderParams() {
    if (
      paramsList.contains(root.getRootNode().activeElement) &&
      paramsList.dataset.source === S.source
    )
      return;
    paramsList.dataset.source = S.source;
    paramsList.replaceChildren();
    const params = parseParameters(S.source);
    if (!params.length) {
      paramsList.append(element("p", "muted", text.noParams));
      return;
    }
    let pending = S.source;
    for (const param of params) {
      const row = element("div", "param");
      const label = element("label");
      const name = element("span", "", param.name);
      const value = element(
        "span",
        "",
        param.kind === "boolean" ? "" : number.format(param.value),
      );
      const input = element("input");
      input.disabled = !!S.run;
      input.setAttribute("aria-label", param.name);
      if (param.kind === "boolean") {
        input.type = "checkbox";
        input.checked = param.value;
        label.append(name, input);
        row.append(label);
        input.addEventListener("change", () =>
          commitParam(withValues(S.source, { [param.name]: input.checked })),
        );
      } else {
        input.type = "range";
        input.min = String(param.min);
        input.max = String(param.max);
        input.step = String(param.step);
        input.value = String(param.value);
        label.append(name, value);
        const range = element(
          "span",
          "range",
          `${number.format(param.min)} – ${number.format(param.max)}${param.derived ? ` (${text.derived})` : ""}`,
        );
        row.append(label, input, range);
        // Dragging re-renders locally only; releasing saves one version.
        input.addEventListener("input", () => {
          value.textContent = number.format(Number(input.value));
          pending = withValues(S.source, { [param.name]: Number(input.value) });
          cancel(sliderTimer);
          sliderTimer = later(() => show(pending, "live"), SLIDER_DEBOUNCE_MS);
        });
        const commit = () => {
          cancel(sliderTimer);
          cancel(commitTimer);
          commitTimer = 0;
          commitParam(
            withValues(S.source, { [param.name]: Number(input.value) }),
          );
        };
        input.addEventListener("change", () => {
          cancel(commitTimer);
          commitTimer = later(commit, SLIDER_COMMIT_MS);
        });
        input.addEventListener("blur", () => {
          if (commitTimer) commit();
        });
      }
      paramsList.append(row);
    }
  }

  async function commitParam(scad) {
    if (S.run || scad === S.savedSource) return;
    S.source = scad;
    // The focused slider already shows this value: keep its row (and the focus).
    paramsList.dataset.source = scad;
    editor?.setDoc(scad);
    await saveVersion("slider");
    renderParams();
  }

  // -- saving -----------------------------------------------------------------------------

  async function saveEdits() {
    if (S.run || S.source === S.savedSource || !S.design) return;
    await saveVersion("hand");
  }

  /** Save the current source as a version (hand or slider), then render and report it. */
  function saveVersion(source) {
    if (S.saving) return S.saving;
    const scad = S.source;
    S.saving = (async () => {
      renderSaveState();
      let version;
      try {
        ({ version } = await call("save_version", {
          design_id: S.design.id,
          parent_id: S.headId,
          scad,
          params: paramValues(scad),
          source,
        }));
      } catch (error) {
        failNotice(designNotice, error);
        return;
      }
      S.savedSource = scad;
      S.headId = version.id;
      upsertVersion(version);
      const outcome = await show(scad, "final");
      if (shouldReport(version, outcome)) await report(version.id, outcome);
    })().finally(() => {
      S.saving = null;
      renderSaveState();
      // Edits made while saving are saved next; a refused save is not retried
      // with the same text (it would loop against the Gateway).
      if (
        S.source !== S.savedSource &&
        shouldRetrySave({ now: S.source, attempted: scad, running: !!S.run })
      )
        saveEdits();
    });
    return S.saving;
  }

  // -- versions ----------------------------------------------------------------------------

  function renderVersions() {
    versionsList.replaceChildren();
    const rows = timeline(S.versions, S.headId);
    if (!rows.length) {
      versionsList.append(element("li", "muted", text.versionsEmpty));
      return;
    }
    for (const row of rows) {
      const item = element("li");
      const node = button("", () => selectVersion(row.id));
      node.disabled = !!S.run;
      node.setAttribute("aria-current", row.isHead ? "true" : "false");
      node.setAttribute("aria-pressed", String(row.isHead));
      node.append(
        element("span", "seq", `v${row.seq}`),
        element("span", "", text.source[row.source] ?? row.source),
        element(
          "span",
          row.status === "error" ? "error" : "muted",
          text.status[row.status],
        ),
        element(
          "span",
          "muted",
          row.createdAt ? formatTime(row.createdAt) : "",
        ),
      );
      if (row.isHead) node.append(element("span", "chip", text.head));
      if (row.final?.status)
        node.append(
          element(
            "span",
            "chip",
            text.final[row.final.status] ?? row.final.status,
          ),
        );
      if (row.branchFrom !== null)
        node.append(element("span", "branch", text.branchFrom(row.branchFrom)));
      if (row.error) node.title = row.error;
      item.append(node);
      versionsList.append(item);
    }
  }

  async function selectVersion(versionId) {
    if (S.run || !S.design) return;
    if (S.source !== S.savedSource) await saveEdits();
    let version = S.versions.find((v) => v.id === versionId);
    if (!version) return;
    let scad = version.scad;
    if (scad == null) scad = (await fetchVersion(versionId))?.scad ?? "";
    try {
      const { design } = await call("set_head", {
        design_id: S.design.id,
        version_id: versionId,
      });
      if (design) S.design = design;
    } catch (error) {
      failNotice(designNotice, error);
      return;
    }
    S.headId = versionId;
    setSource(scad);
    renderVersions();
    renderFinalizeButton();
    renderFinal();
    if (S.narrow) setPhone("preview");
    else setTab("preview");
    version = S.versions.find((v) => v.id === versionId) ?? version;
    if (scad.trim()) renderVersion(version, scad);
  }

  // -- finalize ------------------------------------------------------------------------------

  function renderFinalizeButton() {
    const head = headVersion();
    const ready = !!head?.render?.ok && Array.isArray(head.render.bbox_mm);
    finalizeButton.disabled = !!S.run || !ready;
    finalizeButton.title = ready ? text.finalizeHint : text.finalizeNeedsRender;
  }

  async function finalize() {
    const head = headVersion();
    if (!head || S.run) return;
    await startRun(
      "finalize",
      { design_id: S.design.id, version_id: head.id, ...runOptions() },
      "finalize",
    );
  }

  const artifactUrl = (name) =>
    `/api/threads/${encodeURIComponent(S.design.thread_id)}/artifacts/mnt/user-data/outputs/${encodeURIComponent(name)}?download=true`;

  function setCompare(mode) {
    S.compare = mode;
    for (const [key, node] of Object.entries(compareButtons))
      node.setAttribute("aria-pressed", String(key === mode));
    viewer?.setCompare(mode);
  }

  function renderFinal() {
    const head = headVersion();
    const final = head?.final;
    finalBox.replaceChildren();
    finalBox.hidden = !final?.status;
    compareGroup.hidden = true;
    if (!final?.status) {
      if (S.finalKey) {
        S.finalKey = null;
        viewer?.setFinal(null);
      }
      return;
    }
    finalBox.className = `final ${final.status}`;
    finalBox.append(
      element("div", "state", text.final[final.status] ?? final.status),
    );
    if (final.message)
      finalBox.append(element("div", "muted", String(final.message)));
    const measured = Array.isArray(final.bbox_mm) ? final.bbox_mm : null;
    const draft = Array.isArray(final.draft_bbox_mm)
      ? final.draft_bbox_mm
      : null;
    if (measured && draft) {
      const tolerance = Array.isArray(final.tolerance_mm)
        ? triple(final.tolerance_mm)
        : number.format(final.tolerance_mm ?? 0.5);
      finalBox.append(
        element(
          "div",
          "",
          text.bboxCheck(triple(draft), triple(measured), tolerance),
        ),
      );
    }
    const files = (Array.isArray(final.files) ? final.files : []).filter(
      (name) => typeof name === "string" && /^[^/\\]{1,255}$/.test(name),
    );
    if (files.length && S.design?.thread_id) {
      finalBox.append(element("div", "muted", text.files));
      const ul = element("ul");
      for (const name of files) {
        const li = element("li");
        const link = element("a", "", name);
        link.href = artifactUrl(name);
        link.download = name;
        link.setAttribute("aria-label", text.download(name));
        li.append(link);
        ul.append(li);
      }
      finalBox.append(ul);
    }
    const glb = files.find(
      (n) => /\.glb$/i.test(n) && !/\.failed\.glb$/i.test(n),
    );
    if (glb && (final.status === "built" || final.status === "mismatch")) {
      compareGroup.hidden = false;
      // Side by side on a wide screen; one at a time on a phone.
      compareButtons.both.hidden = S.narrow;
      if (S.narrow && S.compare === "both") S.compare = "final";
      const key = `${head.id}:${glb}`;
      if (S.finalKey !== key) {
        S.finalKey = key;
        loadFinal(glb, key);
      } else setCompare(S.compare);
    } else if (S.finalKey) {
      S.finalKey = null;
      viewer?.setFinal(null);
    }
  }

  async function loadFinal(name, key) {
    if (!context.requestBackend || !S.design) return;
    try {
      const response = await context.requestBackend(
        `/api/extensions/cad-design/designs/${S.design.id}/files/${encodeURIComponent(name)}`,
      );
      if (!response.ok) throw new Error(String(response.status));
      const bytes = await response.arrayBuffer();
      const model = await prepareInWorker(bytes, "glb", signal);
      if (S.finalKey !== key || signal.aborted) return;
      viewerReady()?.setFinal(model);
      setCompare(S.compare);
    } catch {
      if (!signal.aborted && S.finalKey === key)
        setNotice(designNotice, text.errors.action);
    }
  }

  // -- conversation ---------------------------------------------------------------------------

  async function loadMessages() {
    if (!S.design) return;
    const id = S.design.id;
    try {
      const { messages: loaded } = await call("messages", { design_id: id });
      if (S.design?.id !== id) return;
      S.messages = Array.isArray(loaded) ? loaded : [];
    } catch {
      S.messages = [];
    }
    renderMessages();
  }

  let messagesFrame = 0;
  function scheduleMessages() {
    if (messagesFrame) return;
    messagesFrame = requestAnimationFrame(() => {
      messagesFrame = 0;
      renderMessages();
    });
  }

  function messageNode(role, body, calls = []) {
    const node = element("div", `msg ${role}`);
    node.append(
      element("div", "who", role === "user" ? text.you : text.assistant),
    );
    if (body) node.append(element("div", "text", body));
    for (const name of calls) node.append(element("span", "chip", name));
    return node;
  }

  function historyNode(message) {
    const calls = (
      Array.isArray(message.tool_calls) ? message.tool_calls : []
    ).map((c) =>
      isScadDraft(c?.name)
        ? text.draftCall(null)
        : text.toolCall(String(c?.name ?? "")),
    );
    if (!message.text && !calls.length) return null;
    return messageNode(message.role, String(message.text ?? ""), calls);
  }

  let historyOf = null;
  function renderHistory() {
    // Only a new message list can change the history.
    if (historyOf === S.messages) return;
    historyOf = S.messages;
    const shown = S.messages.filter(
      (m) =>
        m && (m.role === "user" || m.role === "assistant") && historyNode(m),
    );
    let added = appendOnly(shownIds, shown);
    if (added === null) {
      historyBox.replaceChildren();
      added = shown;
    }
    for (const message of added) historyBox.append(historyNode(message));
    shownIds = shown.map((m) => m.id);
  }

  function renderMessages() {
    const atBottom =
      messages.scrollHeight - messages.scrollTop - messages.clientHeight < 40;
    renderHistory();
    const live = [];
    const run = S.run;
    messages.setAttribute("aria-busy", String(!!run));
    if (run) {
      if (run.prompt) live.push(messageNode("user", run.prompt));
      for (const entry of assistantMessages(run.state))
        live.push(messageNode("assistant", entry.text));
      for (const call of scadCalls(run.state))
        if (call.result)
          live.push(element("span", "chip", text.draftCall(call.result.seq)));
      live.push(element("div", "working", text.working));
    }
    if (S.note) live.push(element("div", "working", S.note));
    if (!historyBox.childElementCount && !live.length)
      live.push(element("p", "muted", text.noMessages));
    liveBox.replaceChildren(...live);
    if (atBottom || run) messages.scrollTop = messages.scrollHeight;
  }

  composer.addEventListener("submit", (event) => {
    event.preventDefault();
    sendPrompt();
  });
  promptBox.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendPrompt();
    }
  });

  async function sendPrompt() {
    const value = promptBox.value.trim();
    if (!value || S.run || !S.design) return;
    if (S.source !== S.savedSource) await saveEdits();
    S.note = null;
    const started = await startRun(
      "prompt",
      { design_id: S.design.id, text: value, ...runOptions() },
      "prompt",
      value,
    );
    if (started) promptBox.value = "";
  }

  // -- runs ------------------------------------------------------------------------------------

  function renderRunState() {
    const running = !!S.run;
    sendButton.disabled = running || !S.design;
    stopButton.hidden = !running;
    promptBox.disabled = running;
    held.hidden = !running;
    editor?.setReadOnly(running);
    runStatus.textContent = running
      ? S.run.kind === "finalize"
        ? text.final.running
        : text.working
      : "";
    renderSaveState();
    renderFinalizeButton();
    for (const node of versionsList.querySelectorAll("button"))
      node.disabled = running;
    for (const node of paramsList.querySelectorAll("input"))
      node.disabled = running;
  }

  async function startRun(action, payload, kind, prompt = null) {
    if (S.run) return false;
    setNotice(designNotice, null);
    let started;
    try {
      started = await call(action, payload);
    } catch (error) {
      failNotice(designNotice, error);
      return false;
    }
    if (!ID.test(started?.run_id ?? "") || !ID.test(started?.thread_id ?? "")) {
      setNotice(designNotice, text.errors.action);
      return false;
    }
    follow(started.run_id, started.thread_id, kind, prompt);
    return true;
  }

  function stopFollowing() {
    if (!S.run) return;
    S.run.controller.abort();
    cancel(S.run.liveTimer);
    S.run = null;
  }

  async function stopRun() {
    const run = S.run;
    if (!run) return;
    run.stopped = true;
    try {
      await call("cancel", { design_id: S.design.id, run_id: run.id });
    } catch (error) {
      failNotice(designNotice, error);
    }
  }

  async function resumeRun() {
    const runId = S.design?.run_id;
    if (!runId || !ID.test(runId) || S.run) return;
    try {
      const { status } = await call("run_status", {
        design_id: S.design.id,
        run_id: runId,
      });
      if (ACTIVE.has(status)) {
        const finalizing = S.versions.some(
          (v) => v.final?.status === "running" && v.final?.run_id === runId,
        );
        follow(runId, S.design.thread_id, finalizing ? "finalize" : "resume");
      } else await reloadDesign();
    } catch {
      /* An unknown run is simply not followed. */
    }
  }

  /** Follow a run: stream it (or poll), render drafts live, then settle the design. */
  async function follow(runId, threadId, kind, prompt = null) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    const run = {
      id: runId,
      threadId,
      kind,
      prompt,
      designId: S.design.id,
      controller,
      state: createRunState(),
      known: new Set(S.versions.map((v) => v.id)),
      handled: new Set(),
      pending: new Set(),
      liveTimer: 0,
      lastPrefix: "",
      lastOutcome: null,
      failedVersion: null,
    };
    S.run = run;
    renderRunState();
    renderMessages();
    let streamed = false;
    if (context.joinRunStream) {
      try {
        for await (const event of context.joinRunStream(threadId, runId, {
          signal: controller.signal,
        })) {
          streamed = true;
          foldRunEvent(run.state, event);
          progress(run);
          if (run.state.ended) break;
        }
      } catch {
        if (controller.signal.aborted) return;
        if (streamed) setNotice(designNotice, text.errors.stream, "info");
      }
    }
    if (controller.signal.aborted) return;
    // Also after a stream that ended: run_status is where the server settles a
    // finalize run that never built ("running" -> "failed") and clears the design's run.
    await poll(run);
    if (controller.signal.aborted) return;
    await settle(run);
    signal.removeEventListener("abort", abort);
  }

  async function poll(run) {
    while (!run.controller.signal.aborted) {
      try {
        const { status } = await call("run_status", {
          design_id: run.designId,
          run_id: run.id,
        });
        if (!ACTIVE.has(status)) {
          if (status === "error") run.state.error = text.runEnded.error;
          if (status === "interrupted")
            run.state.error = text.runEnded.interrupted;
          return;
        }
      } catch {
        return;
      }
      await new Promise((resolve) => later(resolve, POLL_MS));
    }
  }

  /** One folded event: refresh the text, render the streaming draft, handle finished drafts. */
  function progress(run) {
    if (S.run !== run) return;
    scheduleMessages();
    const calls = scadCalls(run.state);
    for (const call of calls)
      if (call.result && !run.handled.has(call.result.version_id))
        handleDraft(run, call);
    const live = calls.findLast(
      (call) => !call.result && !call.failed && call.code,
    );
    if (!live || run.liveTimer) return;
    // At most one live pass per interval while the arguments stream in.
    run.liveTimer = later(() => {
      run.liveTimer = 0;
      if (S.run !== run) return;
      const current = scadCalls(run.state).findLast(
        (call) => !call.result && !call.failed && call.code,
      );
      if (!current) return;
      editor?.setDoc(current.code);
      const prefix = completePrefix(current.code);
      if (!prefix.trim() || prefix === run.lastPrefix) return;
      run.lastPrefix = prefix;
      show(prefix, "live", { partial: true });
    }, LIVE_DEBOUNCE_MS);
  }

  /** The model stored a version: render the whole file, report it, make it the head. */
  function handleDraft(run, call) {
    const versionId = call.result.version_id;
    run.handled.add(versionId);
    if (run.known.has(versionId) || !ID.test(versionId)) return;
    const task = (async () => {
      cancel(run.liveTimer);
      run.liveTimer = 0;
      let scad =
        call.complete && typeof call.code === "string" ? call.code : null;
      if (scad === null) scad = (await fetchVersion(versionId))?.scad ?? "";
      if (S.design?.id !== run.designId) return;
      S.headId = versionId;
      setSource(scad);
      upsertVersion({
        id: versionId,
        seq: call.result.seq,
        parent_id: null,
        source: "model",
        scad,
        render: null,
        created_at: new Date().toISOString(),
      });
      const outcome = await show(scad, "final");
      if (outcome.engine) run.lastOutcome = "engine";
      if (!shouldReport(null, outcome)) return;
      await report(versionId, outcome);
      run.lastOutcome = outcome.ok;
      run.failedVersion = outcome.ok ? null : versionId;
    })();
    run.pending.add(task);
    task.finally(() => run.pending.delete(task));
  }

  async function settle(run) {
    cancel(run.liveTimer);
    await Promise.allSettled([...run.pending]);
    if (S.run !== run) return;
    await reloadDesign();
    // Drafts whose stream was missed (no joinRunStream, or a lost stream) render now.
    for (const version of [...S.versions].sort((a, b) => a.seq - b.seq)) {
      if (
        run.known.has(version.id) ||
        run.handled.has(version.id) ||
        version.render ||
        !isDraftSource(version.source)
      )
        continue;
      run.handled.add(version.id);
      let scad = version.scad;
      if (scad == null) scad = (await fetchVersion(version.id))?.scad ?? "";
      const outcome = await show(scad, "final");
      if (outcome.engine) run.lastOutcome = "engine";
      if (!shouldReport(null, outcome)) continue;
      await report(version.id, outcome);
      run.lastOutcome = outcome.ok;
      run.failedVersion = outcome.ok ? null : version.id;
    }
    S.run = null;
    run.controller.abort();
    const head = headVersion();
    if (head && head.scad != null && head.scad !== S.savedSource)
      setSource(head.scad);
    else {
      // No new version (stopped, failed, or the tool refused the call): put back
      // the head's file where the stream wrote the model's unfinished one.
      editor?.setDoc(S.source);
      if (S.shown?.partial) {
        if (head && S.source.trim()) renderVersion(head, S.source);
        else {
          viewer?.reset();
          S.shown = S.lastGood = null;
          setOverlay(null);
          renderInfo();
        }
      }
    }
    if (run.state.error)
      setNotice(
        designNotice,
        run.state.error === "error"
          ? text.runEnded.error
          : String(run.state.error),
      );
    await loadMessages();
    renderAll();
    renderParams();
    // One automatic repair turn for a draft that did not render, never more.
    if (shouldRepair(run)) {
      S.note = text.repairing;
      renderMessages();
      const started = await startRun(
        "repair",
        {
          design_id: run.designId,
          version_id: run.failedVersion,
          ...runOptions(),
        },
        "repair",
      );
      if (!started) S.note = null;
    } else if (run.kind === "repair") {
      // An engine failure is not the repair's verdict; the preview says what failed.
      S.note =
        run.lastOutcome === true || run.lastOutcome === "engine"
          ? null
          : text.repairSpent;
      renderMessages();
    }
  }

  // -- start --------------------------------------------------------------------------------------

  loadList();

  return function dispose() {
    stopFollowing();
    for (const id of timers) clearTimeout(id);
    timers.clear();
    if (messagesFrame) cancelAnimationFrame(messagesFrame);
    widthObserver.disconnect();
    runner?.dispose();
    viewer?.dispose();
    editor?.dispose();
    root.replaceChildren();
  };
}
