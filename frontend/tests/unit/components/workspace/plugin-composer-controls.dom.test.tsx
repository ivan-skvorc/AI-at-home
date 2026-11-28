import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { PluginSurfaces } from "@/components/workspace/plugin-surfaces";
import type {
  SurfaceComposerControlsHandle,
  SurfaceContext,
  SurfaceRunContext,
} from "@/core/extensions/contracts";
import type { LoadedContribution } from "@/core/extensions/registry";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { THREAD_CONTEXT_KEY_PREFIX } from "@/core/settings/local";

/**
 * `SurfaceContext.composerControls` with real React, the real settings store
 * and the real composer components: a plugin page gets the chat's picker,
 * mode menu and effort menu inside its own element, its choice is kept under
 * the page's scope, and nothing stays mounted after dispose or the page.
 */

const state = rs.hoisted(() => ({
  entries: [] as unknown[],
  models: [] as unknown[],
  // Next's router is stable across renders; a new one would remount the page.
  router: { push: () => undefined },
}));

rs.mock("next/navigation", () => ({
  useRouter: () => state.router,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "alice" } }),
}));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({
    data: state.entries,
    isPending: false,
    isSuccess: true,
  }),
  useFrontendServices: () => ({}),
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ models: state.models }),
}));

const SMART = {
  id: "smart",
  name: "smart",
  model: "smart",
  display_name: "Smart Model",
  supports_thinking: true,
  supports_reasoning_effort: true,
};
const PLAIN = {
  id: "plain",
  name: "plain",
  model: "plain",
  display_name: "Plain Model",
  supports_thinking: false,
  supports_reasoning_effort: false,
};
const WORKFLOWS = {
  namespace: "community.workflows",
  module: null,
  entry: null,
  title: "Script workflows",
  description: "",
  settings: { enabled: true },
};

let mounts: { slot: HTMLElement; context: SurfaceContext }[] = [];
let disposePage = rs.fn();

function install(
  storageKey: string,
  onChange?: (c: SurfaceRunContext) => void,
) {
  const handles: SurfaceComposerControlsHandle[] = [];
  const entry: LoadedContribution = {
    namespace: "cad-design",
    module: "cad-design",
    entry: null,
    title: "CAD design",
    description: "",
    settings: { enabled: true },
    viewer_id: "viewer",
    extension: {
      apiVersion: 1,
      module: "cad-design",
      surfaces: [
        {
          id: "designs",
          slot: "page",
          title: "Designs",
          mount(root, context) {
            const slot = document.createElement("div");
            root.append(slot);
            mounts.push({ slot, context });
            handles.push(
              context.composerControls!.mount(slot, { storageKey, onChange }),
            );
            return { dispose: disposePage };
          },
        },
      ],
    },
  };
  state.entries = [entry, ...state.entries];
  return handles;
}

function renderPage() {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <PluginSurfaces slot="page" namespace="cad-design" surfaceId="designs" />
    </I18nContext.Provider>,
  );
}

/** The controls' own tree: the shadow root the host attached inside the slot. */
function controlsIn(slot: HTMLElement) {
  const host = slot.querySelector<HTMLElement>(
    '[data-slot="composer-controls-host"]',
  );
  const tree = host?.shadowRoot?.querySelector<HTMLElement>(
    '[data-slot="plugin-composer-controls"]',
  );
  if (!tree) throw new Error("controls not mounted");
  return tree;
}

/** The open menu's items by their bold label (the description follows it). */
async function menuItems() {
  const items = await screen.findAllByRole("menuitem");
  return new Map(
    items.map((item) => [
      item.querySelector(".font-bold")?.textContent?.trim() ?? "",
      item,
    ]),
  );
}

async function openModeMenu(slot: HTMLElement, current: string) {
  const trigger = within(controlsIn(slot)).getByRole("button", {
    name: current,
  });
  fireEvent.pointerDown(trigger, { button: 0, pointerType: "mouse" });
  return menuItems();
}

async function chooseMode(slot: HTMLElement, current: string, next: string) {
  const item = (await openModeMenu(slot, current)).get(next);
  if (!item) throw new Error(`no ${next} in the mode menu`);
  fireEvent.click(item);
}

beforeEach(() => {
  window.localStorage.clear();
  state.models = [SMART, PLAIN];
  state.entries = [];
  mounts = [];
  disposePage = rs.fn();
});

afterEach(() => {
  cleanup();
  document.head
    .querySelectorAll("style[data-test-host]")
    .forEach((node) => node.remove());
});

describe("composer controls on a plugin page", () => {
  test("render the chat's controls in the page's element and send what the chat sends", async () => {
    const style = document.createElement("style");
    style.dataset.testHost = "";
    style.textContent = ".host-rule{}";
    document.head.append(style);
    const handles = install("first");
    renderPage();
    await waitFor(() => expect(mounts).toHaveLength(1));
    const slot = mounts[0]!.slot;
    await waitFor(() =>
      expect(within(controlsIn(slot)).getByText("Main agent")).toBeTruthy(),
    );
    const shadow = slot.querySelector(
      '[data-slot="composer-controls-host"]',
    )!.shadowRoot!;
    // The host's styles are copied into the controls' own shadow root only.
    expect(
      [...shadow.querySelectorAll("style")].some(
        (node) => node.textContent === ".host-rule{}",
      ),
    ).toBe(true);
    expect(within(controlsIn(slot)).getByText("Smart Model")).toBeTruthy();
    // A new selection follows the account default, resolved as a new chat's is.
    expect(handles[0]!.runContext()).toEqual({
      model_name: "smart",
      mode: "pro",
      thinking_enabled: true,
      is_plan_mode: true,
      subagent_enabled: false,
      reasoning_effort: "medium",
    });
  });

  test("a mode and a model chosen in the controls reach runContext, onChange and the page's stored selection", async () => {
    const changes: SurfaceRunContext[] = [];
    const handles = install("second", (context) => changes.push(context));
    renderPage();
    await waitFor(() => expect(mounts).toHaveLength(1));
    const slot = mounts[0]!.slot;
    await waitFor(() => controlsIn(slot));

    // The composer's modes for a thinking model; no Ultracode without Script workflows.
    const items = await openModeMenu(slot, enUS.inputBox.proMode);
    expect([...items.keys()]).toEqual([
      enUS.inputBox.flashMode,
      enUS.inputBox.reasoningMode,
      enUS.inputBox.proMode,
      enUS.inputBox.ultraMode,
    ]);
    fireEvent.click(items.get(enUS.inputBox.ultraMode)!);
    await waitFor(() =>
      expect(handles[0]!.runContext()).toMatchObject({
        mode: "ultra",
        subagent_enabled: true,
        is_plan_mode: true,
        reasoning_effort: "high",
      }),
    );
    await waitFor(() =>
      expect(changes.at(-1)).toEqual(handles[0]!.runContext()),
    );
    // Ultra brings the subagent picker, as in the composer.
    expect(within(controlsIn(slot)).getByText("Subagent")).toBeTruthy();

    // The model dialog: search, sort controls and the shared rows.
    fireEvent.click(
      within(controlsIn(slot)).getByText("Main agent").closest("button")!,
    );
    expect(
      screen.getByPlaceholderText(enUS.inputBox.searchModels),
    ).toBeTruthy();
    const plain = screen
      .getAllByRole("option")
      .find((option) => option.getAttribute("data-value") === "plain")!;
    fireEvent.click(plain);
    // Without thinking, only `thinking` falls back to `flash`: Ultra stays.
    await waitFor(() =>
      expect(handles[0]!.runContext()).toMatchObject({
        model_name: "plain",
        mode: "ultra",
      }),
    );
    const stored = JSON.parse(
      window.localStorage.getItem(
        `${THREAD_CONTEXT_KEY_PREFIX}plugin:alice:cad-design/designs/second`,
      ) ?? "{}",
    ) as Record<string, unknown>;
    expect(stored).toMatchObject({ model_name: "plain", mode: "ultra" });
  });

  test("Plus Ultracode is offered only with Script workflows and carries its plugin option", async () => {
    state.entries = [WORKFLOWS];
    const handles = install("third");
    renderPage();
    await waitFor(() => expect(mounts).toHaveLength(1));
    const slot = mounts[0]!.slot;
    await waitFor(() => controlsIn(slot));
    await chooseMode(slot, enUS.inputBox.proMode, enUS.inputBox.ultracodeMode);
    await waitFor(() =>
      expect(handles[0]!.runContext()).toMatchObject({
        mode: "ultracode",
        subagent_enabled: true,
        plugin_options: {
          "community.workflows": { mode: "ultracode", model: "smart" },
        },
      }),
    );
  });

  test("dispose and the page's unmount leave nothing mounted, and a remount mounts once", async () => {
    const handles = install("fourth");
    const view = renderPage();
    await waitFor(() => expect(mounts).toHaveLength(1));
    const slot = mounts[0]!.slot;
    await waitFor(() => controlsIn(slot));
    act(() => handles[0]!.dispose());
    expect(slot.childElementCount).toBe(0);
    // The portal is gone too, not only its host element: no controls render anywhere.
    expect(
      document.querySelectorAll('[data-slot="composer-controls-host"]'),
    ).toHaveLength(0);

    const again = mounts[0]!.context.composerControls!.mount(slot);
    await waitFor(() => controlsIn(slot));
    expect(
      slot.querySelectorAll('[data-slot="composer-controls-host"]'),
    ).toHaveLength(1);
    expect(typeof again.runContext().mode).toBe("string");
    view.unmount();
    expect(disposePage).toHaveBeenCalledTimes(1);
    expect(slot.childElementCount).toBe(0);
    expect(
      document.querySelector('[data-slot="plugin-composer-controls"]'),
    ).toBeNull();

    renderPage();
    await waitFor(() => expect(mounts).toHaveLength(2));
    await waitFor(() => controlsIn(mounts[1]!.slot));
    expect(
      mounts[1]!.slot.querySelectorAll('[data-slot="composer-controls-host"]'),
    ).toHaveLength(1);
  });
});
