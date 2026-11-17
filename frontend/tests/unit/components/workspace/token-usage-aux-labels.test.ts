import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, test } from "@rstest/core";

import { auxCategoryLabel } from "@/components/workspace/token-usage-indicator";
import { enUS, zhCN } from "@/core/i18n/locales";

/**
 * Every auxiliary spend row the chat header can show has a label.
 *
 * The category is a free-form string from the backend, and an unknown one
 * falls back to its own name — still money spent, just shown as a raw
 * snake_case key. Nothing fails when a new backend sink lands without a
 * label, so this reads the backend's own list (`CHAT_AUX_CATEGORIES` in
 * `deerflow/runtime/aux_usage.py`) and checks each one in both locales.
 */

const AUX_USAGE_PY = path.resolve(
  __dirname,
  "../../../../../backend/packages/harness/deerflow/runtime/aux_usage.py",
);

function backendChatAuxCategories(): string[] {
  const source = readFileSync(AUX_USAGE_PY, "utf8");
  const constants = new Map<string, string>();
  for (const match of source.matchAll(
    /^(AUX_CATEGORY_\w+)\s*=\s*"([^"]+)"/gm,
  )) {
    constants.set(match[1]!, match[2]!);
  }
  const tuple = /CHAT_AUX_CATEGORIES[^=]*=\s*\(([\s\S]*?)\)/.exec(source);
  expect(tuple).not.toBeNull();
  return tuple![1]!
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((name) => {
      const value = constants.get(name);
      expect(value, `${name} is defined in aux_usage.py`).toBeDefined();
      return value!;
    });
}

describe("aux spend labels", () => {
  const categories = backendChatAuxCategories();

  test("the backend list includes the clean-up pass", () => {
    expect(categories).toContain("organize");
  });

  test.each([
    ["en-US", enUS],
    ["zh-CN", zhCN],
  ] as const)("every chat aux category has a %s label", (_locale, t) => {
    for (const category of categories) {
      const label = auxCategoryLabel(category, t);
      expect(label, category).not.toBe(category);
      expect(label.trim(), category).not.toBe("");
    }
  });

  test("the clean-up pass reads as clean-up, and an unknown sink keeps its name", () => {
    expect(auxCategoryLabel("organize", enUS)).toBe("Chat clean-up");
    expect(auxCategoryLabel("brand_new_sink", enUS)).toBe("brand_new_sink");
  });
});
