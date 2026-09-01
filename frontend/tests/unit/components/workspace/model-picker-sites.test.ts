import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

/**
 * Structural guards for the one shared model picker (fork feature, FORK.md §8).
 *
 * Two failures live here, and both are silent in their own way.
 *
 * **1. A picker that stops being findable.** E2E specs used to locate these
 * pickers with `getByRole("combobox")` — the ARIA role of whatever primitive was
 * underneath (Radix `Select`). Replacing that primitive with the shared dialog +
 * cmdk picker deleted the role, and every spec driving a picker died on a 30s
 * timeout against a locator matching nothing. Nothing in the *product* was
 * broken; the specs were coupled to an implementation detail. `ModelSelect`
 * therefore publishes its own contract — `data-slot="model-select"` — and specs
 * target that. This test keeps the contract from being dropped by a refactor,
 * and it runs in milliseconds instead of the six minutes the e2e job takes to
 * tell you the same thing.
 *
 * **2. A screen that quietly goes back to a flat list.** Mapping `models` into
 * `SelectItem`s is not an error: it renders a perfectly good dropdown, in
 * `config.yaml` order, with the price as grey text and no search — which is
 * exactly the state the shared picker exists to end, on that one screen, while
 * every other screen still sorts and groups. Nobody notices until they go
 * looking for a model there.
 */

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");

const read = (relativePath: string) =>
  readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    return statSync(full).isDirectory()
      ? walk(full)
      : full.endsWith(".tsx")
        ? [full]
        : [];
  });
}

describe("the shared model picker's test contract", () => {
  it("publishes a stable data-slot that does not depend on the primitive underneath", () => {
    const source = read("src/components/workspace/model-select.tsx");
    expect(source).toContain('data-slot="model-select"');
  });

  it("is how the e2e specs find a model picker, rather than an ARIA role", () => {
    const specs = walk(path.join(FRONTEND_ROOT, "tests/e2e"));
    const offenders = specs.filter((file) => {
      const source = readFileSync(file, "utf8");
      // A spec that drives a *model* picker by the combobox role is coupled to
      // the primitive. Specs may still use that role for other controls (the
      // artifact file selector, Democracy's grading scale), so the signal is a
      // combobox lookup in a file that also picks a model by name.
      const usesComboboxRole = /getByRole\(\s*["']combobox["']/.test(source);
      const picksAModel =
        source.includes('data-slot="model-select"') ||
        /getByTestId\(\s*["'][\w-]*model[\w-]*["']/.test(source);
      return usesComboboxRole && picksAModel;
    });
    // If this fires, the spec named below is one primitive-swap away from a
    // 30s timeout. Point it at `[data-slot="model-select"]` instead.
    expect(offenders.map((f) => path.relative(FRONTEND_ROOT, f))).toEqual([]);
  });
});

describe("every model-selection site goes through the shared picker", () => {
  // The five sites converted away from a flat `<Select>`, plus the composer and
  // sidecar, which use the `ModelPickerControls`/`ModelPickerList` pair directly
  // because they own their own trigger markup.
  const SHARED_PICKER_USERS = [
    "src/components/workspace/democracy-setup.tsx",
    "src/components/workspace/settings/suggestions-settings-page.tsx",
    "src/components/workspace/settings/subagent-settings-page.tsx",
    "src/components/workspace/agents/agent-generator.tsx",
    "src/components/workspace/agents/agent-settings-dialog.tsx",
  ];

  it.each(SHARED_PICKER_USERS)("%s uses ModelSelect", (file) => {
    expect(read(file)).toContain("ModelSelect");
  });

  it("every picker renders its rows through the shared row component", () => {
    // The row layout — provider first, price pinned to the right edge, weights
    // and window on the second line — is the same silent-drift risk as the flat
    // list above: a site that hand-rolls the markup still renders a perfectly
    // good row, just one that lines up with nothing and drops the local
    // model's size. Anything that drives `ModelPickerList` uses `ModelPickerRow`.
    const components = walk(path.join(FRONTEND_ROOT, "src/components"));
    const offenders = components.filter((file) => {
      const source = readFileSync(file, "utf8");
      return (
        /<ModelPickerList\b/.test(source) && !source.includes("ModelPickerRow")
      );
    });
    expect(offenders.map((f) => path.relative(FRONTEND_ROOT, f))).toEqual([]);
  });

  it("no component builds its own flat list of models", () => {
    const components = walk(path.join(FRONTEND_ROOT, "src/components"));
    const offenders = components.filter((file) => {
      const source = readFileSync(file, "utf8");
      // The shape being banned: iterating the models array straight into a
      // Radix `SelectItem`. `ModelPickerList` renders models too, but through
      // `renderItem`, and never as a `SelectItem`.
      return /\bmodels\s*\.map\(/.test(source) && /<SelectItem\b/.test(source);
    });
    expect(offenders.map((f) => path.relative(FRONTEND_ROOT, f))).toEqual([]);
  });
});
