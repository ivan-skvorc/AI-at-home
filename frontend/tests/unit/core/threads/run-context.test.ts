import { afterEach, describe, expect, it, rs } from "@rstest/core";

import type { LocalSettings } from "@/core/settings";
import { buildRunContext } from "@/core/threads/hooks";

const settings = {
  mode: "pro",
  model_name: "gemma4",
  reasoning_effort: undefined,
} as unknown as LocalSettings["context"];

describe("buildRunContext", () => {
  it("applies a one-turn model without mutating saved context", () => {
    const before = { ...settings };
    const current = buildRunContext({
      settings,
      threadId: "t-1",
      extraContext: { model_name: "child-choice" },
    });
    expect(current.model_name).toBe("child-choice");
    expect(settings).toEqual(before);
    expect(buildRunContext({ settings, threadId: "t-1" }).model_name).toBe(
      "gemma4",
    );
  });
  it("passes child-only selection separately from the parent model", () => {
    // Fork: a child selection only travels on a run that can delegate (the
    // chat page refuses a task-scoped choice outside Ultra), so this is Ultra.
    const context = buildRunContext({
      settings: { ...settings, mode: "ultra" },
      threadId: "t-1",
      extraContext: { subagent_model_name: "child-choice" },
    });
    expect(context.model_name).toBe("gemma4");
    expect(context.subagent_model_name).toBe("child-choice");
  });
  it("lets a one-run child choice outrank the thread's subagent dropdown", () => {
    const context = buildRunContext({
      settings: {
        ...settings,
        mode: "ultra",
        subagent_model_name: "dropdown-choice",
      },
      threadId: "t-1",
      extraContext: { subagent_model_name: "child-choice" },
    });
    expect(context.subagent_model_name).toBe("child-choice");
  });
  it("drops a leftover subagent dropdown value on a run that cannot delegate", () => {
    // The backend rejects a child selection without subagents, so a value kept
    // from an earlier Ultra turn would fail every later Pro turn in the thread.
    const ultra = buildRunContext({
      settings: { ...settings, mode: "ultra", subagent_model_name: "kimi" },
      threadId: "t-1",
    });
    expect(ultra.subagent_model_name).toBe("kimi");
    const pro = buildRunContext({
      settings: { ...settings, mode: "pro", subagent_model_name: "kimi" },
      threadId: "t-1",
    });
    expect(pro.subagent_model_name).toBeUndefined();
    expect(JSON.parse(JSON.stringify(pro))).not.toHaveProperty(
      "subagent_model_name",
    );
  });
  it("sends attached references as a plain string[] under context.conversation_references", () => {
    const context = buildRunContext({
      settings,
      threadId: "t-1",
      extraContext: { agent_name: "writer" },
      conversationReferences: ["source-a", "source-b"],
    });
    expect(context.conversation_references).toEqual(["source-a", "source-b"]);
    expect(context.agent_name).toBe("writer");
    expect(context.thread_id).toBe("t-1");
    expect(context.is_plan_mode).toBe(true);
  });

  it("omits the key when nothing is attached, including on the replay path", () => {
    expect(
      "conversation_references" in
        buildRunContext({ settings, threadId: "t-1" }),
    ).toBe(false);
    expect(
      "conversation_references" in
        buildRunContext({
          settings,
          threadId: "t-1",
          conversationReferences: [],
        }),
    ).toBe(false);
  });

  it("never forwards a stray conversation_references key from local settings", () => {
    const stale = {
      ...settings,
      conversation_references: ["stale-source"],
    } as unknown as LocalSettings["context"];
    expect(
      "conversation_references" in
        buildRunContext({ settings: stale, threadId: "t-1" }),
    ).toBe(false);
    expect(
      buildRunContext({
        settings: stale,
        threadId: "t-1",
        conversationReferences: ["source-a"],
      }).conversation_references,
    ).toEqual(["source-a"]);
  });

  it("copies the list so later mutation of the caller's array cannot change the request", () => {
    const references = ["source-a"];
    const context = buildRunContext({
      settings,
      threadId: "t-1",
      conversationReferences: references,
    });
    references.push("source-b");
    expect(context.conversation_references).toEqual(["source-a"]);
  });
});

describe("buildRunContext client_timezone", () => {
  afterEach(() => {
    rs.restoreAllMocks();
  });

  function mockResolvedTimeZone(timeZone: string | (() => never)) {
    const RealDateTimeFormat = Intl.DateTimeFormat;
    rs.spyOn(Intl, "DateTimeFormat").mockImplementation(((
      ...args: ConstructorParameters<typeof Intl.DateTimeFormat>
    ) => {
      const real = new RealDateTimeFormat(...args);
      return {
        ...real,
        resolvedOptions: () => {
          if (typeof timeZone === "function") {
            return timeZone();
          }
          return { ...real.resolvedOptions(), timeZone };
        },
      };
    }) as unknown as typeof Intl.DateTimeFormat);
  }

  it("sends the browser's zone for the scheduled-task default", () => {
    mockResolvedTimeZone("Asia/Shanghai");
    expect(buildRunContext({ settings, threadId: "t-1" }).client_timezone).toBe(
      "Asia/Shanghai",
    );
  });

  it("omits the key when the browser cannot tell", () => {
    mockResolvedTimeZone(() => {
      throw new RangeError("unsupported");
    });
    expect(
      "client_timezone" in buildRunContext({ settings, threadId: "t-1" }),
    ).toBe(false);
  });

  it("omits the key for an empty zone", () => {
    mockResolvedTimeZone("");
    expect(
      "client_timezone" in buildRunContext({ settings, threadId: "t-1" }),
    ).toBe(false);
  });
});
