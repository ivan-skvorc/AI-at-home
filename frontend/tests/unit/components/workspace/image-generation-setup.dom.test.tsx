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
 * The rest is the three decisions the page exists to take before the first
 * model call, each with a failure that looks like success: the prompt mode (a
 * verbatim prompt quietly rewritten), the resolution (a clip at image size that
 * runs for minutes and then runs out of VRAM), and the negative prompt (a field
 * that accepts text the chosen model will never read).
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
  return screen.getByLabelText(enUS.imageGeneration.brief);
}

function startButton() {
  return screen.getByRole<HTMLButtonElement>("button", {
    name: enUS.imageGeneration.start,
  });
}

function chooseMode(mode: "assisted" | "direct") {
  fireEvent.click(
    screen.getByText(
      mode === "direct"
        ? enUS.imageGeneration.promptModeDirect
        : enUS.imageGeneration.promptModeAssisted,
    ),
  );
}

test("nothing is generated until there is something to draw", () => {
  render(<ImageGenerationSetup />);
  expect(startButton().disabled).toBe(true);

  fireEvent.change(promptBox(), { target: { value: "a red bicycle" } });
  expect(startButton().disabled).toBe(false);
});

test("the page stashes the launch and routes to a new chat", () => {
  render(<ImageGenerationSetup />);
  fireEvent.change(promptBox(), { target: { value: "  a red bicycle  " } });
  fireEvent.click(startButton());

  expect(push).toHaveBeenCalledWith("/workspace/chats/new");
  // Trimmed, and dispatchable by the chat that is about to mount.
  expect(consumeImageLaunch()).toEqual({
    kind: "image",
    promptMode: "assisted",
    prompt: "a red bicycle",
    negativePrompt: undefined,
    aspect: "landscape",
    width: 1344,
    height: 768,
    checkpoint: undefined,
    refine: false,
  });
});

test("the request is shown before it is spent", () => {
  render(<ImageGenerationSetup />);
  fireEvent.change(promptBox(), { target: { value: "a red bicycle" } });
  // The size the run will actually use, not a shape name the model must guess at.
  expect(screen.getByText(/Size: 1344x768 pixels\./)).toBeTruthy();
});

test("the toggle decides who writes the prompt, and the page says which", () => {
  render(<ImageGenerationSetup />);

  // Assisted by default: the assistant writes both halves, so there is no
  // verbatim negative box to fill in and no way to fill one in by accident.
  expect(
    screen.getByText(enUS.imageGeneration.negativePromptWritten),
  ).toBeTruthy();
  expect(
    screen.queryByLabelText(enUS.imageGeneration.negativePrompt),
  ).toBeNull();

  chooseMode("direct");
  expect(
    screen.getByLabelText(enUS.imageGeneration.negativePrompt),
  ).toBeTruthy();
  expect(
    screen.queryByText(enUS.imageGeneration.negativePromptWritten),
  ).toBeNull();
});

test("a verbatim prompt is asked for verbatim, negative prompt included", () => {
  render(<ImageGenerationSetup />);
  chooseMode("direct");
  fireEvent.change(screen.getByLabelText(enUS.imageGeneration.prompt), {
    target: { value: "masterpiece, (neon:1.2), tokyo" },
  });
  fireEvent.change(screen.getByLabelText(enUS.imageGeneration.negativePrompt), {
    target: { value: "blurry, watermark" },
  });
  fireEvent.click(startButton());

  expect(consumeImageLaunch()).toMatchObject({
    promptMode: "direct",
    prompt: "masterpiece, (neon:1.2), tokyo",
    negativePrompt: "blurry, watermark",
  });
});

test("a model that ignores negative prompts is not offered one", () => {
  render(<ImageGenerationSetup />);
  chooseMode("direct");
  fireEvent.change(promptBoxDirect(), { target: { value: "a red bicycle" } });
  fireEvent.change(screen.getByLabelText(enUS.imageGeneration.checkpoint), {
    target: { value: "flux1-dev.safetensors" },
  });

  // Explained, not silently dropped: an accepted field the sampler never reads
  // is the failure this branch exists to prevent.
  expect(
    screen.queryByLabelText(enUS.imageGeneration.negativePrompt),
  ).toBeNull();
  expect(
    screen.getByText(
      enUS.imageGeneration.negativePromptUnsupported("flux1-dev.safetensors"),
    ),
  ).toBeTruthy();
});

function promptBoxDirect() {
  return screen.getByLabelText(enUS.imageGeneration.prompt);
}

test("the resolution is two numbers, and they are the ones the run uses", () => {
  render(<ImageGenerationSetup />);
  fireEvent.change(promptBox(), { target: { value: "a red bicycle" } });
  fireEvent.change(screen.getByLabelText(enUS.imageGeneration.width), {
    target: { value: "1600" },
  });
  fireEvent.change(screen.getByLabelText(enUS.imageGeneration.height), {
    target: { value: "900" },
  });

  // Snapped to the latent grid and shown, so the number that runs is visible
  // before the GPU is spent on it.
  expect(screen.getByText(/Size: 1600x904 pixels\./)).toBeTruthy();

  fireEvent.click(startButton());
  // Snapped on the way out too, so the chat is seeded with the size shown here.
  expect(consumeImageLaunch()).toMatchObject({ width: 1600, height: 904 });
});

test("each side of the resolution is entered on its own", () => {
  render(<ImageGenerationSetup />);
  fireEvent.change(promptBox(), { target: { value: "a red bicycle" } });
  fireEvent.change(screen.getByLabelText(enUS.imageGeneration.width), {
    target: { value: "1600" },
  });
  expect(screen.getByText(/Size: 1600x768 pixels\./)).toBeTruthy();
});

test("a resolution that cannot be rendered blocks the run instead of guessing", () => {
  render(<ImageGenerationSetup />);
  fireEvent.change(promptBox(), { target: { value: "a red bicycle" } });
  fireEvent.change(screen.getByLabelText(enUS.imageGeneration.width), {
    target: { value: "" },
  });

  expect(startButton().disabled).toBe(true);
  expect(
    screen.getByText(enUS.imageGeneration.resolutionWarning(64, 4096)),
  ).toBeTruthy();
});
