import { describe, expect, it } from "@rstest/core";

import {
  requestsThreadFilesPanel,
  routeShowsThread,
  withoutThreadFilesPanel,
} from "@/core/thread-files/deep-link";

describe("?panel=files deep link", () => {
  it("is addressed only to the chat the URL names", () => {
    const params = new URLSearchParams("panel=files");
    expect(requestsThreadFilesPanel("/workspace/chats/t1", params, "t1")).toBe(
      true,
    );
    expect(
      requestsThreadFilesPanel(
        "/workspace/agents/helper/chats/t1",
        params,
        "t1",
      ),
    ).toBe(true);
    // A kept-alive chat still mounted while the URL already shows the next.
    expect(requestsThreadFilesPanel("/workspace/chats/t2", params, "t1")).toBe(
      false,
    );
    expect(
      requestsThreadFilesPanel(
        "/workspace/chats/t1",
        new URLSearchParams("panel=artifacts"),
        "t1",
      ),
    ).toBe(false);
    expect(routeShowsThread("/workspace/projects/t1", "t1")).toBe(false);
    expect(routeShowsThread("/workspace/chats/%E0%A4%A", "t1")).toBe(false);
  });

  it("removes only the panel parameter", () => {
    expect(
      withoutThreadFilesPanel(
        "/workspace/chats/t1",
        new URLSearchParams("panel=files&mock=true"),
      ),
    ).toBe("/workspace/chats/t1?mock=true");
    expect(
      withoutThreadFilesPanel(
        "/workspace/chats/t1",
        new URLSearchParams("panel=files"),
      ),
    ).toBe("/workspace/chats/t1");
  });
});
