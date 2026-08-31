"use client";

import { ImageGenerationSetup } from "@/components/workspace/image-generation-setup";

/**
 * Generation setup lives at its own route rather than in a modal over the chat:
 * it is the start of a conversation, the same as `/workspace/chats/new` and
 * `/workspace/democracy/new`, and the choices it collects (image or clip, size,
 * whether to iterate) decide how many GPU minutes the first turn spends.
 */
export default function ImageGenerationNewPage() {
  return <ImageGenerationSetup />;
}
