import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [
      { name: "first-model", display_name: "First Model" },
      { name: "agent-model", display_name: "Agent Model" },
    ],
    tokenUsageEnabled: false,
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: rs.fn(),
  }),
}));

rs.mock("@/core/skills/hooks", () => ({
  useSkills: () => ({ skills: [], isLoading: false, error: null }),
}));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
});

function composer(
  onContextChange: (...args: unknown[]) => void,
  agent: { model?: string; loading: boolean },
) {
  return (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider
          initialUser={{
            id: "user-1",
            email: "user@example.test",
            system_role: "user",
            needs_setup: false,
            oauth_provider: null,
          }}
        >
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: true }}
          >
            <PromptInputProvider>
              <InputBox
                threadId="thread-1"
                draftAgentName="researcher"
                agentSkillsLoading={agent.loading}
                defaultModelName={agent.model}
                defaultModelLoading={agent.loading}
                context={{ mode: "pro" } as never}
                onContextChange={onContextChange as never}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}

afterEach(() => {
  rs.restoreAllMocks();
  window.sessionStorage.clear();
  cleanup();
});

describe("InputBox agent default model", () => {
  it("waits for the agent before resolving a model the list loaded first", async () => {
    const onContextChange = rs.fn();
    const view = render(composer(onContextChange, { loading: true }));

    // Models are known, the agent is not: no automatic fallback may land,
    // or models[0] would be pinned over the agent's own default.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(onContextChange).not.toHaveBeenCalled();

    view.rerender(
      composer(onContextChange, { model: "agent-model", loading: false }),
    );
    await waitFor(() => {
      expect(onContextChange).toHaveBeenCalledWith(
        expect.objectContaining({ model_name: "agent-model" }),
        { automatic: true },
      );
    });
    expect(onContextChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ model_name: "first-model" }),
      expect.anything(),
    );
  });
});
