import { expect, test } from "@rstest/core";

import { pathOfSearchHit, type WorkspaceSearchHit } from "@/core/search/api";

const hit: WorkspaceSearchHit = {
  type: "thread",
  thread_id: "root",
  title: "Trip plan",
  agent_name: null,
  archived: false,
  updated_at: "2026-11-15T00:00:00Z",
  project_id: null,
  snippet: [{ text: "Trip plan" }],
};

// Fork (§18): an edited conversation opens the version the user last switched
// to, as its sidebar entry does; a message lives in exactly one version.
test("a thread hit opens its active edit version and a message hit stays on its thread", () => {
  expect(pathOfSearchHit({ ...hit, open_thread_id: "v2" })).toBe(
    "/workspace/chats/v2",
  );
  expect(pathOfSearchHit(hit)).toBe("/workspace/chats/root");
  expect(
    pathOfSearchHit({
      ...hit,
      type: "message",
      open_thread_id: "v2",
      message_id: "m",
      seq: 3,
    }),
  ).toBe("/workspace/chats/root?message=m&message_seq=3");
});
