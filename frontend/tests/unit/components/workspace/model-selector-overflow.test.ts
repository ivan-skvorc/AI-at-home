import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
// The trigger's own wrapper: the first <div> after the trigger opens, however
// far <ModelSelectorName> sits inside it.
//
// Upstream can require the name to follow the div immediately. This fork puts a
// "Main agent" / "Subagent" label between the two (FORK.md §3), and with the
// stricter spelling the leading `[\s\S]*?` simply walked past the trigger and
// matched a row *inside the dropdown list* — the assertions then passed against
// an unrelated div and guarded nothing. Anchoring on the first div after the
// trigger keeps the guard pointed at the control it is about.
const SELECTED_MODEL_WRAPPER_PATTERN =
  /<ModelSelectorTrigger asChild>(?:(?!<div)[\s\S])*<div className="([^"]*)">[\s\S]*?<ModelSelectorName/;

function source(relativePath: string) {
  return readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
}

function selectedModelWrapperClasses(relativePath: string) {
  return SELECTED_MODEL_WRAPPER_PATTERN.exec(source(relativePath))?.[1]?.split(
    /\s+/,
  );
}

describe("selected model name truncation", () => {
  it.each([
    "src/components/workspace/input-box.tsx",
    "src/components/workspace/sidecar/sidecar-panel.tsx",
  ])("lets the selected model name stretch in %s", (relativePath) => {
    const classes = selectedModelWrapperClasses(relativePath);

    expect(classes).toEqual(
      expect.arrayContaining(["flex", "min-w-0", "flex-col"]),
    );
    expect(classes).not.toContain("items-start");
  });
});

describe("model picker integration", () => {
  // Upstream replaced the composer/sidecar picker with a favorites-based
  // `ModelPickerContent` and deleted `ai-elements/model-selector`. This fork
  // keeps its own picker — search, sort, group-by-provider and the price column
  // (FORK.md; "One model picker, everywhere" in `src/AGENTS.md`) — and keeps
  // that component alive. The failure this guards is silent: swapping either
  // call site to upstream's picker still compiles, type-checks and renders, it
  // just drops search, sorting, grouping and prices on that one screen.
  it.each([
    {
      relativePath: "src/components/workspace/input-box.tsx",
      open: "modelDialogOpen",
      onSelect: "handleModelSelect",
    },
    {
      relativePath: "src/components/workspace/sidecar/sidecar-panel.tsx",
      open: "open",
      onSelect: "onModelSelect",
    },
  ])(
    "drives the fork's sorted, searchable picker in $relativePath",
    ({ relativePath, open, onSelect }) => {
      const contents = source(relativePath);

      expect(contents).toMatch(/<ModelSelector\s/);
      expect(contents).toContain("<ModelSelectorTrigger asChild>");
      expect(contents).toMatch(new RegExp(`open=\\{${open}\\}`));
      // The three pieces that make it the fork's picker rather than a flat list.
      expect(contents).toContain("<ModelSelectorInput");
      expect(contents).toContain("<ModelPickerControls");
      expect(contents).toContain("<ModelPickerRow");
      expect(contents).toMatch(
        new RegExp(`onSelect=\\{\\(\\) => ${onSelect}\\(`),
      );
      // Prefs come from the one shared store, so a sort chosen in a
      // conversation is already applied in Settings.
      expect(contents).toContain("localSettings.modelPicker");
      // Upstream's picker must not be half-wired into the same control.
      for (const upstreamComponent of [
        "ModelPickerContent",
        "ModelPickerTrigger",
      ]) {
        expect(contents).not.toContain(`<${upstreamComponent}`);
      }
    },
  );
});
