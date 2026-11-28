import { prepareInWorker } from "../../deerflow-extension-cad-preview/ui/worker-client.js";

import {
  MAX_JSON_BYTES,
  MAX_SOURCE_BYTES,
  bodiesOf,
  checkSummary,
  designFolder,
  fileKey,
  filesByName,
  hasFolder,
  parseJson,
  printSummary,
  renderSummary,
  versionNumbers,
  viewImages,
} from "./files.js";
import { appendOnly, endedWithoutVersion, pickVersion } from "./outcomes.js";
import {
  assistantMessages,
  createRunState,
  foldRunEvent,
  toolCalls,
} from "./run-stream.js";
import { STYLE } from "./style.js";
import { strings } from "./text.js";
import { VIEWS, createViewer } from "./viewer.js";

const MODEL_RETRY_MS = 1000;
const MODEL_RETRIES = 30;
const LEFT_DEFAULT = 38;
const POLL_MS = 2000;
/** Tool results arrive in bursts; one listing follows the burst. */
const REFRESH_MS = 400;
const NARROW_PX = 768;
/** Parsed bodies and read JSON kept per design view, oldest dropped first. */
const CACHE_ENTRIES = 48;
const ACTIVE = new Set(["pending", "running"]);
const ID = /^[A-Za-z0-9_-]{1,128}$/;
const TABS = ["preview", "views", "checks", "code", "files"];

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
/** Keep at most CACHE_ENTRIES values; a Map iterates in insertion order. */
const remember = (cache, key, value) => {
  cache.set(key, value);
  while (cache.size > CACHE_ENTRIES) cache.delete(cache.keys().next().value);
  return value;
};

/** Mount the Designs page into `root` (inside the host's shadow root); returns dispose(). */
export function mountPage(root, context) {
  const text = strings(context.locale);
  const { signal } = context;
  const files = context.threadFiles ?? null;
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
  const fmt = (value) => (value === null ? "?" : number.format(value));
  const triple = (values) => values.map(fmt).join(" × ");
  const bytes = (size) =>
    typeof size !== "number"
      ? ""
      : size < 1024
        ? `${size} B`
        : size < 1024 * 1024
          ? `${number.format(size / 1024)} KiB`
          : `${number.format(size / 1024 / 1024)} MiB`;

  const S = {
    trash: false,
    container: true,
    design: null,
    folder: designFolder(null),
    versions: [],
    selected: null,
    // Show the newest version as it appears, until the user picks an older one.
    follow: true,
    loaded: null,
    hidden: new Set(),
    messages: [],
    run: null,
    tab: "preview",
    phone: "preview",
    narrow: false,
    note: null,
  };
  // Created with the first design view; released when it closes.
  let viewer = null;
  // Set when the 3D view could not start (no WebGL); the lists and checks still show.
  let viewerFailed = false;
  // Aborted when the design view closes: listings, reads and parses stop with it.
  let view = null;
  let loadToken = 0;
  const models = new Map();
  const reads = new Map();
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
  const listBanner = element("div");
  const listNotice = element("div", "notice");
  listNotice.hidden = true;
  listNotice.setAttribute("role", "status");
  const list = element("ul", "list");
  listView.append(listBar, listBanner, listNotice, list);

  const designView = element("div", "design");
  designView.hidden = true;
  const designBar = element("header", "bar");
  const back = button(`← ${text.backToDesigns}`, () => closeDesign());
  const title = element("h1");
  const renameButton = button(text.rename, () => renameDesign(S.design, title));
  const runStatus = element("span", "muted");
  runStatus.setAttribute("role", "status");
  designBar.append(
    back,
    title,
    renameButton,
    element("span", "grow"),
    runStatus,
  );
  const designBanner = element("div");
  const designNotice = element("div", "notice");
  designNotice.hidden = true;
  designNotice.setAttribute("role", "status");

  const phoneTabs = element("nav", "phone-tabs");
  phoneTabs.setAttribute("role", "tablist");
  const phoneButtons = {};
  for (const key of ["prompt", "preview"]) {
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
  const viewingNote = element("div", "muted viewing");
  viewingNote.hidden = true;
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
  composer.append(viewingNote, promptBox, composerRow);
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
  const head = element("div", "tabs");
  const versionLabel = element("label", "version");
  const versionSelect = element("select");
  versionSelect.setAttribute("aria-label", text.version);
  versionLabel.append(element("span", "muted", text.version), versionSelect);
  versionSelect.addEventListener("change", () => {
    const n = Number(versionSelect.value);
    if (!S.versions.includes(n)) return;
    S.follow = n === newest();
    S.selected = n;
    renderViewing();
    showVersion(n);
  });
  const tabs = element("div", "tablist");
  tabs.setAttribute("role", "tablist");
  const tabButtons = {};
  for (const key of TABS) {
    const node = button(text.tabs[key], () => setTab(key));
    node.setAttribute("role", "tab");
    tabButtons[key] = node;
    tabs.append(node);
  }
  head.append(versionLabel, tabs);

  // Preview panel
  const previewPanel = element("div", "panel preview");
  const toolbar = element("div", "toolbar");
  const viewButton = (label, direction) => {
    const node = button(label, () => viewer?.fit(direction));
    node.setAttribute("aria-label", text.viewLabel(label));
    return node;
  };
  toolbar.append(
    button(text.fit, () => viewer?.fit()),
    viewButton(text.top, VIEWS.top),
    viewButton(text.front, VIEWS.front),
    viewButton(text.iso, VIEWS.iso),
  );
  const stage = element("div", "stage");
  const viewport = element("div", "viewport");
  const placeholder = element("div", "placeholder", text.noVersion);
  const overlay = element("div", "overlay");
  overlay.hidden = true;
  overlay.setAttribute("role", "status");
  viewport.append(placeholder, overlay);
  const bodyList = element("ul", "bodies");
  bodyList.setAttribute("aria-label", text.bodies);
  stage.append(viewport, bodyList);
  const info = element("div", "info");
  previewPanel.append(toolbar, stage, info);

  const viewsPanel = element("div", "panel views");
  const checksPanel = element("div", "panel checks");
  const codePanel = element("div", "panel code");
  const codeBox = element("pre", "source");
  codeBox.tabIndex = 0;
  codeBox.setAttribute("aria-label", text.tabs.code);
  codePanel.append(codeBox);
  const filesPanel = element("div", "panel files");

  work.append(
    head,
    previewPanel,
    viewsPanel,
    checksPanel,
    codePanel,
    filesPanel,
  );
  split.append(chat, divider, work);
  designView.append(designBar, designBanner, designNotice, phoneTabs, split);
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
  const newest = () => S.versions[S.versions.length - 1] ?? 0;

  /** The setup commands, shown while the host runs no sandbox containers. */
  function renderBanner() {
    listBanner.replaceChildren();
    designBanner.replaceChildren();
    if (S.container) return;
    const banner = element("div", "notice info banner");
    banner.setAttribute("role", "status");
    const commands = element("pre");
    commands.textContent = text.container.commands.join("\n");
    banner.append(
      element("strong", "", text.container.title),
      element("p", "", text.container.body),
      commands,
      element("p", "", text.container.after),
    );
    // Only in the view on screen, so the page holds one copy of the commands.
    (S.design ? designBanner : listBanner).append(banner);
  }

  function setOverlay(message, isError = false) {
    // A browser without WebGL keeps saying so once nothing else is to be said.
    if (!message && viewerFailed) {
      message = text.errors.webgl;
      isError = true;
    }
    overlay.hidden = !message;
    overlay.textContent = message ?? "";
    overlay.classList.toggle("error", isError);
  }

  function setTab(key) {
    S.tab = key;
    work.dataset.tab = key;
    for (const [name, node] of Object.entries(tabButtons))
      node.setAttribute("aria-selected", String(name === key));
    if (key === "preview") viewer?.resize();
    if (key === "code") renderCode();
  }
  function setPhone(key) {
    S.phone = key;
    app.dataset.phone = key;
    for (const [name, node] of Object.entries(phoneButtons))
      node.setAttribute("aria-selected", String(name === key));
    if (key === "preview") {
      phoneDot.hidden = true;
      if (S.tab === "preview") viewer?.resize();
    }
  }
  setTab("preview");
  setPhone("preview");

  function viewerReady() {
    if (viewer) return viewer;
    if (viewerFailed) return null;
    try {
      viewer = createViewer(viewport, {
        label: text.viewport,
        // No WebGL, or the context was lost: the viewer stays empty from here on.
        onLost: () => {
          viewerFailed = true;
          setOverlay(text.errors.webgl, true);
          renderPlaceholder();
        },
      });
    } catch {
      viewerFailed = true;
      setOverlay(text.errors.webgl, true);
      return null;
    }
    return viewer;
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
    viewer?.resize();
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
    let loaded;
    try {
      loaded = await call("list_designs", { trash: S.trash });
    } catch (error) {
      list.replaceChildren();
      failNotice(listNotice, error);
      return;
    }
    S.container = loaded?.container !== false;
    renderBanner();
    const designs = loaded?.designs;
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
        formatTime(design.deleted_at ?? design.updated_at),
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

  async function openDesign(designId) {
    setNotice(listNotice, null);
    let loaded;
    try {
      loaded = await call("get_design", { design_id: designId });
    } catch (error) {
      failNotice(listNotice, error);
      return;
    }
    if (!ID.test(loaded?.design?.id ?? "")) {
      setNotice(listNotice, text.errors.action);
      return;
    }
    listView.hidden = true;
    designView.hidden = false;
    setNotice(designNotice, null);
    view?.abort();
    view = new AbortController();
    S.design = loaded.design;
    S.folder = designFolder(loaded.folder);
    S.container = loaded.container !== false;
    S.versions = [];
    S.selected = null;
    S.follow = true;
    S.loaded = null;
    S.hidden = new Set();
    S.note = null;
    S.messages = [];
    models.clear();
    reads.clear();
    title.textContent = S.design.title || text.untitled;
    viewer?.reset();
    setOverlay(null);
    modelTries = 0;
    renderModels();
    renderBanner();
    renderPicker();
    renderViewing();
    renderVersion();
    renderRunState();
    renderMessages();
    loadMessages();
    refresh();
    resumeRun();
  }

  function closeDesign() {
    stopFollowing();
    view?.abort();
    view = null;
    loadToken += 1;
    S.design = null;
    S.loaded = null;
    models.clear();
    reads.clear();
    designView.hidden = true;
    listView.hidden = false;
    viewer?.dispose();
    viewer = null;
    viewerFailed = false;
    setOverlay(null);
    loadList();
  }

  // -- version folders ------------------------------------------------------------------

  const viewSignal = () => AbortSignal.any([signal, view.signal]);

  /** One folder of the design's outputs, or null when it does not exist (yet). */
  async function listFolder(path) {
    try {
      return await files.list(S.design.thread_id, path, {
        signal: viewSignal(),
      });
    } catch (error) {
      if (error?.status === 404) return null;
      throw error;
    }
  }

  /** A JSON report as an object; undefined when absent, null when unreadable. */
  function readJson(entry) {
    if (!entry) return Promise.resolve(undefined);
    if (typeof entry.size === "number" && entry.size > MAX_JSON_BYTES)
      return Promise.resolve(null);
    const key = fileKey(entry);
    const cached = reads.get(key);
    if (cached) return cached;
    const pending = files
      .read(S.design.thread_id, entry.path, {
        signal: viewSignal(),
        maxBytes: MAX_JSON_BYTES,
      })
      .then(parseJson)
      .catch(() => {
        reads.delete(key);
        return null;
      });
    return remember(reads, key, pending);
  }

  /** A body's STL, parsed in its own Worker by cad-preview's capped parser. */
  function modelOf(entry) {
    const key = fileKey(entry);
    const cached = models.get(key);
    if (cached) return cached;
    const own = viewSignal();
    const pending = files
      .read(S.design.thread_id, entry.path, { signal: own })
      .then((data) => prepareInWorker(data, "stl", own));
    pending.catch(() => models.delete(key));
    return remember(models, key, pending);
  }

  // The run whose final listing is in flight: it may still bring the first new version.
  let settling = null;
  let refreshTimer = 0;
  let refreshing = null;
  let refreshAgain = false;
  const scheduleRefresh = (ms = REFRESH_MS) => {
    cancel(refreshTimer);
    refreshTimer = later(() => refresh(), ms);
  };

  /** List the design folder and show the chosen version; one listing at a time. */
  function refresh() {
    if (refreshing) {
      refreshAgain = true;
      return refreshing;
    }
    refreshing = (async () => {
      do {
        refreshAgain = false;
        await refreshOnce();
      } while (refreshAgain && S.design && !signal.aborted);
    })().finally(() => {
      refreshing = null;
    });
    return refreshing;
  }

  async function refreshOnce() {
    const design = S.design;
    if (!design || !ID.test(design.thread_id ?? "")) return;
    if (!files) {
      setNotice(designNotice, text.errors.noFiles, "info");
      return;
    }
    let entries;
    try {
      entries = await listFolder(S.folder);
    } catch {
      if (S.design === design && !signal.aborted)
        setNotice(designNotice, text.errors.list);
      return;
    }
    if (S.design !== design) return;
    const before = newest();
    S.versions = versionNumbers(entries ?? []);
    if (newest() > before && S.narrow && S.phone !== "preview")
      phoneDot.hidden = false;
    // A run's first new version is shown even when the user was looking at an
    // older one: that is the answer to what they just asked.
    const run = S.run ?? settling;
    if (run && !run.jumped && newest() > run.newestBefore) {
      run.jumped = true;
      S.follow = true;
    }
    const n = pickVersion(S.versions, {
      selected: S.selected,
      follow: S.follow,
    });
    renderPicker(n);
    renderViewing();
    renderPlaceholder();
    await showVersion(n);
  }

  /** Read version `n`'s folder and show it; a newer request supersedes this one. */
  async function showVersion(n) {
    const token = ++loadToken;
    const design = S.design;
    S.selected = n;
    renderPicker(n);
    if (n === null) {
      S.loaded = null;
      viewer?.keep([]);
      renderVersion();
      return;
    }
    const base = `${S.folder}/v${n}`;
    if (S.loaded?.n !== n) setOverlay(text.loadingVersion(n));
    let entries;
    let views = [];
    let print = [];
    try {
      entries = (await listFolder(base)) ?? [];
      if (hasFolder(entries, "views"))
        views = (await listFolder(`${base}/views`)) ?? [];
      if (hasFolder(entries, "print"))
        print = (await listFolder(`${base}/print`)) ?? [];
    } catch {
      if (token === loadToken && !signal.aborted) {
        setOverlay(null);
        setNotice(designNotice, text.errors.list);
      }
      return;
    }
    if (token !== loadToken || S.design !== design) return;
    const top = filesByName(entries);
    const printFiles = filesByName(print);
    const [report, check, printReport] = await Promise.all([
      readJson(top.get("report.json")),
      readJson(top.get("check.json")),
      readJson(printFiles.get("print.json") ?? top.get("print.json")),
    ]);
    if (token !== loadToken || S.design !== design) return;
    S.loaded = {
      n,
      base,
      top,
      viewFiles: filesByName(views),
      printFiles,
      report,
      check,
      print: printReport,
      bodies: bodiesOf(report, top),
      failed: new Set(),
    };
    renderVersion();
    await drawBodies(token);
  }

  /** Each body's mesh in its colour; a body keeps its mesh until the new one is ready. */
  async function drawBodies(token) {
    const loaded = S.loaded;
    const shown = loaded.bodies.filter((body) => body.file);
    viewer?.keep(shown.map((body) => body.name));
    for (const body of shown) {
      let model;
      try {
        model = await modelOf(loaded.top.get(body.file));
      } catch {
        if (token !== loadToken || signal.aborted) return;
        loaded.failed.add(body.name);
        // An older version's mesh of the same name must not stand in for it.
        viewer?.keep(
          shown
            .filter((other) => !loaded.failed.has(other.name))
            .map((other) => other.name),
        );
        renderBodies();
        continue;
      }
      if (token !== loadToken) return;
      const target = viewerReady();
      if (!target) continue;
      try {
        target.setBody(body.name, model, {
          color: body.color,
          visible: !S.hidden.has(body.name),
        });
      } catch {
        viewerFailed = true;
      }
    }
    if (token !== loadToken) return;
    setOverlay(null);
    renderPlaceholder();
  }

  function renderPicker(selected = S.selected) {
    const top = newest();
    versionSelect.replaceChildren(
      ...[...S.versions]
        .reverse()
        .map((n) => new Option(text.versionLabel(n, n === top), String(n))),
    );
    versionSelect.value = selected === null ? "" : String(selected);
    versionSelect.disabled = S.versions.length < 2;
    versionLabel.hidden = !S.versions.length;
  }

  function renderViewing() {
    const older = S.selected !== null && S.selected < newest() && !S.follow;
    viewingNote.hidden = !older;
    viewingNote.textContent = older ? text.viewingOlder(S.selected) : "";
  }

  function renderPlaceholder() {
    placeholder.hidden = S.versions.length > 0 || viewerFailed;
  }

  function renderVersion() {
    renderBodies();
    renderInfo();
    renderViews();
    renderChecks();
    renderFiles();
    if (S.tab === "code") renderCode();
    renderPlaceholder();
    if (!S.loaded) setOverlay(null);
  }

  function renderBodies() {
    bodyList.replaceChildren();
    const loaded = S.loaded;
    bodyList.hidden = !loaded?.bodies.length;
    if (!loaded) return;
    for (const body of loaded.bodies) {
      const item = element("li", "body");
      const label = element("label");
      const toggle = element("input");
      toggle.type = "checkbox";
      toggle.checked = !S.hidden.has(body.name);
      toggle.disabled = !body.file;
      toggle.setAttribute("aria-label", text.showBody(body.name));
      toggle.addEventListener("change", () => {
        if (toggle.checked) S.hidden.delete(body.name);
        else S.hidden.add(body.name);
        viewer?.setVisible(body.name, toggle.checked);
      });
      const swatch = element("span", "swatch");
      swatch.style.background = body.color;
      label.append(toggle, swatch, element("span", "name", body.name));
      item.append(label);
      const facts = [];
      if (body.size) facts.push(text.size(...body.size.map(fmt)));
      if (body.volume !== null) facts.push(text.volume(fmt(body.volume)));
      if (body.mass !== null) facts.push(text.mass(fmt(body.mass)));
      if (facts.length) item.append(element("span", "meta", facts.join(" · ")));
      if (body.watertight === false && !body.error)
        item.append(element("span", "meta error", text.open));
      if (body.error)
        item.append(element("span", "meta error", text.bodyFailed(body.error)));
      else if (!body.file)
        item.append(element("span", "meta error", text.noStl));
      else if (loaded.failed.has(body.name))
        item.append(element("span", "meta error", text.bodyUnreadable));
      bodyList.append(item);
    }
  }

  function renderInfo() {
    info.replaceChildren();
    const loaded = S.loaded;
    if (!loaded) return;
    const summary = renderSummary(loaded.report);
    info.append(
      element(
        "span",
        "",
        text.summary(loaded.n, loaded.bodies.length, summary?.seconds ?? null),
      ),
    );
    if (loaded.report === undefined)
      info.append(element("span", "muted", text.rendering(loaded.n)));
  }

  function renderViews() {
    viewsPanel.replaceChildren();
    const loaded = S.loaded;
    const names = loaded ? viewImages(loaded.viewFiles) : [];
    if (!names.length) {
      viewsPanel.append(element("p", "muted pad", text.noViews));
      return;
    }
    const grid = element("div", "gallery");
    for (const name of names) {
      const entry = loaded.viewFiles.get(name);
      const url = files.url(S.design.thread_id, entry.path);
      // A rewritten image (views run again) has a new time: the browser fetches it anew.
      const src = `${url}${url.includes("?") ? "&" : "?"}t=${encodeURIComponent(entry.modified_at ?? "")}`;
      const figure = element("figure");
      const link = element("a");
      link.href = src;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      const image = element("img");
      image.src = src;
      image.alt = text.viewAlt(name);
      image.loading = "lazy";
      image.decoding = "async";
      link.append(image);
      figure.append(link, element("figcaption", "", name));
      grid.append(figure);
    }
    viewsPanel.append(grid);
  }

  function section(heading) {
    const node = element("section", "check");
    node.append(element("h3", "", heading));
    checksPanel.append(node);
    return node;
  }
  const bullets = (items) => {
    const ul = element("ul");
    for (const item of items) ul.append(element("li", "", item));
    return ul;
  };

  function renderChecks() {
    checksPanel.replaceChildren();
    const loaded = S.loaded;
    if (!loaded) {
      checksPanel.append(element("p", "muted pad", text.noChecks));
      return;
    }
    const c = text.checks;
    const render = section(c.render);
    const summary = renderSummary(loaded.report);
    if (loaded.report === undefined)
      render.append(element("p", "muted", text.rendering(loaded.n)));
    else if (!summary)
      render.append(element("p", "error", c.unreadable("report.json")));
    else {
      if (summary.seconds !== null)
        render.append(element("p", "", c.seconds(fmt(summary.seconds))));
      if (loaded.bodies.length > 1)
        render.append(
          summary.clashes.length
            ? element("p", "error", c.asModelled)
            : element("p", "", c.noOverlap),
        );
      if (summary.clashes.length)
        render.append(
          bullets(
            summary.clashes.map((clash) =>
              c.clash(clash.pair, fmt(clash.volume), clash.where),
            ),
          ),
        );
      if (summary.warnings.length) {
        render.append(element("p", "", c.warnings));
        render.append(bullets(summary.warnings));
      }
      if (summary.echo)
        render.append(element("p", "muted", c.echo(summary.echo)));
    }

    const collisions = section(c.collisions);
    const check = checkSummary(loaded.check);
    if (loaded.check === undefined)
      collisions.append(element("p", "muted", c.notRun("check")));
    else if (!check)
      collisions.append(element("p", "error", c.unreadable("check.json")));
    else {
      collisions.append(
        element(
          "p",
          check.clashes ? "error" : "",
          c.states(fmt(check.states), fmt(check.clashes), check.clearance),
        ),
      );
      if (check.findings.length)
        collisions.append(
          bullets(
            check.findings.map((f) =>
              c.stateClash(f.pose, f.state, f.pair, fmt(f.volume)),
            ),
          ),
        );
      if (check.more)
        collisions.append(element("p", "muted", c.more(check.more)));
    }

    const printing = section(c.print);
    const print = printSummary(loaded.print);
    if (loaded.print === undefined)
      printing.append(element("p", "muted", c.notRun("print")));
    else if (!print)
      printing.append(element("p", "error", c.unreadable("print.json")));
    else {
      if (print.layout && print.bed)
        printing.append(
          element("p", "", c.layout(triple(print.layout), triple(print.bed))),
        );
      if (print.problems.length) {
        printing.append(element("p", "error", c.problems));
        printing.append(bullets(print.problems));
        if (print.more)
          printing.append(element("p", "muted", c.more(print.more)));
      } else printing.append(element("p", "", c.noProblems));
      const slicer = print.slicer;
      printing.append(
        element(
          "p",
          slicer.error ? "error" : "",
          `${c.slicer}: ${
            slicer.error ??
            slicer.skipped ??
            c.sliced(slicer.filament, slicer.time, slicer.settings)
          }`,
        ),
      );
    }
  }

  let codeKey = null;
  async function renderCode() {
    const loaded = S.loaded;
    const entry = loaded?.top.get("model.scad");
    if (!entry) {
      codeKey = null;
      codeBox.textContent = loaded ? text.noCode : "";
      return;
    }
    if (typeof entry.size === "number" && entry.size > MAX_SOURCE_BYTES) {
      codeKey = null;
      codeBox.textContent = text.codeTooLarge;
      return;
    }
    const key = fileKey(entry);
    if (codeKey === key) return;
    codeKey = key;
    codeBox.textContent = text.loading;
    let source;
    try {
      const data = await files.read(S.design.thread_id, entry.path, {
        signal: viewSignal(),
        maxBytes: MAX_SOURCE_BYTES,
      });
      source = new TextDecoder().decode(data);
    } catch {
      source = null;
    }
    if (codeKey !== key) return;
    if (source === null) codeKey = null;
    codeBox.textContent = source ?? text.codeTooLarge;
  }

  function renderFiles() {
    filesPanel.replaceChildren();
    const loaded = S.loaded;
    const groups = loaded
      ? [
          ["", loaded.top],
          ["views/", loaded.viewFiles],
          ["print/", loaded.printFiles],
        ].filter(([, group]) => group.size)
      : [];
    if (!groups.length) {
      filesPanel.append(element("p", "muted pad", text.noFiles));
      return;
    }
    const ul = element("ul", "file-list");
    for (const [prefix, group] of groups)
      for (const name of [...group.keys()].sort()) {
        const entry = group.get(name);
        const li = element("li");
        const link = element("a", "", `${prefix}${name}`);
        link.href = files.url(S.design.thread_id, entry.path, {
          download: true,
        });
        link.download = name;
        link.setAttribute("aria-label", text.download(`${prefix}${name}`));
        li.append(link, element("span", "muted", bytes(entry.size)));
        ul.append(li);
      }
    filesPanel.append(ul);
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

  const callLabel = (name, summary) =>
    summary ? `${name}: ${summary}` : String(name);

  function messageNode(role, body, calls = []) {
    const node = element("div", `msg ${role}`);
    node.append(
      element("div", "who", role === "user" ? text.you : text.assistant),
    );
    if (body) node.append(element("div", "text", body));
    for (const label of calls) node.append(element("span", "chip", label));
    return node;
  }

  function historyNode(message) {
    if (message.role === "tool") {
      const body = String(message.text ?? "");
      if (!body.trim()) return null;
      const node = element("details", "msg tool");
      node.append(
        element(
          "summary",
          "",
          text.toolResult(String(message.tool_name ?? "")),
        ),
        element("pre", "", body),
      );
      return node;
    }
    const calls = (
      Array.isArray(message.tool_calls) ? message.tool_calls : []
    ).map((c) => callLabel(String(c?.name ?? ""), String(c?.summary ?? "")));
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
        m &&
        (m.role === "user" || m.role === "assistant" || m.role === "tool") &&
        historyNode(m),
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
      for (const item of toolCalls(run.state))
        live.push(
          element(
            "span",
            item.done ? "chip done" : "chip",
            callLabel(item.name, item.summary),
          ),
        );
      live.push(element("div", "working", text.working));
    }
    if (S.note) live.push(element("div", "working note", S.note));
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
    S.note = null;
    // The version on screen rides along: the model is told when it is not the newest.
    const viewing =
      S.selected !== null ? { viewing: S.selected, newest: newest() } : {};
    const started = await startRun(
      { design_id: S.design.id, text: value, ...viewing, ...runOptions() },
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
    runStatus.textContent = running ? text.working : "";
  }

  async function startRun(payload, prompt) {
    if (S.run) return false;
    setNotice(designNotice, null);
    let started;
    try {
      started = await call("prompt", payload);
    } catch (error) {
      failNotice(designNotice, error);
      return false;
    }
    if (!ID.test(started?.run_id ?? "") || !ID.test(started?.thread_id ?? "")) {
      setNotice(designNotice, text.errors.action);
      return false;
    }
    follow(started.run_id, started.thread_id, "prompt", prompt);
    return true;
  }

  function stopFollowing() {
    if (!S.run) return;
    S.run.controller.abort();
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
    const design = S.design;
    const runId = design?.run_id;
    if (!runId || !ID.test(runId) || S.run) return;
    try {
      const { status } = await call("run_status", {
        design_id: design.id,
        run_id: runId,
      });
      if (S.design === design && ACTIVE.has(status))
        follow(runId, design.thread_id, "resume");
    } catch {
      /* An unknown run is simply not followed. */
    }
  }

  /** Follow a run: stream it (or poll), re-list the versions as tools answer, then settle. */
  async function follow(runId, threadId, kind, prompt = null) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    const run = {
      id: runId,
      kind,
      prompt,
      designId: S.design.id,
      controller,
      state: createRunState(),
      newestBefore: newest(),
      results: 0,
      streamed: false,
      stopped: false,
    };
    S.run = run;
    renderRunState();
    renderMessages();
    if (context.joinRunStream) {
      try {
        for await (const event of context.joinRunStream(threadId, runId, {
          signal: controller.signal,
        })) {
          run.streamed = true;
          foldRunEvent(run.state, event);
          progress(run);
          if (run.state.ended) break;
        }
      } catch {
        if (controller.signal.aborted) return;
        if (run.streamed) setNotice(designNotice, text.errors.stream, "info");
      }
    }
    if (controller.signal.aborted) return;
    // Also after a stream that ended: run_status is where the server clears the design's run.
    await poll(run);
    if (controller.signal.aborted) return;
    signal.removeEventListener("abort", abort);
    await settle(run);
  }

  /** One folded event: redraw the turn, and list the folder again when a tool answered. */
  function progress(run) {
    if (S.run !== run) return;
    scheduleMessages();
    const answered = run.state.results.size;
    if (answered !== run.results) {
      run.results = answered;
      scheduleRefresh();
    }
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
      // Without a stream there is no tool result to wait for: list on each poll.
      if (!run.streamed) scheduleRefresh(0);
      await new Promise((resolve) => later(resolve, POLL_MS));
    }
  }

  async function settle(run) {
    if (S.run !== run) return;
    S.run = null;
    run.controller.abort();
    cancel(refreshTimer);
    renderRunState();
    settling = run;
    await refresh();
    settling = null;
    if (S.design?.id !== run.designId) return;
    if (run.state.error)
      setNotice(
        designNotice,
        run.state.error === "error"
          ? text.runEnded.error
          : String(run.state.error),
      );
    // A turn that made no version leaves the preview as it was: say so, not nothing.
    if (endedWithoutVersion(run, newest())) S.note = text.noNewVersion;
    await loadMessages();
    renderMessages();
  }

  // -- start --------------------------------------------------------------------------------------

  loadList();

  return function dispose() {
    stopFollowing();
    view?.abort();
    for (const id of timers) clearTimeout(id);
    timers.clear();
    if (messagesFrame) cancelAnimationFrame(messagesFrame);
    widthObserver.disconnect();
    viewer?.dispose();
    viewer = null;
    models.clear();
    reads.clear();
    root.replaceChildren();
  };
}
