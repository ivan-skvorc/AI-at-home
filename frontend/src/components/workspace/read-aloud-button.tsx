import { Loader2Icon, SquareIcon, Volume2Icon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { speakText, toSpeakableText } from "@/core/voice-input/read-aloud";

import { Tooltip } from "./tooltip";

/** Read one answer aloud through Grok. The label names xAI as the destination. */
export function ReadAloudButton({
  text,
  maxChars,
}: {
  text: string;
  maxChars: number;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const abortRef = useRef<AbortController | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    audioRef.current?.pause();
    audioRef.current = null;
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setState("idle");
  }, []);

  // Leaving the row (or the thread) must not keep playing or leak the blob.
  useEffect(() => stop, [stop]);

  const start = useCallback(() => {
    const speakable = toSpeakableText(text, maxChars);
    if (!speakable) {
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setState("loading");
    void speakText(speakable, { signal: controller.signal })
      .then(async (blob) => {
        if (controller.signal.aborted) {
          return;
        }
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = stop;
        setState("playing");
        await audio.play();
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          stop();
          toast.error(t.common.readAloudFailed);
        }
      });
  }, [maxChars, stop, t.common.readAloudFailed, text]);

  const label = state === "idle" ? t.common.readAloud : t.common.stopReadAloud;
  return (
    <Tooltip content={label}>
      <Button
        aria-label={label}
        size="icon-sm"
        type="button"
        variant="ghost"
        onClick={state === "idle" ? start : stop}
      >
        {state === "loading" ? (
          <Loader2Icon className="size-4 animate-spin" />
        ) : state === "playing" ? (
          <SquareIcon className="size-4" />
        ) : (
          <Volume2Icon className="size-4" />
        )}
      </Button>
    </Tooltip>
  );
}
