import { describe, expect, test } from "@rstest/core";

import {
  consumeImageLaunch,
  stashImageLaunch,
} from "@/core/threads/image-generation";

/**
 * The setup-page-to-chat handoff, which needs real storage.
 *
 * A new chat mints its thread id inside the chat instance, after navigation, so
 * the setup page cannot write onto a thread that does not exist yet. It stashes
 * instead — and the stash must be claimed exactly once, or a leftover turns the
 * user's next ordinary new chat into a surprise generation run.
 */
describe("image launch handoff", () => {
  test("a stashed launch is consumed exactly once", () => {
    stashImageLaunch({
      kind: "image",
      promptMode: "direct",
      prompt: "a red bicycle",
      negativePrompt: "blurry",
      aspect: "square",
      width: 1024,
      height: 1024,
      refine: true,
    });

    expect(consumeImageLaunch()).toEqual({
      kind: "image",
      promptMode: "direct",
      prompt: "a red bicycle",
      negativePrompt: "blurry",
      aspect: "square",
      width: 1024,
      height: 1024,
      checkpoint: undefined,
      refine: true,
    });
    expect(consumeImageLaunch()).toBeNull();
  });

  test("the entered resolution survives the handoff", () => {
    // The numbers are the whole reason the field exists; a round trip that
    // quietly restores the preset would look identical on screen.
    stashImageLaunch({
      kind: "image",
      promptMode: "assisted",
      prompt: "a red bicycle",
      aspect: "landscape",
      width: 1600,
      height: 904,
      refine: false,
    });

    expect(consumeImageLaunch()).toMatchObject({
      promptMode: "assisted",
      width: 1600,
      height: 904,
    });
  });

  test("nothing stashed is not a launch", () => {
    expect(consumeImageLaunch()).toBeNull();
  });

  test("a stash written by an older or broken build is discarded, not run", () => {
    window.localStorage.setItem("deerflow.image-launch", "{oops");
    expect(consumeImageLaunch()).toBeNull();
    // Still cleared, so it cannot keep failing on every future new chat.
    expect(window.localStorage.getItem("deerflow.image-launch")).toBeNull();
  });
});
