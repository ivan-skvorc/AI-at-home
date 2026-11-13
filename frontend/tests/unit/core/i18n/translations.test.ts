import { describe, expect, it } from "@rstest/core";

import { loadTranslations } from "@/core/i18n/translations";

describe("core copy loading", () => {
  it("loads only the requested overseas and domestic copy", async () => {
    const [english, chinese] = await Promise.all([
      loadTranslations("en-US"),
      loadTranslations("zh-CN"),
    ]);
    expect(english.inputBox.disclaimer).toBe(
      "DeerFlow is AI and can make mistakes",
    );
    expect(chinese.inputBox.disclaimer).toBe(
      "内容由AI生成，重要信息请务必核查",
    );
    expect(english.channels.descriptions.buzz).toBe(
      "Buzz channels and direct messages through your DeerFlow agent.",
    );
    expect(chinese.channels.descriptions.buzz).toBe(
      "通过 DeerFlow 智能体接收 Buzz 频道消息和私聊。",
    );
    expect(chinese.knowledge.scope.title).toBe("知识库范围");
  });
});

describe("artifacts and files labels", () => {
  it("names the Files view differently from the Artifacts view in every locale", async () => {
    // The two panel tabs and the two header buttons sit side by side; the same
    // word on both left Chinese readers with two identical "文件" tabs.
    for (const locale of ["en-US", "zh-CN"] as const) {
      const copy = await loadTranslations(locale);
      expect(copy.threadFiles.title).not.toBe(copy.common.artifacts);
      expect(copy.threadFiles.showFiles).not.toBe(copy.common.showArtifacts);
      expect(copy.threadFiles.treeLabel).not.toBe(copy.common.showArtifacts);
    }
  });
});
