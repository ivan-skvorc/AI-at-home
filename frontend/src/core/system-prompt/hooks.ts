import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  loadSystemPrompt,
  loadSystemPromptPreview,
  resetSystemPrompt,
  saveSystemPrompt,
} from "./api";
import type { SystemPrompt } from "./types";

const SYSTEM_PROMPT_KEY = ["systemPrompt"] as const;
const SYSTEM_PROMPT_PREVIEW_KEY = ["systemPromptPreview"] as const;

export function useSystemPrompt() {
  return useQuery({
    queryKey: SYSTEM_PROMPT_KEY,
    queryFn: loadSystemPrompt,
    // A 403 means the caller is not an admin; retrying cannot change that.
    retry: false,
  });
}

export function useSystemPromptPreview(
  subagentEnabled: boolean,
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...SYSTEM_PROMPT_PREVIEW_KEY, subagentEnabled],
    queryFn: () => loadSystemPromptPreview({ subagentEnabled }),
    enabled,
    retry: false,
  });
}

export function useSaveSystemPrompt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) => saveSystemPrompt(content),
    onSuccess: (prompt) => {
      queryClient.setQueryData<SystemPrompt>(SYSTEM_PROMPT_KEY, prompt);
      // The rendered preview is derived from the saved template.
      void queryClient.invalidateQueries({
        queryKey: SYSTEM_PROMPT_PREVIEW_KEY,
      });
    },
  });
}

export function useResetSystemPrompt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => resetSystemPrompt(),
    onSuccess: (prompt) => {
      queryClient.setQueryData<SystemPrompt>(SYSTEM_PROMPT_KEY, prompt);
      void queryClient.invalidateQueries({
        queryKey: SYSTEM_PROMPT_PREVIEW_KEY,
      });
    },
  });
}
