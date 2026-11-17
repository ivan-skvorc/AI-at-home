"use client";

import { useEffect } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { hydrateAutoTitlePreference } from "@/core/settings/auto-title-sync";
import { isStaticWebsiteOnly } from "@/core/static-mode";

/**
 * Adopts the account's Settings → Conversation titles preference once per
 * workspace session (fork feature, FORK.md §33), and again when another
 * account signs in. Renders nothing.
 *
 * Mounted once in the workspace shell rather than in the Settings page: the
 * run context reads the local copy on every send, so it has to be current
 * before anyone opens Settings. Keyed by user id, not by an authenticated
 * session — with auth disabled every request is the `default` user, and the
 * Gateway still stores that user's preference.
 */
export function AutoTitlePreferenceSync() {
  const { user } = useAuth();
  const userId = user?.id;

  useEffect(() => {
    if (!userId || isStaticWebsiteOnly()) {
      return;
    }
    const abort = new AbortController();
    void hydrateAutoTitlePreference(abort.signal);
    return () => abort.abort();
  }, [userId]);

  return null;
}
