import { CODES, DEADLINE_MS, ModelError } from "./limits.js";

/**
 * Prepare one file in its own Worker. The Worker is terminated when it answers,
 * when the deadline passes and when the signal aborts, so no parser outlives
 * the preview that asked for it. It receives a private copy of the bytes: the
 * host's buffer stays whole for the download fallback.
 */
export function prepareInWorker(
  bytes,
  kind,
  signal,
  {
    timeoutMs = DEADLINE_MS,
    workerFactory = () =>
      new Worker(new URL("./model-worker.mjs", import.meta.url), { type: "module" }),
  } = {},
) {
  if (signal.aborted) return Promise.reject(abortReason(signal));
  return new Promise((resolve, reject) => {
    let worker;
    let timer;
    let settled = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      if (worker) {
        worker.onmessage = worker.onerror = worker.onmessageerror = null;
        worker.terminate();
      }
      if (error) reject(error);
      else resolve(result);
    };
    const abort = () => finish(abortReason(signal));
    try {
      worker = workerFactory();
      signal.addEventListener("abort", abort, { once: true });
      timer = setTimeout(() => finish(new ModelError("timeout")), timeoutMs);
      worker.onmessage = ({ data }) => {
        if (data && Object.hasOwn(data, "result")) finish(null, data.result);
        else finish(new ModelError(CODES.includes(data?.error) ? data.error : "worker-failed"));
      };
      worker.onerror = (event) => {
        event.preventDefault?.();
        finish(new ModelError("worker-failed"));
      };
      worker.onmessageerror = () => finish(new ModelError("worker-failed"));
      const copy = bytes.slice(0);
      worker.postMessage({ bytes: copy, kind }, [copy]);
    } catch {
      finish(new ModelError("worker-failed"));
    }
  });
}

function abortReason(signal) {
  return signal.reason instanceof Error && signal.reason.name === "AbortError"
    ? signal.reason
    : new DOMException("Preview cancelled", "AbortError");
}
