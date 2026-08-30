/**
 * Microphone capture for the server-transcription tier.
 *
 * Thin on purpose: open a stream, collect chunks, hand back one blob. The
 * transport lives in `server-transcription.ts` and the tier decision in
 * `speech-recognition.ts`, so this module can be exercised with fake
 * `MediaRecorder` and `getUserMedia` implementations.
 *
 * The one rule worth stating: **the microphone track is always stopped.**
 * A live `MediaStreamTrack` keeps the browser's recording indicator lit, and
 * on a phone that reads as an app secretly listening. Every exit path —
 * success, failure, or abandonment — releases it.
 */

import {
  pickRecordingMimeType,
  recordingFileName,
} from "@/core/voice-input/server-transcription";

export type RecorderLike = {
  start: () => void;
  stop: () => void;
  ondataavailable: ((event: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  onerror: ((event: unknown) => void) | null;
  state?: string;
};

export type RecorderDeps = {
  getUserMedia: (constraints: {
    audio: boolean;
  }) => Promise<{ getTracks: () => { stop: () => void }[] }>;
  createRecorder: (
    stream: unknown,
    options: { mimeType?: string },
  ) => RecorderLike;
  isTypeSupported: (type: string) => boolean;
};

export function browserRecorderDeps(): RecorderDeps {
  return {
    getUserMedia: (constraints) =>
      navigator.mediaDevices.getUserMedia(constraints) as unknown as Promise<{
        getTracks: () => { stop: () => void }[];
      }>,
    createRecorder: (stream, options) =>
      new MediaRecorder(
        stream as MediaStream,
        options.mimeType ? { mimeType: options.mimeType } : undefined,
      ) as unknown as RecorderLike,
    isTypeSupported: (type) => MediaRecorder.isTypeSupported(type),
  };
}

export type ActiveRecording = {
  /** Stop capture and resolve with what was recorded. */
  stop: () => Promise<{ blob: Blob; fileName: string }>;
  /** Abandon the recording and release the microphone without transcribing. */
  cancel: () => void;
};

/**
 * Begin recording. The returned handle owns the microphone until one of its
 * two methods is called; callers must always call one.
 */
export async function startRecording(
  deps: RecorderDeps = browserRecorderDeps(),
): Promise<ActiveRecording> {
  const stream = await deps.getUserMedia({ audio: true });
  const releaseMicrophone = () => {
    for (const track of stream.getTracks()) {
      try {
        track.stop();
      } catch {
        // A track that already ended is not an error worth surfacing.
      }
    }
  };

  let recorder: RecorderLike;
  const mimeType = pickRecordingMimeType(deps.isTypeSupported);
  try {
    recorder = deps.createRecorder(stream, mimeType ? { mimeType } : {});
  } catch (error) {
    // Constructing the recorder can throw on an unsupported container; the
    // stream is already open at this point, so it has to be released here.
    releaseMicrophone();
    throw error;
  }

  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event?.data) {
      chunks.push(event.data);
    }
  };

  let settled = false;
  const stopped = new Promise<{ blob: Blob; fileName: string }>(
    (resolve, reject) => {
      recorder.onstop = () => {
        if (settled) {
          return;
        }
        settled = true;
        releaseMicrophone();
        resolve({
          blob: new Blob(chunks, mimeType ? { type: mimeType } : undefined),
          fileName: recordingFileName(mimeType),
        });
      };
      recorder.onerror = (event) => {
        if (settled) {
          return;
        }
        settled = true;
        releaseMicrophone();
        reject(
          (event as { error?: Error })?.error ?? new Error("Recording failed."),
        );
      };
    },
  );

  recorder.start();

  return {
    stop: () => {
      try {
        recorder.stop();
      } catch (error) {
        if (!settled) {
          settled = true;
          releaseMicrophone();
        }
        return Promise.reject(
          error instanceof Error ? error : new Error(String(error)),
        );
      }
      return stopped;
    },
    cancel: () => {
      settled = true;
      try {
        recorder.stop();
      } catch {
        // Already stopped; the microphone still needs releasing below.
      }
      releaseMicrophone();
    },
  };
}
