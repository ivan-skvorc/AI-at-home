import { describe, expect, test } from "@rstest/core";

import {
  consumeDemocracyLaunch,
  stashDemocracyLaunch,
} from "@/core/threads/democracy";

/**
 * The dialog-to-chat handoff, which needs real storage.
 *
 * A new chat mints its thread id inside the chat instance, after navigation, so
 * the setup dialog cannot write the panel onto a thread that does not exist yet.
 * It stashes instead — and the stash must be claimed exactly once, or a leftover
 * turns the user's next ordinary new chat into a surprise panel.
 */
describe("democracy launch handoff", () => {
  test("a stashed launch is consumed exactly once", () => {
    stashDemocracyLaunch({
      organizer: "organizer",
      participants: ["panelist-a", "panelist-b"],
      task: "assess the sectors",
    });

    expect(consumeDemocracyLaunch()).toEqual({
      organizer: "organizer",
      participants: ["panelist-a", "panelist-b"],
      task: "assess the sectors",
    });
    expect(consumeDemocracyLaunch()).toBeNull();
  });

  test("nothing stashed is not a panel", () => {
    expect(consumeDemocracyLaunch()).toBeNull();
  });

  test("a stash written by an older or broken build is discarded, not run", () => {
    window.localStorage.setItem("deerflow.democracy-launch", "{oops");
    expect(consumeDemocracyLaunch()).toBeNull();
    // Still cleared, so it cannot keep failing on every future new chat.
    expect(window.localStorage.getItem("deerflow.democracy-launch")).toBeNull();
  });
});
