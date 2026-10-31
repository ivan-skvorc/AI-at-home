import { afterEach, describe, expect, it } from "@rstest/core";

import { LOCAL_SETTINGS_KEY, type LocalSettings } from "@/core/settings/local";
import { buildRunContext } from "@/core/threads/hooks";
import { ULTRACODE_NAMESPACE } from "@/core/threads/ultracode";

afterEach(() => {
  window.localStorage.clear();
});

describe("Double Plus Ultracode on submit", () => {
  it("reads the Settings limits when the message is sent", () => {
    window.localStorage.setItem(
      LOCAL_SETTINGS_KEY,
      JSON.stringify({ ultracode: { maxAgents: 5, maxParallel: 2 } }),
    );
    const context = buildRunContext({
      settings: {
        mode: "ultracode",
        model_name: "gemma4",
      } as unknown as LocalSettings["context"],
      threadId: "t-1",
    });
    expect(context.plugin_options).toEqual({
      [ULTRACODE_NAMESPACE]: {
        mode: "ultracode",
        max_agents: 5,
        max_parallel: 2,
      },
    });
    expect(context.subagent_enabled).toBe(true);
  });
});
