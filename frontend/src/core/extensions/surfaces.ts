import type {
  PluginSurface,
  RunStreamEvent,
  SurfaceContext,
} from "./contracts";

/** Shadow DOM scopes styles, not privileges: packages are administrator-trusted code. */
export function mountSurface(
  container: HTMLElement,
  surface: PluginSurface,
  context: Omit<
    SurfaceContext,
    "signal" | "openConversation" | "joinRunStream"
  > & {
    openConversation?: (threadId: string, signal: AbortSignal) => Promise<void>;
    joinRunStream?: (
      threadId: string,
      runId: string,
      signal: AbortSignal,
    ) => AsyncIterable<RunStreamEvent>;
  },
  onError: () => void,
) {
  const abort = new AbortController();
  const shadow =
    container.shadowRoot ?? container.attachShadow({ mode: "open" });
  const root = document.createElement("div");
  // A full-layout page owns the whole area; its root must not collapse to content height.
  if (surface.layout === "full") root.style.height = "100%";
  shadow.replaceChildren(root);
  let controller: { dispose: () => void } | undefined;
  const cleanup = () => {
    if (abort.signal.aborted) return;
    abort.abort();
    try {
      controller?.dispose();
    } catch {
      /* Contain plugin cleanup failures. */
    }
    root.remove();
  };
  try {
    controller = surface.mount(root, {
      ...context,
      signal: abort.signal,
      requestBackend: context.requestBackend
        ? async (path, options) => {
            abort.signal.throwIfAborted();
            const response = await context.requestBackend!(path, {
              ...options,
              signal: options?.signal
                ? AbortSignal.any([abort.signal, options.signal])
                : abort.signal,
            });
            abort.signal.throwIfAborted();
            return response;
          }
        : undefined,
      openConversation: context.openConversation
        ? async (threadId) => {
            abort.signal.throwIfAborted();
            await context.openConversation!(threadId, abort.signal);
          }
        : undefined,
      joinRunStream: context.joinRunStream
        ? async function* (threadId, runId, options) {
            abort.signal.throwIfAborted();
            yield* context.joinRunStream!(
              threadId,
              runId,
              options?.signal
                ? AbortSignal.any([abort.signal, options.signal])
                : abort.signal,
            );
          }
        : undefined,
      async callBackend(action, payload) {
        abort.signal.throwIfAborted();
        const result = await context.callBackend(action, payload);
        abort.signal.throwIfAborted();
        return result;
      },
    });
    if (typeof controller?.dispose !== "function")
      throw new Error("Invalid surface controller");
  } catch {
    cleanup();
    onError();
  }
  return cleanup;
}
