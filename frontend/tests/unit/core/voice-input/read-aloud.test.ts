import { describe, expect, it } from "@rstest/core";

import {
  speakText,
  toSpeakableText,
  VOICE_SPEAK_ENDPOINT,
} from "@/core/voice-input/read-aloud";

describe("toSpeakableText", () => {
  it("reads the prose and drops code, link targets and markup", () => {
    const markdown = [
      "## Result",
      "",
      "The **answer** is [here](https://example.com/x) and `inline`.",
      "",
      "```python",
      "print('not read aloud')",
      "```",
      "- first item",
      "> quoted ![chart](/mnt/user-data/outputs/chart.png)",
    ].join("\n");
    const text = toSpeakableText(markdown, 1000);
    expect(text).toContain("The answer is here and inline.");
    expect(text).toContain("first item");
    expect(text).toContain("quoted chart");
    expect(text).not.toContain("print(");
    expect(text).not.toContain("https://");
    expect(text).not.toContain("#");
  });

  it("never exceeds the Gateway's limit", () => {
    expect(toSpeakableText("word ".repeat(500), 40).length).toBeLessThanOrEqual(
      40,
    );
  });
});

describe("speakText", () => {
  it("posts the text and fails loudly on a refusal", async () => {
    const calls: [string, RequestInit][] = [];
    const audio = new Blob(["mp3"], { type: "audio/mpeg" });
    const ok = (async (url: string, init: RequestInit) => {
      calls.push([url, init]);
      return { ok: true, status: 200, blob: async () => audio };
    }) as unknown as typeof fetch;
    expect(await speakText("Hello", { fetchImpl: ok })).toBe(audio);
    expect(calls[0]?.[0]).toBe(VOICE_SPEAK_ENDPOINT);
    expect(JSON.parse(calls[0]?.[1].body as string)).toEqual({ text: "Hello" });

    const refused = (async () => ({
      ok: false,
      status: 503,
    })) as unknown as typeof fetch;
    await expect(speakText("Hello", { fetchImpl: refused })).rejects.toThrow(
      "503",
    );
  });
});
