import { describe, expect, test } from "@rstest/core";

import {
  consumeDemocracyFiles,
  consumeDemocracyLaunch,
  stashDemocracyFiles,
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
      grading: "five_point",
    });

    expect(consumeDemocracyLaunch()).toEqual({
      organizer: "organizer",
      participants: ["panelist-a", "panelist-b"],
      task: "assess the sectors",
      grading: "five_point",
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

/**
 * Attachments ride a module-level carrier rather than the localStorage stash: a
 * `File` is a handle to browser-held bytes and does not survive JSON, and there
 * is no thread to upload against until the chat exists.
 */
describe("democracy file handoff", () => {
  function file(name: string) {
    return new File(["x"], name, { type: "text/plain" });
  }

  test("files are handed over exactly once", () => {
    stashDemocracyFiles([file("a.csv"), file("b.pdf")]);
    expect(consumeDemocracyFiles().map((f) => f.name)).toEqual([
      "a.csv",
      "b.pdf",
    ]);
    expect(consumeDemocracyFiles()).toEqual([]);
  });

  test("the carrier is copied, so the caller's array cannot mutate it later", () => {
    const picked = [file("a.csv")];
    stashDemocracyFiles(picked);
    picked.push(file("sneaky.pdf"));
    expect(consumeDemocracyFiles()).toHaveLength(1);
  });

  test("an abandoned setup does not leak its files into the next panel", () => {
    // Files stashed with no launch behind them belong to a setup the user walked
    // away from; claiming nothing must also drop them, or the next panel starts
    // with a stranger's attachments.
    stashDemocracyFiles([file("abandoned.csv")]);
    expect(consumeDemocracyLaunch()).toBeNull();
    expect(consumeDemocracyFiles()).toEqual([]);
  });
});
