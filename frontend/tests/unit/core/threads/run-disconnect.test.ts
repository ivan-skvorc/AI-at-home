/**
 * Concurrent chats: a run must outlive the SSE consumer that started it.
 *
 * Leaving a chat tears its stream down, and the Gateway cancels a run on
 * client disconnect unless the run request says otherwise
 * (`on_disconnect` defaults to `"cancel"` in `backend/app/gateway/run_models.py`).
 * Without `onDisconnect: "continue"` on every submit path, walking away from a
 * chat to write a prompt in another one kills the answer you walked away to
 * wait for.
 *
 * This is asserted rather than left to the SDK's own default, which derives
 * `onDisconnect` from `streamResumable` — a flag `sanitizeRunStreamOptions`
 * strips before the request reaches the Gateway.
 */
import { afterEach, expect, rs, test } from "@rstest/core";

type SubmitCall = [unknown, Record<string, unknown> | undefined];

async function captureSubmitOptions(): Promise<SubmitCall[]> {
  const submitCalls: SubmitCall[] = [];

  rs.resetModules();
  rs.doMock("react", () => ({
    useCallback: <T extends (...args: never[]) => unknown>(callback: T) =>
      callback,
    useEffect: () => undefined,
    useMemo: <T>(factory: () => T) => factory(),
    useRef: <T>(initialValue: T) => ({ current: initialValue }),
    useState: <T>(initialValue: T | (() => T)) => [
      typeof initialValue === "function"
        ? (initialValue as () => T)()
        : initialValue,
      rs.fn(),
    ],
  }));
  rs.doMock("@tanstack/react-query", () => ({
    useInfiniteQuery: () => ({
      data: { pages: [] },
      error: null,
      fetchNextPage: rs.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      isLoading: false,
    }),
    useMutation: rs.fn(),
    useQuery: rs.fn(),
    useQueryClient: () => ({
      invalidateQueries: rs.fn(),
      setQueriesData: rs.fn(),
    }),
  }));
  rs.doMock("@langchain/langgraph-sdk/react", () => ({
    useStream: () => ({
      isLoading: false,
      messages: [],
      stop: rs.fn(),
      submit: async (
        values: unknown,
        options?: Record<string, unknown>,
      ): Promise<void> => {
        submitCalls.push([values, options]);
      },
      values: { title: "", messages: [] },
    }),
  }));
  rs.doMock("@/core/api", () => ({
    getAPIClient: () => ({}),
  }));
  rs.doMock("@/core/i18n/hooks", () => ({
    useI18n: () => ({
      t: {
        pages: { newChat: "New chat" },
        uploads: { uploadingFiles: "Uploading files" },
      },
    }),
  }));
  rs.doMock("@/core/tasks/context", () => ({
    useSubtaskContext: () => ({
      tasksRef: { current: {} },
      setTasks: rs.fn(),
    }),
    useUpdateSubtask: () => rs.fn(),
  }));

  const { useThreadStream } = await import("@/core/threads/hooks");
  let sendMessage!: (
    threadId: string,
    message: { text: string; files: never[] },
  ) => Promise<void>;
  function ThreadStreamCapture() {
    ({ sendMessage } = useThreadStream({
      context: { mode: "flash" },
      isMock: true,
    } as never));
    return null;
  }
  ThreadStreamCapture();

  await sendMessage("thread-1", { text: "Second prompt", files: [] });

  return submitCalls;
}

afterEach(() => {
  rs.doUnmock("react");
  rs.doUnmock("@tanstack/react-query");
  rs.doUnmock("@langchain/langgraph-sdk/react");
  rs.doUnmock("@/core/api");
  rs.doUnmock("@/core/i18n/hooks");
  rs.doUnmock("@/core/tasks/context");
  rs.resetModules();
});

test("a submitted run keeps going when its stream disconnects", async () => {
  const submitCalls = await captureSubmitOptions();

  expect(submitCalls).toHaveLength(1);
  expect(submitCalls[0]?.[1]).toMatchObject({
    threadId: "thread-1",
    onDisconnect: "continue",
  });
});
