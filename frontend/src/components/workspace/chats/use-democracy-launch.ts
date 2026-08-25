"use client";

import { useEffect, useRef } from "react";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import {
  consumeDemocracyLaunch,
  DEMOCRACY_LAUNCH_EVENT,
  type DemocracyLaunch,
} from "@/core/threads/democracy";

/**
 * Pick up a Democracy launch stashed by the setup dialog and apply it here.
 *
 * The dialog cannot write this directly: a new chat mints its thread id inside
 * the chat instance, *after* navigation, so there is no thread to write a
 * context onto while the dialog is still open. The launch is therefore stashed
 * under one key and claimed here.
 *
 * Three rules keep that handoff from misfiring:
 *
 * * **Claim on mount *and* on the launch event.** Navigating to
 *   `/workspace/chats/new` from a chat that is already `/new` is a no-op — the
 *   route does not change, so nothing remounts and a mount-only effect never
 *   fires. Launching a panel from an already-open new chat would then silently
 *   do nothing, which is the worst possible failure for a button whose whole job
 *   is to start an expensive run.
 * * **Only a new chat claims.** The event fires before navigation completes, so
 *   an instance showing an existing thread must ignore it and let the new chat
 *   that is about to mount take it. Otherwise a panel would land in whatever
 *   conversation happened to be open.
 * * **Only the active instance claims.** Keep-alive chat tabs mount several
 *   instances under one route; every one of them would otherwise race for the
 *   same launch and all but one would lose it.
 *
 * The one-shot `consumeDemocracyLaunch` is what makes claiming safe from both
 * paths: whichever fires first removes the stash, and the other finds nothing.
 */
export function useDemocracyLaunch({
  enabled,
  isNewThread,
  applyLaunch,
}: {
  enabled: boolean;
  isNewThread: boolean;
  applyLaunch: (launch: DemocracyLaunch) => void;
}) {
  const promptInputController = usePromptInputController();
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;
  const applyRef = useRef(applyLaunch);
  applyRef.current = applyLaunch;

  useEffect(() => {
    if (!enabled || !isNewThread) return;

    const claim = () => {
      const launch = consumeDemocracyLaunch();
      if (!launch) return;
      applyRef.current(launch);
      // The task is seeded into the composer rather than sent, so the user gets
      // a last look at what a panel-priced run is about to be asked.
      setInputRef.current(launch.task);
    };

    claim();
    window.addEventListener(DEMOCRACY_LAUNCH_EVENT, claim);
    return () => window.removeEventListener(DEMOCRACY_LAUNCH_EVENT, claim);
  }, [enabled, isNewThread]);
}
