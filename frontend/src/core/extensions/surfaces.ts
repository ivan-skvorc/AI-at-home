import type {
  PluginSurface,
  RunStreamEvent,
  SurfaceComposerControlsHandle,
  SurfaceComposerControlsOptions,
  SurfaceContext,
  SurfaceThreadFileEntry,
} from "./contracts";

/** The host side of `threadFiles`: every read takes the page-bound signal. */
export type HostThreadFiles = {
  list: (
    threadId: string,
    virtualPath: string,
    signal: AbortSignal,
  ) => Promise<SurfaceThreadFileEntry[]>;
  read: (
    threadId: string,
    virtualPath: string,
    signal: AbortSignal,
    maxBytes?: number,
  ) => Promise<ArrayBuffer>;
  url: (threadId: string, virtualPath: string, download?: boolean) => string;
};

/** The host side of `composerControls`; the page wrapper owns lifetime and errors. */
export type HostComposerControls = {
  mount: (
    element: HTMLElement,
    options: {
      storageKey?: unknown;
      onChange?: SurfaceComposerControlsOptions["onChange"];
    },
  ) => SurfaceComposerControlsHandle;
};

/** Shadow DOM scopes styles, not privileges: packages are administrator-trusted code. */
export function mountSurface(
  container: HTMLElement,
  surface: PluginSurface,
  context: Omit<
    SurfaceContext,
    | "signal"
    | "openConversation"
    | "joinRunStream"
    | "threadFiles"
    | "composerControls"
  > & {
    openConversation?: (threadId: string, signal: AbortSignal) => Promise<void>;
    joinRunStream?: (
      threadId: string,
      runId: string,
      signal: AbortSignal,
    ) => AsyncIterable<RunStreamEvent>;
    threadFiles?: HostThreadFiles;
    composerControls?: HostComposerControls;
  },
  onError: () => void,
) {
  const abort = new AbortController();
  const bound = (signal?: AbortSignal) =>
    signal ? AbortSignal.any([abort.signal, signal]) : abort.signal;
  const files = context.threadFiles;
  const controls = context.composerControls;
  // Every mounted set of composer controls ends with the page, disposed or not.
  const mountedControls = new Set<() => void>();
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
    for (const dispose of [...mountedControls]) dispose();
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
      threadFiles: files
        ? {
            async list(threadId, virtualPath, options) {
              abort.signal.throwIfAborted();
              const entries = await files.list(
                threadId,
                virtualPath,
                bound(options?.signal),
              );
              abort.signal.throwIfAborted();
              return entries;
            },
            async read(threadId, virtualPath, options) {
              abort.signal.throwIfAborted();
              const bytes = await files.read(
                threadId,
                virtualPath,
                bound(options?.signal),
                options?.maxBytes,
              );
              abort.signal.throwIfAborted();
              return bytes;
            },
            url: (threadId, virtualPath, options) =>
              files.url(threadId, virtualPath, options?.download === true),
          }
        : undefined,
      composerControls: controls
        ? {
            mount(element, options) {
              abort.signal.throwIfAborted();
              if (!(element instanceof HTMLElement))
                throw new TypeError("composerControls needs an HTMLElement");
              let disposed = false;
              const onChange = options?.onChange;
              const handle = controls.mount(element, {
                storageKey: options?.storageKey,
                onChange:
                  typeof onChange === "function"
                    ? (runContext) => {
                        if (disposed || abort.signal.aborted) return;
                        try {
                          onChange(runContext);
                        } catch {
                          /* A plugin callback cannot break the host controls. */
                        }
                      }
                    : undefined,
              });
              const dispose = () => {
                if (disposed) return;
                disposed = true;
                mountedControls.delete(dispose);
                try {
                  handle.dispose();
                } catch {
                  /* Contain host cleanup failures. */
                }
              };
              mountedControls.add(dispose);
              return { runContext: () => handle.runContext(), dispose };
            },
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
