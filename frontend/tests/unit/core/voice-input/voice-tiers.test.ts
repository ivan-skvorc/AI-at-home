import { describe, expect, it } from "@rstest/core";

import {
  DEFAULT_VOICE_SERVER_CONFIG,
  fetchVoiceServerConfig,
  pickRecordingMimeType,
  recordingFileName,
  supportsAudioRecording,
  transcribeRecording,
  VoiceTranscriptionError,
} from "@/core/voice-input/server-transcription";
import {
  applyOnDeviceProcessing,
  prepareOnDeviceRecognition,
  readOnDeviceAvailability,
  resolveVoiceInputTier,
  supportsOnDeviceRecognition,
  type BrowserSpeechRecognition,
  type SpeechRecognitionConstructor,
} from "@/core/voice-input/speech-recognition";

const ALL_AVAILABLE = {
  onDeviceReady: true,
  serverTranscription: true,
  allowCloudFallback: true,
  recognitionSupported: true,
  recordingSupported: true,
};

describe("voice input tier selection", () => {
  it("prefers on-device recognition when the browser is ready", () => {
    expect(resolveVoiceInputTier(ALL_AVAILABLE)).toBe("on_device");
  });

  it("falls back to the user's own server before the vendor cloud", () => {
    expect(
      resolveVoiceInputTier({ ...ALL_AVAILABLE, onDeviceReady: false }),
    ).toBe("server");
  });

  it("uses the cloud only when on-device and server are both out", () => {
    expect(
      resolveVoiceInputTier({
        ...ALL_AVAILABLE,
        onDeviceReady: false,
        serverTranscription: false,
      }),
    ).toBe("cloud");
  });

  it("reports no tier rather than reaching for the cloud uninvited", () => {
    expect(
      resolveVoiceInputTier({
        ...ALL_AVAILABLE,
        onDeviceReady: false,
        serverTranscription: false,
        allowCloudFallback: false,
      }),
    ).toBeNull();
  });

  it("does not pick the server tier when the page cannot record", () => {
    // The plain-HTTP tailnet URL is not a secure context, so getUserMedia is
    // absent there; falling through must not silently become a cloud upload.
    expect(
      resolveVoiceInputTier({
        ...ALL_AVAILABLE,
        onDeviceReady: false,
        recordingSupported: false,
        allowCloudFallback: false,
      }),
    ).toBeNull();
  });

  it("cannot pick a browser tier when SpeechRecognition is missing", () => {
    expect(
      resolveVoiceInputTier({
        ...ALL_AVAILABLE,
        recognitionSupported: false,
      }),
    ).toBe("server");
    expect(
      resolveVoiceInputTier({
        ...ALL_AVAILABLE,
        recognitionSupported: false,
        serverTranscription: false,
      }),
    ).toBeNull();
  });
});

describe("on-device recognition preparation", () => {
  function makeCtor(
    statics: Partial<SpeechRecognitionConstructor> = {},
  ): SpeechRecognitionConstructor {
    const ctor = function noop() {
      return undefined;
    } as unknown as SpeechRecognitionConstructor;
    return Object.assign(ctor, statics);
  }

  it("detects whether the browser exposes the on-device controls", () => {
    expect(supportsOnDeviceRecognition(null)).toBe(false);
    expect(supportsOnDeviceRecognition(makeCtor())).toBe(false);
    expect(
      supportsOnDeviceRecognition(
        makeCtor({ available: async () => "available" }),
      ),
    ).toBe(true);
  });

  it("normalizes both shapes available() has shipped with", () => {
    expect(readOnDeviceAvailability(true)).toBe("available");
    expect(readOnDeviceAvailability(false)).toBe("unavailable");
    expect(readOnDeviceAvailability(undefined)).toBe("unavailable");
    expect(readOnDeviceAvailability("downloadable")).toBe("downloadable");
  });

  it("is ready when the language pack is already present", async () => {
    const ctor = makeCtor({ available: async () => "available" });
    expect(await prepareOnDeviceRecognition(ctor, "en-US")).toBe(true);
  });

  it("installs a downloadable pack and reports the result", async () => {
    let installedWith: unknown = null;
    const ctor = makeCtor({
      available: async () => "downloadable",
      install: async (options) => {
        installedWith = options;
        return true;
      },
    });
    expect(await prepareOnDeviceRecognition(ctor, "de-DE")).toBe(true);
    expect(installedWith).toEqual({ langs: ["de-DE"], processLocally: true });
  });

  it("treats a downloading pack as not ready", async () => {
    // The download can take minutes; blocking the mic button on it reads as broken.
    const ctor = makeCtor({ available: async () => "downloading" });
    expect(await prepareOnDeviceRecognition(ctor, "en-US")).toBe(false);
  });

  it("never throws — a failure just means the next tier runs", async () => {
    const ctor = makeCtor({
      available: async () => {
        throw new Error("boom");
      },
    });
    expect(await prepareOnDeviceRecognition(ctor, "en-US")).toBe(false);
    expect(await prepareOnDeviceRecognition(null, "en-US")).toBe(false);
  });

  it("confirms processLocally actually took rather than assuming", () => {
    const accepting = { processLocally: false } as BrowserSpeechRecognition;
    expect(applyOnDeviceProcessing(accepting)).toBe(true);

    // A browser that ignores the unknown property: assignment is silent, so
    // only the read-back distinguishes on-device from wishful thinking.
    const ignoring = Object.defineProperty(
      {} as BrowserSpeechRecognition,
      "processLocally",
      { get: () => undefined, set: () => undefined, configurable: true },
    );
    expect(applyOnDeviceProcessing(ignoring)).toBe(false);
  });
});

describe("recording support and formats", () => {
  it("picks the first container the browser can record", () => {
    expect(pickRecordingMimeType((type) => type === "audio/webm")).toBe(
      "audio/webm",
    );
    expect(pickRecordingMimeType(() => false)).toBeNull();
    expect(pickRecordingMimeType(() => true)).toBe("audio/webm;codecs=opus");
  });

  it("names the upload after the container", () => {
    expect(recordingFileName("audio/webm;codecs=opus")).toBe("speech.webm");
    expect(recordingFileName("audio/ogg;codecs=opus")).toBe("speech.ogg");
    expect(recordingFileName("audio/mp4")).toBe("speech.m4a");
    expect(recordingFileName(null)).toBe("speech.webm");
  });

  it("requires a secure context before offering to record", () => {
    const complete = {
      isSecureContext: true,
      MediaRecorder: function MediaRecorderStub() {
        return undefined;
      },
      navigator: { mediaDevices: { getUserMedia: () => undefined } },
    };
    expect(supportsAudioRecording(complete as never)).toBe(true);
    // The plain-HTTP tailnet URL: everything present except the secure origin.
    expect(
      supportsAudioRecording({ ...complete, isSecureContext: false } as never),
    ).toBe(false);
    expect(supportsAudioRecording({} as never)).toBe(false);
  });
});

describe("server-side transcription", () => {
  function jsonResponse(body: unknown, status = 200): Response {
    return {
      ok: status < 400,
      status,
      json: async () => body,
    } as unknown as Response;
  }

  it("returns the trimmed transcript", async () => {
    const text = await transcribeRecording(new Blob(["audio"]), {
      fetchImpl: (async () =>
        jsonResponse({ text: "  hello there  " })) as unknown as typeof fetch,
    });
    expect(text).toBe("hello there");
  });

  it("posts multipart audio to the transcribe endpoint", async () => {
    let seenUrl = "";
    let seenMethod = "";
    await transcribeRecording(new Blob(["audio"], { type: "audio/webm" }), {
      fetchImpl: (async (url: string, init: RequestInit) => {
        seenUrl = url;
        seenMethod = init.method ?? "";
        return jsonResponse({ text: "ok" });
      }) as unknown as typeof fetch,
    });
    expect(seenUrl).toBe("/api/voice/transcribe");
    expect(seenMethod).toBe("POST");
  });

  it("marks a 503 as unconfigured so the caller can try the next tier", async () => {
    await expect(
      transcribeRecording(new Blob(["audio"]), {
        fetchImpl: (async () =>
          jsonResponse(
            { detail: "not enabled" },
            503,
          )) as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ status: 503, unconfigured: true });
  });

  it("does not mark a 502 as unconfigured — that service exists but failed", async () => {
    try {
      await transcribeRecording(new Blob(["audio"]), {
        fetchImpl: (async () =>
          jsonResponse(
            { detail: "unreachable" },
            502,
          )) as unknown as typeof fetch,
      });
      throw new Error("should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(VoiceTranscriptionError);
      expect((error as VoiceTranscriptionError).unconfigured).toBe(false);
    }
  });
});

describe("voice capability report", () => {
  it("fails closed when the Gateway does not answer", async () => {
    const config = await fetchVoiceServerConfig((async () => {
      throw new Error("network down");
    }) as unknown as typeof fetch);
    expect(config).toEqual(DEFAULT_VOICE_SERVER_CONFIG);
    expect(config.allow_cloud_fallback).toBe(false);
  });

  it("fails closed on a non-OK response", async () => {
    const config = await fetchVoiceServerConfig((async () => ({
      ok: false,
      status: 500,
      json: async () => ({ allow_cloud_fallback: true }),
    })) as unknown as typeof fetch);
    expect(config.allow_cloud_fallback).toBe(false);
  });

  it("reads the server's answer when it is present", async () => {
    const config = await fetchVoiceServerConfig((async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        prefer_on_device: false,
        server_transcription: true,
        allow_cloud_fallback: true,
        local_service: false,
      }),
    })) as unknown as typeof fetch);
    expect(config).toEqual({
      prefer_on_device: false,
      server_transcription: true,
      allow_cloud_fallback: true,
      local_service: false,
    });
  });
});
