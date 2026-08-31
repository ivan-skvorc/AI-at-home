import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { enUS } from "@/core/i18n/locales/en-US";

/**
 * The generation setup page (fork feature): sidebar → page → seeded new chat.
 *
 * What is pinned here is the handoff, because it is the part that fails
 * silently. The page cannot start the run itself — a new chat mints its thread
 * id after navigation — so it stashes a launch and routes. Drop either half and
 * the button still looks like it worked: the page navigates to an empty chat,
 * or stashes a launch nothing ever claims.
 *
 * The preview assertions cover the second silent failure: the pixel size is
 * chosen HERE, and a clip asked for at image resolution runs for minutes before
 * it runs out of VRAM.
 */

const push = rs.fn((_href: string) => undefined);
const back = rs.fn(() => undefined);

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push, back }),
  usePathname: () => "/workspace/image/new",
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

// The chrome is not what is under test, and it reaches for sidebar context.
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => null,
  WorkspaceBody: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

const { ImageGenerationSetup } =
  await import("@/components/workspace/image-generation-setup");
const { consumeImageLaunch } = await import("@/core/threads/image-generation");

beforeEach(() => {
  push.mockClear();
  back.mockClear();
  window.localStorage.clear();
});

afterEach(cleanup);

function promptBox() {
  return screen.getByPlaceholderText(enUS.imageGeneration.promptPlaceholder);
}

test("nothing is generated until there is something to draw", () => {
  render(<ImageGenerationSetup />);
  const button = screen.getByRole<HTMLButtonElement>("button", {
    name: enUS.imageGeneration.start,
  });
  expect(button.disabled).toBe(true);

  fireEvent.change(promptBox(), { target: { value: "a red bicycle" } });
  expect(button.disabled).toBe(false);
});

test("the page stashes the launch and routes to a new chat", () => {
  render(<ImageGenerationSetup />);
  fireEvent.change(promptBox(), { target: { value: "  a red bicycle  " } });
  fireEvent.click(
    screen.getByRole("button", { name: enUS.imageGeneration.start }),
  );

  expect(push).toHaveBeenCalledWith("/workspace/chats/new");
  // Trimmed, and dispatchable by the chat that is about to mount.
  expect(consumeImageLaunch()).toEqual({
    kind: "image",
    prompt: "a red bicycle",
    aspect: "landscape",
    checkpoint: undefined,
    refine: false,
  });
});

test("the request is shown before it is spent", () => {
  render(<ImageGenerationSetup />);
  fireEvent.change(promptBox(), { target: { value: "a red bicycle" } });
  // The size the run will actually use, not a shape name the model must guess at.
  expect(screen.getByText(/Size: 1344x768 \(landscape\)/)).toBeTruthy();
});
