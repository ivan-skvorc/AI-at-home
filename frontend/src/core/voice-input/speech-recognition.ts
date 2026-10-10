export type SpeechRecognitionErrorCode =
  | "aborted"
  | "audio-capture"
  | "bad-grammar"
  | "language-not-supported"
  | "network"
  | "no-speech"
  | "not-allowed"
  | "phrases-not-supported"
  | "service-not-allowed";

export type SpeechRecognitionErrorKind =
  | "cancelled"
  | "microphone_unavailable"
  | "permission_denied"
  | "unsupported_language"
  | "network"
  | "no_speech"
  | "unknown";

/**
 * What `SpeechRecognition.available()` reports for a language pack.
 *
 * "available" means recognition can run locally right now; "downloadable" and
 * "downloading" mean it cannot yet but will; "unavailable" means never.
 */
export type OnDeviceAvailability =
  | "available"
  | "downloadable"
  | "downloading"
  | "unavailable";

export type SpeechRecognitionConstructor =
  (new () => BrowserSpeechRecognition) & {
    /** Chrome 139+: whether on-device recognition can serve these languages. */
    available?: (options: {
      langs: string[];
      processLocally: boolean;
    }) => Promise<OnDeviceAvailability | boolean>;
    /** Chrome 139+: fetch the on-device language pack. */
    install?: (options: {
      langs: string[];
      processLocally: boolean;
    }) => Promise<boolean>;
  };

export type SpeechRecognitionEventLike = {
  results: SpeechRecognitionResultListLike;
};

export type SpeechRecognitionErrorEventLike = {
  error?: SpeechRecognitionErrorCode | string;
};

export type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  /**
   * Chrome 139+. Keeps recognition on the device instead of streaming the
   * audio to the vendor. Absent everywhere else, which is why every write is
   * guarded rather than assigned unconditionally.
   */
  processLocally?: boolean;
  onend: (() => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionWindow = Window &
  typeof globalThis & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };

export type SpeechRecognitionAlternativeLike = {
  transcript?: string;
};

export type SpeechRecognitionResultLike = {
  0?: SpeechRecognitionAlternativeLike;
  isFinal: boolean;
  length: number;
};

export type SpeechRecognitionResultListLike = {
  [index: number]: SpeechRecognitionResultLike | undefined;
  length: number;
};

const DEFAULT_SPEECH_RECOGNITION_LANGUAGE = "en-US";
const SPEECH_RECOGNITION_LANGUAGE_ALLOWLIST = new Set([
  "de",
  "en",
  "es",
  "fr",
  "it",
  "ja",
  "ko",
  "pt",
  "zh",
]);

export function getSpeechRecognitionConstructor(
  value: unknown = globalThis,
): SpeechRecognitionConstructor | null {
  const maybeWindow = value as Partial<SpeechRecognitionWindow>;
  return (
    maybeWindow.SpeechRecognition ?? maybeWindow.webkitSpeechRecognition ?? null
  );
}

export function getSpeechRecognitionLanguage(locale: string): string {
  const normalized = normalizeBCP47Locale(locale);
  const language = normalized.split("-")[0]?.toLowerCase();

  if (language === "zh") {
    return "zh-CN";
  }
  if (language && SPEECH_RECOGNITION_LANGUAGE_ALLOWLIST.has(language)) {
    return normalized;
  }
  return DEFAULT_SPEECH_RECOGNITION_LANGUAGE;
}

export function shouldRestartSpeechRecognition(
  lastError: SpeechRecognitionErrorKind | null,
): boolean {
  return lastError === null || lastError === "no_speech";
}

// Scripts written without spaces between words and the punctuation that
// surrounds them: Han (Chinese), kana (Japanese), CJK symbols/punctuation,
// and their full-width/half-width compatibility forms. Korean Hangul is
// deliberately absent — Korean uses eojeol spaces, so it is joined like any
// space-delimited script. Boundaries compare single UTF-16 code units, so
// supplementary-plane Han (CJK Ext B+) never matches; fine for ASR output.
const NO_SPACE_SCRIPT_BOUNDARY =
  /[\u3000-\u303f\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uff9f]/;

// These leading marks attach to the preceding text. Keep the rule directional:
// a sentence-ending mark on the left still needs a space before the next word.
const NO_SPACE_BEFORE_PUNCTUATION = /[,.;:!?%…)\]}]/;

function joinTranscriptSegments(left: string, right: string): string {
  if (!left) {
    return right;
  }
  if (!right) {
    return left;
  }
  const lastChar = left.trimEnd().slice(-1);
  const firstChar = right.trimStart().slice(0, 1);
  // Space-delimited scripts need an explicit separator when a provider does
  // not pad its results (WebKit trims final transcripts), otherwise the last
  // finalized word glues onto the next segment. No-space scripts (Chinese,
  // Japanese) keep the plain concatenation they always had.
  if (
    !lastChar ||
    !firstChar ||
    NO_SPACE_SCRIPT_BOUNDARY.test(lastChar) ||
    NO_SPACE_SCRIPT_BOUNDARY.test(firstChar) ||
    NO_SPACE_BEFORE_PUNCTUATION.test(firstChar)
  ) {
    return `${left}${right}`;
  }
  return `${left} ${right}`;
}

export function readSpeechRecognitionTranscript(
  results: SpeechRecognitionResultListLike,
): { finalText: string; interimText: string; text: string } {
  const finalParts: string[] = [];
  const interimParts: string[] = [];

  for (const result of Array.from(
    { length: results.length },
    (_, index) => results[index],
  )) {
    const transcript = result?.[0]?.transcript ?? "";
    if (result?.isFinal) {
      finalParts.push(transcript);
    } else {
      interimParts.push(transcript);
    }
  }

  let finalText = "";
  for (const part of finalParts) {
    finalText = joinTranscriptSegments(finalText, part);
  }
  let interimText = "";
  for (const part of interimParts) {
    interimText = joinTranscriptSegments(interimText, part);
  }
  let text = "";
  for (const part of [...finalParts, ...interimParts]) {
    text = joinTranscriptSegments(text, part);
  }

  return {
    finalText: normalizeSpeechTranscript(finalText),
    interimText: normalizeSpeechTranscript(interimText),
    text: normalizeSpeechTranscript(text),
  };
}

export function appendSpeechTranscript(baseText: string, transcript: string) {
  const cleanTranscript = normalizeSpeechTranscript(transcript);
  if (!cleanTranscript) {
    return baseText;
  }

  const cleanBase = baseText.trimEnd();
  if (!cleanBase) {
    return cleanTranscript;
  }

  return `${cleanBase} ${cleanTranscript}`;
}

export function normalizeSpeechTranscript(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

export function mapSpeechRecognitionError(
  error: SpeechRecognitionErrorCode | string | undefined,
): SpeechRecognitionErrorKind {
  switch (error) {
    case "aborted":
      return "cancelled";
    case "audio-capture":
      return "microphone_unavailable";
    case "not-allowed":
    case "service-not-allowed":
      return "permission_denied";
    case "language-not-supported":
      return "unsupported_language";
    case "network":
      return "network";
    case "no-speech":
      return "no_speech";
    default:
      return "unknown";
  }
}

function normalizeBCP47Locale(locale: string): string {
  const trimmed = locale.trim();
  if (!trimmed) {
    return DEFAULT_SPEECH_RECOGNITION_LANGUAGE;
  }
  try {
    return Intl.getCanonicalLocales(trimmed)[0] ?? trimmed;
  } catch {
    return DEFAULT_SPEECH_RECOGNITION_LANGUAGE;
  }
}

/**
 * Which tier should handle a voice-input session.
 *
 * - `on_device` — the browser recognizes speech locally; no audio leaves the phone.
 * - `server` — audio is posted to the Gateway and transcribed on the user's own machine.
 * - `cloud` — the browser's default recognition, which streams audio to Google or Apple.
 *
 * The order is the point of the feature. `cloud` is last and only reachable
 * when the operator opted into it, because it is the one tier that sends the
 * household's speech to a model vendor.
 */
export type VoiceInputTier = "on_device" | "server" | "cloud";

export type VoiceTierInputs = {
  /** The browser has on-device recognition ready for the requested language. */
  onDeviceReady: boolean;
  /** The Gateway reports a configured local transcription service. */
  serverTranscription: boolean;
  /** The operator permitted the vendor cloud tier as a last resort. */
  allowCloudFallback: boolean;
  /** The browser exposes SpeechRecognition at all (needed for on_device and cloud). */
  recognitionSupported: boolean;
  /** The page can open a microphone (secure context + MediaRecorder) — needed for `server`. */
  recordingSupported: boolean;
};

/**
 * Pick the tier, or null when voice input cannot honestly run.
 *
 * Returning null is a supported outcome, not a failure to handle: an install
 * with no local STT and no cloud opt-in should say voice is unavailable rather
 * than quietly reaching for a vendor.
 */
export function resolveVoiceInputTier(
  inputs: VoiceTierInputs,
): VoiceInputTier | null {
  if (inputs.recognitionSupported && inputs.onDeviceReady) {
    return "on_device";
  }
  if (inputs.serverTranscription && inputs.recordingSupported) {
    return "server";
  }
  if (inputs.recognitionSupported && inputs.allowCloudFallback) {
    return "cloud";
  }
  return null;
}

/**
 * Whether this browser exposes the on-device recognition controls at all.
 *
 * Chrome 139+ only; every other engine returns false and lands on a later tier.
 */
export function supportsOnDeviceRecognition(
  ctor: SpeechRecognitionConstructor | null,
): boolean {
  return typeof ctor?.available === "function";
}

/** Normalize the two shapes `available()` has shipped with. */
export function readOnDeviceAvailability(
  value: OnDeviceAvailability | boolean | undefined,
): OnDeviceAvailability {
  if (value === true) {
    return "available";
  }
  if (value === false || value === undefined) {
    return "unavailable";
  }
  return value;
}

/**
 * Ask the browser whether it can recognize `language` locally, installing the
 * language pack when that is all that is missing.
 *
 * Never throws: every failure means "this tier is not available", and the
 * caller's job is then to fall through to the next one rather than to show an
 * error. A `downloading` pack is treated as not ready — the install may take
 * minutes, and blocking the microphone button on it would feel broken.
 */
export async function prepareOnDeviceRecognition(
  ctor: SpeechRecognitionConstructor | null,
  language: string,
): Promise<boolean> {
  if (!supportsOnDeviceRecognition(ctor) || !ctor?.available) {
    return false;
  }
  const options = { langs: [language], processLocally: true };
  try {
    const availability = readOnDeviceAvailability(
      await ctor.available(options),
    );
    if (availability === "available") {
      return true;
    }
    if (availability !== "downloadable" || typeof ctor.install !== "function") {
      return false;
    }
    return (await ctor.install(options)) === true;
  } catch {
    return false;
  }
}

/**
 * Turn on local processing for a recognizer when the browser supports it.
 *
 * Returns whether the flag actually took. Assigning an unknown property is
 * silent in JS, so the read-back is what distinguishes "on-device" from
 * "looked like on-device".
 */
export function applyOnDeviceProcessing(
  recognition: BrowserSpeechRecognition,
): boolean {
  try {
    recognition.processLocally = true;
    return recognition.processLocally === true;
  } catch {
    return false;
  }
}
