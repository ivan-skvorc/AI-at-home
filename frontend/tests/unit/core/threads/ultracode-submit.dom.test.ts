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
        max_minutes: 240,
        // The conversation's model, so workflow agents run on it too.
        model: "gemma4",
      },
    });
    expect(context.subagent_enabled).toBe(true);
  });

  it("names the model and the internet switch the run itself is sent with", () => {
    const sent = (
      settings: Record<string, unknown>,
      extraContext?: Record<string, unknown>,
    ) => {
      const context = buildRunContext({
        settings: {
          mode: "double_ultracode",
          ...settings,
        } as unknown as LocalSettings["context"],
        threadId: "t-1",
        extraContext,
      });
      return {
        run: context,
        options: (
          context.plugin_options as Record<string, Record<string, unknown>>
        )[ULTRACODE_NAMESPACE]!,
      };
    };

    // A one-turn model choice replaces the saved one on the run, so it is the
    // one the workflow's agents inherit.
    const oneTurn = sent(
      { model_name: "gemma4", internet_enabled: false },
      { model_name: "one-turn" },
    );
    expect(oneTurn.run.model_name).toBe("one-turn");
    expect(oneTurn.options.model).toBe("one-turn");
    expect(oneTurn.run.internet_enabled).toBe(false);
    expect(oneTurn.options.internet_enabled).toBe(false);

    const defaults = sent({ internet_enabled: true });
    expect(defaults.run.model_name).toBeUndefined();
    expect("model" in defaults.options).toBe(false);
    expect("internet_enabled" in defaults.options).toBe(false);
  });
});
