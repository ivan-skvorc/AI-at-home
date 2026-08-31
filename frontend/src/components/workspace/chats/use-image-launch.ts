"use client";

import { useEffect, useState } from "react";

import {
  consumeImageLaunch,
  IMAGE_LAUNCH_EVENT,
  buildImageLaunchMessage,
} from "@/core/threads/image-generation";

/**
 * Pick up a generation launch stashed by the setup page and seed the composer.
 *
 * The same three rules the Democracy handoff documents apply, for the same
 * reasons — the setup page has no thread id to write to, so the launch is
 * stashed under one key and claimed here:
 *
 * * **Claim on mount *and* on the launch event**, because navigating to
 *   `/workspace/chats/new` from a chat that is already `/new` does not remount.
 * * **Only a new chat claims**, so a launch never lands in whatever
 *   conversation happened to be open.
 * * **Only the active instance claims**, so keep-alive tabs do not race.
 *
 * The request is returned as `seededPrompt` rather than pushed in with
 * `setInput`: the composer's textarea is uncontrolled and hydrates its draft
 * *after* mount, so a value written during mount is overwritten. `initialValue`
 * is the channel that hydration itself respects.
 *
 * Seeded, never sent. A generation costs GPU minutes (a clip, several), and the
 * text is worth a last look before it is spent.
 */
export function useImageLaunch({
  enabled,
  isNewThread,
}: {
  enabled: boolean;
  isNewThread: boolean;
}) {
  const [seededPrompt, setSeededPrompt] = useState<string | undefined>(
    undefined,
  );

  useEffect(() => {
    if (!enabled || !isNewThread) return;

    const claim = () => {
      const launch = consumeImageLaunch();
      if (!launch) return;
      setSeededPrompt(buildImageLaunchMessage(launch));
    };

    claim();
    window.addEventListener(IMAGE_LAUNCH_EVENT, claim);
    return () => window.removeEventListener(IMAGE_LAUNCH_EVENT, claim);
  }, [enabled, isNewThread]);

  return { seededPrompt };
}
