"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useVoiceServerConfig } from "./read-aloud";

type ReadAloudConfig = { available: boolean; maxChars: number };

// The default is "off": a row rendered outside the workspace (tests, embeds,
// static demos) never offers a button that would send text to xAI.
export const ReadAloudContext = createContext<ReadAloudConfig>({
  available: false,
  maxChars: 12000,
});

/** One voice-config read for the workspace, shared with every message row. */
export function ReadAloudConfigProvider({ children }: { children: ReactNode }) {
  const config = useVoiceServerConfig();
  const value = useMemo(
    () => ({
      available: config.read_aloud,
      maxChars: config.read_aloud_max_chars,
    }),
    [config.read_aloud, config.read_aloud_max_chars],
  );
  return (
    <ReadAloudContext.Provider value={value}>
      {children}
    </ReadAloudContext.Provider>
  );
}

export function useReadAloudConfig(): ReadAloudConfig {
  return useContext(ReadAloudContext);
}
