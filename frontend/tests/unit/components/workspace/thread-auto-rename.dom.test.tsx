import { afterEach, expect, rs, test } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

/**
 * The chat header's "Auto rename" dialog (fork feature, FORK.md §38).
 *
 * Two properties that fail silently:
 *
 * * the run does **suggest then rename** — one call generates the title and a
 *   second applies it. Collapsing them into one moves the "409 while a run is
 *   in flight" rule onto a route that cannot enforce it;
 * * the model the user picked is the model that reaches the Gateway, and it is
 *   remembered in the same `autoTitle.modelName` preference the automatic
 *   rename reads — saved to the account like a pick made in Settings. A dialog
 *   that keeps its own copy leaves the two screens disagreeing about which
 *   model will actually run.
 */

const autoRename = rs.fn();
const setAutoTitlePreference = rs.fn();
let storedModelName: string | undefined;
let automaticRenaming = true;
let renamingEnabled = true;

rs.mock("@/core/features", () => ({
  useAutoTitleCapability: () => ({
    enabled: renamingEnabled,
    modelName: null,
    isLoading: false,
  }),
}));

rs.mock("@/core/threads/auto-rename", () => ({
  useAutoRenameThread: () => ({ mutateAsync: autoRename, isPending: false }),
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [
      { name: "cheap-model", display_name: "Cheap", id: "cheap-model" },
      { name: "big-model", display_name: "Big", id: "big-model" },
    ],
  }),
}));

rs.mock("@/core/settings", () => ({
  useLocalSettings: () => [
    {
      autoTitle: { enabled: automaticRenaming, modelName: storedModelName },
      // The picker reads and writes the one shared `modelPicker` preference.
      modelPicker: DEFAULT_MODEL_PICKER_PREFS,
    },
    rs.fn(),
  ],
}));

rs.mock("@/core/settings/auto-title-sync", () => ({
  setAutoTitlePreference: (...args: unknown[]) =>
    setAutoTitlePreference(...args),
}));

const toastCalls: Array<["success" | "error", string]> = [];
rs.mock("sonner", () => ({
  toast: {
    success: (message: string) => toastCalls.push(["success", message]),
    error: (message: string) => toastCalls.push(["error", message]),
  },
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    changeLocale: rs.fn(),
    t: {
      autoRename: {
        label: "Auto rename",
        title: "Rename this conversation",
        description: "A model names the conversation.",
        modelLabel: "Model",
        serverDefault: "Server default",
        serverDefaultHint: "The configured model.",
        run: "Run",
        running: "Renaming…",
        success: (title: string) => `Renamed to "${title}"`,
        failed: "Failed to rename the conversation.",
        manualOnly: "Automatic renaming is off. This renames once, now.",
      },
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
        modelMetaTitle: "Model id",
      },
    },
  }),
}));

import { ThreadAutoRename } from "@/components/workspace/thread-auto-rename";
import { DEFAULT_MODEL_PICKER_PREFS } from "@/core/models/sorting";

afterEach(() => {
  cleanup();
  autoRename.mockReset();
  setAutoTitlePreference.mockReset();
  toastCalls.length = 0;
  storedModelName = undefined;
  automaticRenaming = true;
  renamingEnabled = true;
});

function openDialog() {
  render(<ThreadAutoRename threadId="thread-1" />);
  fireEvent.click(screen.getByTestId("auto-rename-trigger"));
}

async function clickRun() {
  await act(async () => {
    fireEvent.click(screen.getByTestId("auto-rename-run"));
  });
}

test("the button opens a dialog carrying the shared model picker", () => {
  openDialog();

  expect(screen.getByText("Rename this conversation")).toBeTruthy();
  // The sort/group controls only exist on `ModelSelect`; a hand-rolled
  // `<Select>` of models renders and sorts nothing (FORK.md §8).
  fireEvent.click(screen.getByTestId("auto-rename-model-select"));
  expect(screen.getByText("Group by provider")).toBeTruthy();
  expect(screen.getByPlaceholderText("Search models...")).toBeTruthy();
});

test("running with no pick sends no model, leaving the operator's choice alone", async () => {
  autoRename.mockResolvedValue("A better name");
  openDialog();

  await clickRun();

  expect(autoRename).toHaveBeenCalledWith({
    threadId: "thread-1",
    modelName: undefined,
  });
  // Nothing to remember: the user did not choose a model, so the stored
  // preference must not be overwritten with one.
  expect(setAutoTitlePreference).not.toHaveBeenCalled();
  expect(toastCalls).toEqual([["success", 'Renamed to "A better name"']]);
});

test("the picked model is the model that runs, and is remembered for both entry points", async () => {
  autoRename.mockResolvedValue("A better name");
  openDialog();
  fireEvent.click(screen.getByTestId("auto-rename-model-select"));
  fireEvent.click(screen.getByText("Big"));

  await clickRun();

  expect(autoRename).toHaveBeenCalledWith({
    threadId: "thread-1",
    modelName: "big-model",
  });
  // The write-through path, so the pick reaches the account (and with it the
  // automatic rename of runs from every device), not only this browser.
  expect(setAutoTitlePreference).toHaveBeenCalledWith({
    modelName: "big-model",
  });
});

test("the remembered model is where the picker starts", () => {
  // One preference, two entry points: Settings → Conversation titles and this
  // dialog must agree on the model that will run.
  storedModelName = "big-model";
  openDialog();

  expect(screen.getByTestId("auto-rename-model-select").textContent).toContain(
    "Big",
  );
});

test("with automatic renaming off, the button stays and says it renames once", async () => {
  // FORK.md §38: on demand is exactly what is left when the automatic rename is
  // off. Without saying so, a sparkles "Auto rename" in every header reads as
  // the setting being ignored.
  automaticRenaming = false;
  render(<ThreadAutoRename threadId="thread-1" />);
  const trigger = screen.getByTestId("auto-rename-trigger");

  await act(async () => {
    fireEvent.focus(trigger);
  });
  expect(screen.getByRole("tooltip").textContent).toContain(
    "Automatic renaming is off. This renames once, now.",
  );

  fireEvent.click(trigger);
  expect(screen.getByTestId("auto-rename-manual-only").textContent).toBe(
    "Automatic renaming is off. This renames once, now.",
  );
});

test("with automatic renaming on, the button and dialog carry no 'off' note", async () => {
  render(<ThreadAutoRename threadId="thread-1" />);
  const trigger = screen.getByTestId("auto-rename-trigger");

  await act(async () => {
    fireEvent.focus(trigger);
  });
  expect(screen.queryByRole("tooltip")).toBeNull();

  fireEvent.click(trigger);
  expect(screen.queryByTestId("auto-rename-manual-only")).toBeNull();
});

test("a model the operator has since removed does not preselect a name the Gateway refuses", () => {
  // The Gateway answers an unconfigured model with 400 rather than quietly
  // picking another one, so a stale stored name would make the button fail on
  // first press with nothing on screen explaining why.
  storedModelName = "model-that-left-config";
  openDialog();

  expect(screen.getByTestId("auto-rename-model-select").textContent).toContain(
    "Server default",
  );
});

test("the button is absent when the operator turned renaming off", () => {
  // `config.yaml -> title.enabled: false` makes the Gateway answer this route
  // with a 404, so a visible button would only offer a press that cannot work.
  renamingEnabled = false;
  render(<ThreadAutoRename threadId="thread-1" />);

  expect(screen.queryByTestId("auto-rename-trigger")).toBeNull();
});

test("a refusal is shown in the words the Gateway used", async () => {
  autoRename.mockRejectedValue(new Error("Model gpt-legacy is not configured"));
  openDialog();

  await clickRun();

  expect(toastCalls).toEqual([["error", "Model gpt-legacy is not configured"]]);
  // The dialog stays open so the user can pick a different model rather than
  // reopening it from the header.
  expect(screen.getByTestId("auto-rename-run")).toBeTruthy();
});
