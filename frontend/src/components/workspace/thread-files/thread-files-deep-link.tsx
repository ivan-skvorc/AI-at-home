"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  requestsThreadFilesPanel,
  withoutThreadFilesPanel,
} from "@/core/thread-files/deep-link";

import { useArtifacts } from "../artifacts/context";
import { useMaybeSidecar } from "../sidecar/context";

/**
 * Opens the side panel on the Files tab when the chat URL carries
 * `?panel=files`, then removes the parameter with `router.replace`. Renders
 * nothing; mount it inside the chat's providers (artifacts and Side Chat).
 *
 * `enabled` is false for a chat without a Files view (new, mock, static demo)
 * and for a keep-alive chat in the background, so only the chat on screen
 * reacts. The URL must also name this chat's thread: during a switch between
 * kept-alive chats the previous one is still mounted for a render.
 */
export function ThreadFilesDeepLink({
  threadId,
  enabled,
}: {
  threadId: string;
  enabled: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { showFiles } = useArtifacts();
  const sidecar = useMaybeSidecar();
  const requested =
    enabled && requestsThreadFilesPanel(pathname, searchParams, threadId);
  // Two steps: the panel provider restores its saved state in an effect of
  // the same commit that mounts this chat, and a parent's effect runs after a
  // child's, so opening the panel right away would be overwritten. Opening it
  // one commit later lands after that restore.
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (requested) {
      setArmed(true);
    }
  }, [requested]);

  useEffect(() => {
    if (!armed) {
      return;
    }
    setArmed(false);
    sidecar?.close();
    showFiles();
    if (requestsThreadFilesPanel(pathname, searchParams, threadId)) {
      router.replace(withoutThreadFilesPanel(pathname, searchParams), {
        scroll: false,
      });
    }
  }, [armed, pathname, router, searchParams, showFiles, sidecar, threadId]);

  return null;
}
