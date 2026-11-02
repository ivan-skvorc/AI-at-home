import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { RunLimitsSettingsPage } from "@/components/workspace/settings/run-limits-settings-page";
import { fetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { enUS } from "@/core/i18n/locales/en-US";
import type { RunLimitsResponse } from "@/core/settings/run-limits";
import { isStaticWebsiteOnly } from "@/core/static-mode";

rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
  getCsrfHeaders: () => ({}),
}));
rs.mock("sonner", () => ({ toast: { success: rs.fn(), error: rs.fn() } }));

const RESPONSE: RunLimitsResponse = {
  overrides: { recursion_limit: 600 },
  effective: {
    spend_budget: {
      enabled: true,
      daily_limit: 5,
      weekly_limit: null,
      monthly_limit: null,
      currency: "USD",
    },
    loop_detection: {
      enabled: true,
      warn_threshold: 3,
      hard_limit: 5,
      tool_freq_warn: 30,
      tool_freq_hard_limit: 50,
      tool_freq_overrides: {},
    },
    token_budget: { enabled: false, max_tokens: 200_000 },
    subagent_token_budget: { enabled: true, max_tokens: 1_000_000 },
    recursion_limit: 600,
    max_recursion_limit: 1000,
  },
};

const copy = enUS.settings.runLimits;

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

/** The page always sends a JSON string body. */
const bodyOf = (init: RequestInit | undefined): unknown =>
  JSON.parse(typeof init?.body === "string" ? init.body : "null");

/** Bodies of every PUT the page sent, parsed. */
function saved(): unknown[] {
  return rs
    .mocked(fetch)
    .mock.calls.filter(([, init]) => init?.method === "PUT")
    .map(([, init]) => bodyOf(init));
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RunLimitsSettingsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  rs.mocked(useAuth).mockReturnValue({
    user: { id: "u", system_role: "admin" },
  } as ReturnType<typeof useAuth>);
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(false);
  rs.mocked(fetch).mockImplementation(async (_input, init) =>
    init?.method === "PUT"
      ? json({ ...RESPONSE, overrides: bodyOf(init) })
      : json(RESPONSE),
  );
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

test("turning the tool-call limits off saves that section and keeps the rest", async () => {
  renderPage();
  const toggle = await screen.findByRole("switch", { name: copy.toolTitle });
  const save = screen.getByRole("button", { name: copy.save });
  expect(save.hasAttribute("disabled")).toBe(true);

  fireEvent.click(toggle);
  fireEvent.click(save);

  await waitFor(() => expect(saved()).toHaveLength(1));
  expect(saved()[0]).toEqual({
    recursion_limit: 600,
    loop_detection: {
      enabled: false,
      warn_threshold: 3,
      hard_limit: 5,
      tool_freq_warn: 30,
      tool_freq_hard_limit: 50,
    },
  });
});

test("an invalid edit blocks Save and says why", async () => {
  renderPage();
  const steps = await screen.findByLabelText(copy.steps);
  fireEvent.change(steps, { target: { value: "0" } });
  expect(screen.getByRole("alert").textContent).toBe(
    copy.errors.notWholeNumber,
  );
  expect(
    screen.getByRole("button", { name: copy.save }).hasAttribute("disabled"),
  ).toBe(true);
});

test("using config.yaml for one section clears only it and keeps unsaved edits", async () => {
  renderPage();
  const tokens = await screen.findAllByLabelText(copy.maxTokens);
  fireEvent.change(tokens[0]!, { target: { value: "9000" } });
  // Only the step limit is stored as an override, so it has the one reset link.
  fireEvent.click(screen.getByRole("button", { name: copy.useYaml }));

  await waitFor(() => expect(saved()).toHaveLength(1));
  expect(saved()[0]).toEqual({ recursion_limit: null });
  await waitFor(() =>
    expect(
      (screen.getAllByLabelText(copy.maxTokens)[0] as HTMLInputElement).value,
    ).toBe("9000"),
  );
});

test("non-admins never query the limits", () => {
  rs.mocked(useAuth).mockReturnValue({
    user: { id: "u", system_role: "user" },
  } as ReturnType<typeof useAuth>);
  renderPage();
  expect(screen.getByText(copy.adminOnly)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
