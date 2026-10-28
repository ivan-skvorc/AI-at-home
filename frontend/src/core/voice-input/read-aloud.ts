/**
 * Read an answer aloud through Grok on the connected Grok subscription.
 *
 * Unlike dictation, this path has no local tier: the Gateway offers it only
 * while an administrator switched the Grok voice feature on (`read_aloud` in
 * the voice capability report), and the button says the text goes to xAI.
 */

import { useQuery } from "@tanstack/react-query";

import {
  DEFAULT_VOICE_SERVER_CONFIG,
  fetchVoiceServerConfig,
  type VoiceServerConfig,
} from "./server-transcription";

export const VOICE_SPEAK_ENDPOINT = "/api/voice/speak";
export const VOICE_CONFIG_QUERY_KEY = ["voice-config"] as const;

/**
 * Turn a Markdown answer into text worth hearing.
 *
 * Code blocks, link targets, images' URLs and markup characters are dropped;
 * the result is capped at `maxChars` because the Gateway refuses longer text
 * rather than silently truncating it.
 */
export function toSpeakableText(markdown: string, maxChars: number): string {
  // Bound the regex work by the input, not by how long an answer can grow.
  const bounded = markdown.slice(0, maxChars * 4);
  const text = bounded
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`\n]*)`/g, "$1")
    .replace(/!\[([^\]\n]*)\]\([^)\n]*\)/g, "$1")
    .replace(/\[([^\]\n]*)\]\([^)\n]*\)/g, "$1")
    .replace(/<[^<>\n]+>/g, " ")
    .replace(/^[ \t]{0,3}(?:#{1,6}|>|[-*+]|\d+\.)[ \t]+/gm, "")
    .replace(/[*_~]{1,3}/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return text.length > maxChars ? text.slice(0, maxChars).trim() : text;
}

/** Ask the Gateway to synthesize `text`; resolves to the audio to play. */
export async function speakText(
  text: string,
  options: { fetchImpl?: typeof fetch; signal?: AbortSignal } = {},
): Promise<Blob> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const response = await fetchImpl(VOICE_SPEAK_ENDPOINT, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal: options.signal,
  });
  if (!response.ok) {
    throw new Error(`Read-aloud failed (HTTP ${response.status})`);
  }
  return response.blob();
}

/** The voice capability report, shared by every message row through one query. */
export function useVoiceServerConfig(): VoiceServerConfig {
  const query = useQuery({
    queryKey: VOICE_CONFIG_QUERY_KEY,
    queryFn: () => fetchVoiceServerConfig(),
    staleTime: 60_000,
  });
  return query.data ?? DEFAULT_VOICE_SERVER_CONFIG;
}
