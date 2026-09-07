/**
 * The two halves of "this chat remembers what it was running with".
 *
 * `thread-workflow.test.ts` covers the pure model; this covers the hook that
 * decides *when* to read and write it, which is where the bugs were:
 *
 * - a chat opened anywhere this browser had not been showed the app default
 *   instead of the model the conversation had been using, and
 * - a brand-new chat lost its selection the moment the backend assigned it a
 *   real thread id, because every per-conversation key is stored under that id
 *   and the draft was written under a client-side placeholder.
 */
import { beforeEach, describe, expect, rs, test } from "@rstest/core";
import { act, render } from "@testing-library/react";
import { useState } from "react";

const patches = rs.hoisted(() => ({
  calls: [] as Array<{ threadId: string; metadata: Record<string, unknown> }>,
  fail: false,
}));

rs.mock("@/core/threads/api", () => ({
  patchThreadMetadata: async (
    threadId: string,
    metadata: Record<string, unknown>,
  ) => {
    patches.calls.push({ threadId, metadata });
    if (patches.fail) {
      throw new Error("gateway down");
    }
    return { thread_id: threadId, metadata };
  },
}));

const { useThreadWorkflowMemory } =
  await import("@/components/workspace/chats/use-thread-workflow-memory");
const { THREAD_WORKFLOW_METADATA_KEY } =
  await import("@/core/threads/thread-workflow");

type Context = Record<string, unknown>;

let applied: Array<Record<string, string>> = [];
let promote: ((threadId: string, context: never) => void) | null = null;
let setContextExternally: ((context: Context) => void) | null = null;

function Harness({
  threadId,
  metadata,
  initialContext,
  isNewThread = false,
}: {
  threadId: string;
  metadata: Record<string, unknown> | null | undefined;
  initialContext: Context;
  isNewThread?: boolean;
}) {
  const [context, setContext] = useState<Context>(initialContext);
  setContextExternally = setContext;
  const { recordOnPromotion } = useThreadWorkflowMemory({
    threadId,
    isNewThread,
    isMock: false,
    metadata,
    context: context as never,
    applyWorkflow: (workflow) => {
      applied.push(workflow as Record<string, string>);
    },
  });
  promote = recordOnPromotion as (threadId: string, context: never) => void;
  return null;
}

beforeEach(() => {
  patches.calls = [];
  patches.fail = false;
  applied = [];
  promote = null;
  setContextExternally = null;
  window.localStorage.clear();
});

describe("seeding from the conversation's own record", () => {
  test("a chat this browser has never seen adopts its recorded selection", async () => {
    await act(async () => {
      render(
        <Harness
          threadId="thread-a"
          metadata={{
            [THREAD_WORKFLOW_METADATA_KEY]: {
              model_name: "claude-opus-5",
              mode: "ultra",
              subagent_model_name: "ollama:llama3",
            },
          }}
          initialContext={{}}
        />,
      );
    });

    expect(applied).toEqual([
      {
        model_name: "claude-opus-5",
        mode: "ultra",
        subagent_model_name: "ollama:llama3",
      },
    ]);
  });

  test("a chat with no record is left alone", async () => {
    await act(async () => {
      render(<Harness threadId="thread-a" metadata={{}} initialContext={{}} />);
    });

    expect(applied).toEqual([]);
  });

  test("metadata that has not loaded yet does not seed", async () => {
    // Seeding from `undefined` would read "no record" and permanently mark the
    // thread as seeded, so the real record would never be applied.
    await act(async () => {
      render(
        <Harness
          threadId="thread-a"
          metadata={undefined}
          initialContext={{}}
        />,
      );
    });

    expect(applied).toEqual([]);
    expect(patches.calls).toEqual([]);
  });
});

describe("recording the selection back onto the conversation", () => {
  test("a change is written to the thread", async () => {
    await act(async () => {
      render(
        <Harness
          threadId="thread-a"
          metadata={{}}
          initialContext={{ model_name: "claude-opus-5" }}
        />,
      );
    });

    expect(patches.calls).toEqual([
      {
        threadId: "thread-a",
        metadata: {
          [THREAD_WORKFLOW_METADATA_KEY]: { model_name: "claude-opus-5" },
        },
      },
    ]);

    await act(async () => {
      setContextExternally?.({ model_name: "gpt-5", mode: "pro" });
    });

    expect(patches.calls).toHaveLength(2);
    expect(patches.calls[1]?.metadata).toEqual({
      [THREAD_WORKFLOW_METADATA_KEY]: { model_name: "gpt-5", mode: "pro" },
    });
  });

  test("re-reporting the same selection writes nothing", async () => {
    // The composer re-reports its context on every render pass that touches it.
    await act(async () => {
      render(
        <Harness
          threadId="thread-a"
          metadata={{
            [THREAD_WORKFLOW_METADATA_KEY]: { model_name: "claude-opus-5" },
          }}
          initialContext={{ model_name: "claude-opus-5" }}
        />,
      );
    });

    await act(async () => {
      setContextExternally?.({ model_name: "claude-opus-5" });
    });

    expect(patches.calls).toEqual([]);
  });

  test("a failed write is retried on the next change, not swallowed forever", async () => {
    patches.fail = true;
    await act(async () => {
      render(
        <Harness
          threadId="thread-a"
          metadata={{}}
          initialContext={{ model_name: "claude-opus-5" }}
        />,
      );
    });
    expect(patches.calls).toHaveLength(1);

    patches.fail = false;
    await act(async () => {
      setContextExternally?.({ model_name: "claude-opus-5" });
    });

    // Same selection, but the last write never landed, so it is sent again
    // rather than being suppressed as "already stored".
    expect(patches.calls).toHaveLength(2);
  });
});

describe("a new chat becoming real", () => {
  test("the draft's selection is recorded under the id the backend assigned", async () => {
    await act(async () => {
      render(
        <Harness
          threadId="client-placeholder"
          metadata={undefined}
          initialContext={{ model_name: "claude-opus-5", mode: "ultra" }}
          isNewThread
        />,
      );
    });
    // Nothing is written for a chat the backend does not have yet.
    expect(patches.calls).toEqual([]);

    await act(async () => {
      promote?.("real-thread-id", {
        model_name: "claude-opus-5",
        mode: "ultra",
      } as never);
    });

    expect(patches.calls).toEqual([
      {
        threadId: "real-thread-id",
        metadata: {
          [THREAD_WORKFLOW_METADATA_KEY]: {
            model_name: "claude-opus-5",
            mode: "ultra",
          },
        },
      },
    ]);
  });

  test("a draft with nothing selected records nothing", async () => {
    await act(async () => {
      render(
        <Harness
          threadId="client-placeholder"
          metadata={undefined}
          initialContext={{}}
          isNewThread
        />,
      );
    });

    await act(async () => {
      promote?.("real-thread-id", {} as never);
    });

    expect(patches.calls).toEqual([]);
  });
});
