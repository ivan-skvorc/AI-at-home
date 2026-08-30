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
  ])("lets ModelSelectorName stretch in %s", (relativePath) => {
    const classes = selectedModelWrapperClasses(relativePath);

    expect(classes).toEqual(
      expect.arrayContaining(["flex", "min-w-0", "flex-col"]),
    );
    expect(classes).not.toContain("items-start");
  });
});
