/**
 * Tier two of voice input: record on the device, transcribe on the user's own
 * machine.
 *
 * This exists so a browser without on-device recognition still does not have
 * to hand its audio to Google or Apple. The recording is posted to the
 * Gateway, which forwards it to a transcription service the operator
 * configured — by default one on the same host.
 *
 * Unlike `SpeechRecognition`, this tier has no interim results: the transcript
 * arrives once, after the recording stops. That is a real UX difference, not
 * an oversight — a streaming local pipeline is its own piece of work, and the
 * composer shows a distinct "transcribing" state rather than pretending the
 * two tiers feel the same.
 */

/** Candidate container formats, best first. */
const PREFERRED_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

export const VOICE_CONFIG_ENDPOINT = "/api/voice/config";
export const VOICE_TRANSCRIBE_ENDPOINT = "/api/voice/transcribe";

export type VoiceServerConfig = {
  prefer_on_device: boolean;
  server_transcription: boolean;
  allow_cloud_fallback: boolean;
  local_service: boolean;
};

export const DEFAULT_VOICE_SERVER_CONFIG: VoiceServerConfig = {
  prefer_on_device: true,
  server_transcription: false,
  // Fail closed. An install whose Gateway did not answer must not be treated
  // as one that permitted the vendor cloud tier.
  allow_cloud_fallback: false,
  local_service: true,
};

/**
 * Pick a container the browser can actually record.
 *
 * `isTypeSupported` is passed in rather than read off `MediaRecorder` so this
 * stays a pure function under test.
 */
export function pickRecordingMimeType(
  isTypeSupported: (type: string) => boolean,
): string | null {
  for (const type of PREFERRED_MIME_TYPES) {
    if (isTypeSupported(type)) {
      return type;
    }
  }
  return null;
}

/** File extension matching a recorded container, for the multipart filename. */
export function recordingFileName(mimeType: string | null): string {
  if (!mimeType) {
    return "speech.webm";
  }
  if (mimeType.startsWith("audio/ogg")) {
    return "speech.ogg";
  }
  if (mimeType.startsWith("audio/mp4")) {
    return "speech.m4a";
  }
  return "speech.webm";
}

/**
 * Whether this page can record at all.
 *
 * `getUserMedia` needs a secure context, which over Tailscale means the
 * `https://<magicdns>.ts.net` URL rather than the plain-HTTP tailnet IP. On
 * the insecure origin `mediaDevices` is simply absent, so this returns false
 * and the composer explains the situation instead of failing at the prompt.
 */
export function supportsAudioRecording(
  scope: {
    isSecureContext?: boolean;
    MediaRecorder?: unknown;
    navigator?: { mediaDevices?: { getUserMedia?: unknown } };
  } = globalThis as never,
): boolean {
  return Boolean(
    scope.isSecureContext &&
    typeof scope.MediaRecorder === "function" &&
    typeof scope.navigator?.mediaDevices?.getUserMedia === "function",
  );
}

export class VoiceTranscriptionError extends Error {
  readonly status: number;
  /** True when the server has no transcription configured, so a later tier may run. */
  readonly unconfigured: boolean;

  constructor(message: string, status: number) {
    super(message);
    this.name = "VoiceTranscriptionError";
    this.status = status;
    this.unconfigured = status === 503;
  }
}

/** Read the capability report, falling back to a closed default. */
export async function fetchVoiceServerConfig(
  fetchImpl: typeof fetch = fetch,
): Promise<VoiceServerConfig> {
  try {
    const response = await fetchImpl(VOICE_CONFIG_ENDPOINT, {
      method: "GET",
      credentials: "same-origin",
    });
    if (!response.ok) {
      return DEFAULT_VOICE_SERVER_CONFIG;
    }
    const body = (await response.json()) as Partial<VoiceServerConfig>;
    return {
      prefer_on_device:
        body.prefer_on_device ?? DEFAULT_VOICE_SERVER_CONFIG.prefer_on_device,
      server_transcription:
        body.server_transcription ??
        DEFAULT_VOICE_SERVER_CONFIG.server_transcription,
      allow_cloud_fallback:
        body.allow_cloud_fallback ??
        DEFAULT_VOICE_SERVER_CONFIG.allow_cloud_fallback,
      local_service:
        body.local_service ?? DEFAULT_VOICE_SERVER_CONFIG.local_service,
    };
  } catch {
    return DEFAULT_VOICE_SERVER_CONFIG;
  }
}

/** Post one recording to the Gateway and return the transcript. */
export async function transcribeRecording(
  blob: Blob,
  options: {
    fetchImpl?: typeof fetch;
    fileName?: string;
    signal?: AbortSignal;
  } = {},
): Promise<string> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const form = new FormData();
  form.append("file", blob, options.fileName ?? recordingFileName(blob.type));

  let response: Response;
  try {
    response = await fetchImpl(VOICE_TRANSCRIBE_ENDPOINT, {
      method: "POST",
      body: form,
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") {
      throw error;
    }
    throw new VoiceTranscriptionError(
      "Could not reach the transcription service.",
      0,
    );
  }

  if (!response.ok) {
    throw new VoiceTranscriptionError(
      await readErrorDetail(response),
      response.status,
    );
  }

  const body = (await response.json()) as { text?: unknown };
  return typeof body.text === "string" ? body.text.trim() : "";
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Fall through to the generic message below.
  }
  return `Transcription failed (HTTP ${response.status}).`;
}
