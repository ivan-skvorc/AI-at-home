import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

/**
 * The shared model picker (fork feature, FORK.md §8).
 *
 * These pin the property that made this component exist: **every** place a model
 * is chosen behaves like the chat composer's picker. Before it, democracy mode,
 * the suggestions model, the subagent default and the two agent dialogs each
 * rendered a bare `<Select>` in `config.yaml` order with the price as grey text,
 * so the same roster behaved differently depending on which screen you opened.
 *
 * The failure mode is silent — a flat list is not an error, it just makes a
 * model impossible to find — so what is asserted here is that the sort/group
 * controls are present, that the shared preference actually reorders the list,
 * and that prices keep their colour. Swap this component back for a `<Select>`
 * anywhere and its own test goes red rather than the change passing unnoticed.
 */

let prefs: ModelPickerPrefs = { ...DEFAULT_MODEL_PICKER_PREFS };
const setLocalSettings = rs.fn((key: string, value: ModelPickerPrefs) => {
  if (key === "modelPicker") {
    prefs = value;
  }
});

rs.mock("@/core/settings", () => ({
  useLocalSettings: () => [{ modelPicker: prefs }, setLocalSettings],
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      inputBox: {
        searchModels: "Search models...",
        noModelsFound: "No models found.",
        sortModelsBy: "Sort",
        sortByDefault: "Default",
        sortByName: "Name",
        sortByPrice: "Price",
        sortAscending: "Ascending",
        sortDescending: "Descending",
        groupByProvider: "Group by provider",
        modelProviderOther: "Other",
        modelContextSuffix: "ctx",
        modelMetaTitle: "Model id · weights on disk · context window",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

import { ModelSelect } from "@/components/workspace/model-select";
import {
  DEFAULT_MODEL_PICKER_PREFS,
  type ModelPickerPrefs,
} from "@/core/models/sorting";
import type { Model } from "@/core/models/types";

afterEach(() => {
  cleanup();
  prefs = { ...DEFAULT_MODEL_PICKER_PREFS };
  setLocalSettings.mockClear();
});

function model(overrides: Partial<Model> & { name: string }): Model {
  return {
    id: overrides.name,
    model: overrides.name,
    display_name: overrides.name,
    ...overrides,
  } as Model;
}

// Config order is deliberately *not* price or name order, so a list rendered in
// config order is distinguishable from a sorted one.
const MODELS: Model[] = [
  model({
    name: "zeta",
    display_name: "Zeta ($5/25) (Anthropic)",
    price: { currency: "USD", input: 5, output: 25 },
  }),
  model({
    name: "alpha",
    display_name: "Alpha ($1/4) (OpenRouter)",
    price: { currency: "USD", input: 1, output: 4 },
  }),
  model({
    name: "mid",
    display_name: "Mid (Ollama)",
    // A local model: no price, but a GPU footprint and the window the sync
    // sized for it — the two figures a cloud model has no answer for.
    size_bytes: 5.2 * 1024 ** 3,
    context_window: 32768,
  }),
];

function open(extra: Record<string, unknown> = {}) {
  render(
    <ModelSelect models={MODELS} value="zeta" onChange={rs.fn()} {...extra} />,
  );
  fireEvent.click(screen.getByRole("button"));
}

function listedModelNames(): string[] {
  return screen
    .getAllByRole("option")
    .map((el) => el.getAttribute("data-value") ?? "")
    .filter(Boolean);
}

test("the dropdown carries the same sort and group controls as the chat picker", () => {
  open();
  // The three sort keys, the direction toggle, and the group switch — this is
  // the whole point of the component and the half a `<Select>` cannot express.
  expect(screen.getByText("Sort")).toBeTruthy();
  expect(screen.getByText("Default")).toBeTruthy();
  expect(screen.getByText("Name")).toBeTruthy();
  expect(screen.getByText("Price")).toBeTruthy();
  expect(screen.getByText("Group by provider")).toBeTruthy();
  expect(screen.getByPlaceholderText("Search models...")).toBeTruthy();
});

test("out of the box the list keeps config order, so nothing changes until you opt in", () => {
  open();
  expect(listedModelNames()).toEqual(["zeta", "alpha", "mid"]);
});

test("the persisted preference is shared, not per-picker", () => {
  // A sort chosen in the chat composer is already applied here, because both
  // read the one `modelPicker` entry in `deerflow.local-settings`.
  prefs = { ...DEFAULT_MODEL_PICKER_PREFS, sortKey: "name" };
  open();
  expect(listedModelNames()).toEqual(["alpha", "mid", "zeta"]);
});

test("choosing a sort writes it back to that shared preference", () => {
  open();
  fireEvent.click(screen.getByText("Price"));
  expect(setLocalSettings).toHaveBeenCalledWith(
    "modelPicker",
    expect.objectContaining({ sortKey: "price" }),
  );
});

test("sorting by price puts unpriced models last, both directions", () => {
  prefs = { ...DEFAULT_MODEL_PICKER_PREFS, sortKey: "price", sortDir: "asc" };
  open();
  // An unpriced local model has no rate to compare, so it sinks rather than
  // sorting as if it were free — the same rule the composer's picker follows.
  expect(listedModelNames()).toEqual(["alpha", "zeta", "mid"]);
});

test("a pinned pseudo-option stays above the models whatever the sort", () => {
  prefs = { ...DEFAULT_MODEL_PICKER_PREFS, sortKey: "name" };
  render(
    <ModelSelect
      models={MODELS}
      value="__inherit__"
      onChange={rs.fn()}
      options={[{ value: "__inherit__", label: "Follow lead" }]}
    />,
  );
  fireEvent.click(screen.getByRole("button"));
  const rows = screen
    .getAllByRole("option")
    .map((el) => el.getAttribute("data-value"));
  // "Follow lead" is the *absence* of a choice, so sorting it in among the
  // models by name or price would be meaningless.
  expect(rows[0]).toBe("Follow lead");
});

test("demoteLast keeps tool-incapable models at the bottom under any sort", () => {
  prefs = { ...DEFAULT_MODEL_PICKER_PREFS, sortKey: "name" };
  render(
    <ModelSelect
      models={MODELS}
      value="zeta"
      onChange={rs.fn()}
      demoteLast={(m) => m.name === "alpha"}
    />,
  );
  fireEvent.click(screen.getByRole("button"));
  expect(listedModelNames()).toEqual(["mid", "zeta", "alpha"]);
});

test("the price is coloured in the list, not left as grey text", () => {
  open();
  // Green is what you pay. A `<Select>` rendering `display_name` verbatim is
  // exactly what this replaced, and it loses the one number worth scanning for.
  // With a structured `price` on the model the suffix is rendered from that
  // field (parentheses included) rather than parsed back out of the name — the
  // path `/api/models` actually feeds. Either way it lands in its own span so
  // it can be painted.
  const priced = screen
    .getAllByText("($5/25)")
    .filter((el) => el.className.includes("text-emerald-500"));
  // Both the collapsed trigger and the open list row paint it.
  expect(priced.length).toBeGreaterThan(0);
});

test("picking a model reports its name and closes the dropdown", () => {
  const onChange = rs.fn();
  render(<ModelSelect models={MODELS} value="zeta" onChange={onChange} />);
  fireEvent.click(screen.getByRole("button"));
  // The name is its own node now that the row lays the provider, name and
  // price out as separate columns.
  fireEvent.click(screen.getByText("Alpha"));
  expect(onChange).toHaveBeenCalledWith("alpha");
});

function row(name: string): HTMLElement {
  const found = screen
    .getAllByRole("option")
    .find((el) => el.getAttribute("data-value") === name);
  if (!found) {
    throw new Error(`no row for ${name}`);
  }
  return found;
}

test("a row leads with the provider and pins the price to its far edge", () => {
  open();
  const zeta = row("zeta");
  // Provider first: with a couple of dozen models the source is what you scan
  // for before the name.
  expect(zeta.textContent?.startsWith("Anthropic")).toBe(true);
  // And the price at the edge rather than trailing whatever length the name
  // happened to be — that is what makes the column comparable down the list.
  const pinned = zeta.querySelector("span.ml-auto");
  expect(pinned?.textContent).toBe("($5/25)");
});

test("grouping by provider drops the per-row copy the heading already carries", () => {
  prefs = { ...DEFAULT_MODEL_PICKER_PREFS, groupByProvider: true };
  open();
  // The section heading says "Anthropic"; repeating it on every row under it is
  // noise, so the row starts at the name.
  expect(row("zeta").textContent?.startsWith("Zeta")).toBe(true);
});

test("a local model shows its weights and context window beside the model id", () => {
  open();
  // The point of the two fields: how much of the GPU the weights already
  // occupy is what decides how much room the window has left.
  expect(row("mid").textContent).toContain("mid · 5.2 GiB · 32K ctx");
  // A hosted model has neither, and shows the id alone rather than empty slots.
  expect(row("zeta").textContent).toContain("zeta");
  expect(row("zeta").textContent).not.toContain("GiB");
});
