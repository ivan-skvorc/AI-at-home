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
      prompt: "a red bicycle",
      aspect: "square",
      refine: true,
    });

    expect(consumeImageLaunch()).toEqual({
      kind: "image",
      prompt: "a red bicycle",
      aspect: "square",
      checkpoint: undefined,
      refine: true,
    });
    expect(consumeImageLaunch()).toBeNull();
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
