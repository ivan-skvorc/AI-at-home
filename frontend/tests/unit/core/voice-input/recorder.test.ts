import { describe, expect, it } from "@rstest/core";

import {
  startRecording,
  type RecorderDeps,
  type RecorderLike,
} from "@/core/voice-input/recorder";

function makeDeps(
  overrides: Partial<RecorderDeps> & {
    failCreate?: boolean;
    /** When false, stop() does not fire onstop, so a test can drive onerror. */
    autoStop?: boolean;
  } = {},
) {
  const autoStop = overrides.autoStop ?? true;
  const stopped: string[] = [];
  const tracks = [
    { stop: () => stopped.push("a") },
    { stop: () => stopped.push("b") },
  ];
  let recorder: RecorderLike | null = null;

  const deps: RecorderDeps = {
    getUserMedia: async () => ({ getTracks: () => tracks }),
    createRecorder: () => {
      if (overrides.failCreate) {
        throw new Error("unsupported container");
      }
      recorder = {
        start: () => undefined,
        stop: () => {
          if (autoStop) {
            recorder?.onstop?.();
          }
        },
        ondataavailable: null,
        onstop: null,
        onerror: null,
      };
      return recorder;
    },
    isTypeSupported: (type) => type === "audio/webm;codecs=opus",
    ...(overrides.getUserMedia ? { getUserMedia: overrides.getUserMedia } : {}),
    ...(overrides.createRecorder
      ? { createRecorder: overrides.createRecorder }
      : {}),
    ...(overrides.isTypeSupported
      ? { isTypeSupported: overrides.isTypeSupported }
      : {}),
  };

  return { deps, stopped, getRecorder: () => recorder };
}

describe("microphone recording", () => {
  it("returns the recorded audio and releases the microphone", async () => {
    const { deps, stopped, getRecorder } = makeDeps();
    const recording = await startRecording(deps);

    getRecorder()?.ondataavailable?.({ data: new Blob(["chunk"]) });
    const result = await recording.stop();

    expect(result.fileName).toBe("speech.webm");
    expect(result.blob.type).toBe("audio/webm;codecs=opus");
    expect(stopped).toEqual(["a", "b"]);
  });

  it("releases the microphone when the recorder errors", async () => {
    const { deps, stopped, getRecorder } = makeDeps({ autoStop: false });
    const recording = await startRecording(deps);

    const failed = recording.stop();
    getRecorder()?.onerror?.({ error: new Error("device lost") });

    await expect(failed).rejects.toThrow("device lost");
    expect(stopped).toEqual(["a", "b"]);
  });

  it("releases the microphone when the recorder cannot be constructed", async () => {
    const { deps, stopped } = makeDeps({ failCreate: true });
    await expect(startRecording(deps)).rejects.toThrow("unsupported container");
    // The stream was already open when construction failed.
    expect(stopped).toEqual(["a", "b"]);
  });

  it("releases the microphone when the recording is abandoned", async () => {
    // A live track keeps the browser's recording indicator lit, which on a
    // phone reads as an app secretly listening.
    const { deps, stopped } = makeDeps();
    const recording = await startRecording(deps);

    recording.cancel();

    expect(stopped).toEqual(["a", "b"]);
  });

  it("falls back to no explicit container when none is supported", async () => {
    const { deps, getRecorder } = makeDeps({ isTypeSupported: () => false });
    const recording = await startRecording(deps);
    getRecorder()?.ondataavailable?.({ data: new Blob(["chunk"]) });

    const result = await recording.stop();
    expect(result.fileName).toBe("speech.webm");
  });
});
