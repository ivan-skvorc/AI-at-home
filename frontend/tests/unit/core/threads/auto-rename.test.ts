import { readFileSync } from "node:fs";
import path from "node:path";

import { beforeEach, describe, expect, it, rs } from "@rstest/core";

const fetchWithAuth = rs.fn();

rs.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

import type * as ThreadsAPI from "@/core/threads/api";

const suggestThreadTitle = async (
  ...args: Parameters<typeof ThreadsAPI.suggestThreadTitle>
) => (await import("@/core/threads/api")).suggestThreadTitle(...args);

/**
 * On-demand "Auto rename" from the chat header (fork feature, FORK.md §38).
 *
 * Everything here is silent when broken: the button still renames, it just
 * renames on the wrong model, or spends a call the picker said it would not.
 */

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const read = (relativePath: string) =>
  readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

function respondWith(payload: unknown) {
  fetchWithAuth.mockResolvedValue({ ok: true, json: async () => payload });
}

/** The URL the last call passed to the authenticated fetcher. */
function lastUrl(): string {
  return (fetchWithAuth.mock.calls.at(-1) as [string, RequestInit])[0];
}

/** The JSON body the last call sent, as its raw string. */
function lastBody(): string {
  const [, init] = fetchWithAuth.mock.calls.at(-1) as [string, RequestInit];
  return typeof init.body === "string" ? init.body : "";
}

beforeEach(() => {
  fetchWithAuth.mockReset();
});

describe("what reaches the Gateway", () => {
  it("omits model_name rather than sending null for 'server default'", async () => {
    // The Gateway reads an absent key as "use config.yaml -> title.model_name".
    // A literal null is a different value on the wire and a `model_name: null`
    // that ever starts being *honoured* silently un-configures the operator's
    // title model for every press of the button.
    respondWith({ title: "A name", exchange_count: 1 });

    await suggestThreadTitle({ threadId: "t-1" });

    const body = lastBody();
    expect(JSON.parse(body)).toEqual({});
    expect(body).not.toContain("model_name");
  });

  it("sends the picked model verbatim", async () => {
    respondWith({ title: "A name", exchange_count: 2 });

    await suggestThreadTitle({ threadId: "t-1", modelName: "big-model" });

    expect(JSON.parse(lastBody())).toEqual({ model_name: "big-model" });
  });

  it("surfaces the Gateway's own refusal instead of a generic message", async () => {
    // The two refusals a user can actually hit — a model the operator removed
    // (400) and a conversation with nothing in it yet (409) — both explain
    // themselves in `detail`. Swallowing that leaves "Failed to generate a
    // title." on screen with no way to tell the two apart.
    fetchWithAuth.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Model gpt-legacy is not configured" }),
    });

    await expect(
      suggestThreadTitle({ threadId: "t-1", modelName: "gpt-legacy" }),
    ).rejects.toThrow("Model gpt-legacy is not configured");
  });

  it("percent-encodes the thread id into the path", async () => {
    respondWith({ title: "A name", exchange_count: 1 });

    await suggestThreadTitle({ threadId: "a/b" });

    expect(lastUrl()).toContain("/api/threads/a%2Fb/title/suggest");
  });
});

describe("how the rename is applied", () => {
  it("applies the title through useRenameThread, not its own state write", () => {
    // A second copy of the rename is a copy that stops matching: the cache
    // dance (cancel pending snapshot reads *before* writing the title in) is
    // what stops a list response that started earlier from restoring the old
    // name a moment later. Delegating keeps one copy of it.
    const source = read("src/core/threads/auto-rename.ts");

    expect(source).toContain("useRenameThread");
    expect(source).not.toContain("updateState");
  });

  it("never writes the title from the suggest route", () => {
    // The Gateway refuses a rename with 409 while a run is in flight, and only
    // `POST /{id}/state` holds `reserve_checkpoint_write`. A suggest route that
    // also wrote would put that rule in a second place that cannot enforce it.
    const source = read("src/core/threads/api.ts");
    const suggest = source.slice(
      source.indexOf("export async function suggestThreadTitle"),
    );

    expect(suggest).toContain('method: "POST"');
    expect(suggest).not.toContain("values:");
  });
});

describe("the picker", () => {
  it("reuses the one model picker rather than a flat list", () => {
    // FORK.md §8: a hand-rolled `<Select>` of `models` renders fine and sorts,
    // groups, searches and prices nothing — invisible until someone tries to
    // find a model on this one screen.
    const source = read("src/components/workspace/thread-auto-rename.tsx");

    expect(source).toContain("ModelSelect");
    expect(source).not.toContain("SelectItem");
  });

  it("shares the stored model preference with the automatic rename", () => {
    // One preference, two entry points. A separate key here would mean picking
    // a model in the dialog leaves Settings → Conversation titles disagreeing
    // with it, and neither screen showing the model that will actually run.
    const source = read("src/components/workspace/thread-auto-rename.tsx");

    expect(source).toContain('"autoTitle"');
    expect(source).toContain("settings.autoTitle.modelName");
  });
});
