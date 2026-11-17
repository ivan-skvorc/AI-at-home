import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import { AutoTitlePreferenceSync } from "@/components/workspace/settings/auto-title-preference-sync";
import {
  AUTO_TITLE_SYNCED_STORAGE_KEY,
  hydrateAutoTitlePreference,
  setAutoTitlePreference,
} from "@/core/settings/auto-title-sync";
import { getLocalSettings } from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  updateLocalSettings,
} from "@/core/settings/store";
import { autoTitleRunContext } from "@/core/threads/run-context";

/**
 * Settings → Conversation titles follows the account (fork feature, FORK.md
 * §33). The preference used to live only in one browser origin, so another
 * device, the PWA or the tailnet hostname kept renaming conversations the user
 * had told this browser not to. What is pinned here fails silently: the switch
 * still renders, it just shows (and sends) a value the account does not hold.
 */

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  staticMode: false,
  user: { id: "alice" } as { id: string } | null,
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => mocks.staticMode,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));

const ENDPOINT = "/api/settings/auto-title";

type Call = { method: string; body: unknown };

function calls(): Call[] {
  return mocks.fetch.mock.calls.map(([url, init]) => {
    expect(url).toBe(ENDPOINT);
    const request = (init ?? {}) as RequestInit;
    return {
      method: request.method ?? "GET",
      body:
        typeof request.body === "string"
          ? (JSON.parse(request.body) as unknown)
          : undefined,
    };
  });
}

/** Answer GET with `server`, and PUT by echoing what was sent (the store). */
function serve(server: unknown) {
  mocks.fetch.mockImplementation(async (_url: string, init?: RequestInit) =>
    init?.method === "PUT"
      ? Response.json(JSON.parse(init.body as string))
      : Response.json(server),
  );
}

function setLocal(enabled: boolean, modelName?: string) {
  updateLocalSettings("autoTitle", { enabled, modelName });
}

const local = () => getBaseSettingsSnapshot().autoTitle;

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.staticMode = false;
  mocks.user = { id: "alice" };
  setLocal(true, undefined);
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

describe("hydration", () => {
  it("adopts an opt-out the account holds, for the switch and the next run", async () => {
    // The new-device case: this browser has the local default (on), the
    // account says off. Without this, every new device renamed again.
    localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
    serve({ enabled: false });

    await expect(hydrateAutoTitlePreference()).resolves.toBe("adopted");

    expect(local()).toEqual({ enabled: false, modelName: undefined });
    expect(getLocalSettings().autoTitle.enabled).toBe(false);
    expect(autoTitleRunContext()).toEqual({ auto_title_enabled: false });
    expect(calls()).toEqual([{ method: "GET", body: undefined }]);
  });

  it("clears a local model when the account follows the operator's", async () => {
    localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
    setLocal(true, "old-pick");
    serve({ enabled: true });

    await hydrateAutoTitlePreference();

    expect(local()).toEqual({ enabled: true, modelName: undefined });
  });

  it.each([
    ["is unreachable", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["answers with an error", async () => Response.json({}, { status: 503 })],
    ["answers something unusable", async () => Response.json({ ok: true })],
  ])(
    "keeps this browser's value when the Gateway %s",
    async (_label, answer) => {
      // "Unknown" is neither on nor off. Reading a failed read as the
      // never-set default would switch renaming back on for someone who
      // turned it off; reading it as "off" would do the opposite.
      for (const enabled of [false, true]) {
        setLocal(enabled, undefined);
        mocks.fetch.mockImplementation(answer);

        await expect(hydrateAutoTitlePreference()).resolves.toBe("unreachable");

        expect(local().enabled).toBe(enabled);
      }
    },
  );

  it("never contacts a Gateway in the static demo", async () => {
    mocks.staticMode = true;

    await expect(hydrateAutoTitlePreference()).resolves.toBe("static");
    await expect(setAutoTitlePreference({ enabled: false })).resolves.toBe(
      "local",
    );

    expect(mocks.fetch).not.toHaveBeenCalled();
    // Still a working setting: it lives in this browser there.
    expect(local().enabled).toBe(false);
  });

  it("uploads an opt-out this browser held before the account could store it", async () => {
    // The upgrade case. The account has never saved a preference, and this
    // browser was the only place the opt-out existed. Adopting the default
    // would switch renaming back on for exactly the people who turned it off.
    // A Gateway without the `stored` flag gets the same, from the shape.
    for (const server of [
      { enabled: true, stored: false },
      { enabled: true },
    ]) {
      localStorage.clear();
      mocks.fetch.mockReset();
      setLocal(false, undefined);
      serve(server);

      await expect(hydrateAutoTitlePreference()).resolves.toBe("migrated");

      expect(calls()).toEqual([
        { method: "GET", body: undefined },
        { method: "PUT", body: { enabled: false } },
      ]);
      expect(local().enabled).toBe(false);
      expect(
        localStorage.getItem(AUTO_TITLE_SYNCED_STORAGE_KEY),
      ).not.toBeNull();
    }
  });

  it("keeps an 'on' the account stored over a stale opt-out in a new origin", async () => {
    // Origin A uploaded its opt-out, then the user turned renaming back on
    // there. Origin B, opened for the first time since the upgrade, still
    // holds the old opt-out. The account's explicit "on" reads exactly like
    // the never-set default, so only `stored` keeps B from reverting it.
    setLocal(false, undefined);
    serve({ enabled: true, stored: true });

    await expect(hydrateAutoTitlePreference()).resolves.toBe("adopted");

    expect(calls().map((call) => call.method)).toEqual(["GET"]);
    expect(local()).toEqual({ enabled: true, modelName: undefined });
    expect(localStorage.getItem(AUTO_TITLE_SYNCED_STORAGE_KEY)).not.toBeNull();
  });

  it("lets the account win once this browser has been reconciled", async () => {
    // After the first sync the local copy is a cache: turning renaming back on
    // from another device must reach this one too.
    localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
    setLocal(false, undefined);
    serve({ enabled: true });

    await expect(hydrateAutoTitlePreference()).resolves.toBe("adopted");

    expect(local().enabled).toBe(true);
    expect(calls().map((call) => call.method)).toEqual(["GET"]);
  });

  it("does not overwrite a change the user made while the read was in flight", async () => {
    localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
    let answerRead: (response: Response) => void = () => undefined;
    mocks.fetch.mockImplementation((_url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? Promise.resolve(Response.json(JSON.parse(init.body as string)))
        : new Promise<Response>((resolve) => (answerRead = resolve)),
    );

    const hydration = hydrateAutoTitlePreference();
    await expect(setAutoTitlePreference({ enabled: false })).resolves.toBe(
      "saved",
    );
    answerRead(Response.json({ enabled: true }));

    await expect(hydration).resolves.toBe("superseded");
    expect(local().enabled).toBe(false);
  });
});

describe("write-through", () => {
  it("saves every change to the account, model key included", async () => {
    serve({ enabled: true });

    await expect(setAutoTitlePreference({ enabled: false })).resolves.toBe(
      "saved",
    );
    await setAutoTitlePreference({ enabled: true, modelName: "" });
    await setAutoTitlePreference({ modelName: undefined });

    expect(calls()).toEqual([
      { method: "PUT", body: { enabled: false } },
      // `""` is "no model call", a choice of its own…
      { method: "PUT", body: { enabled: true, model_name: "" } },
      // …and an omitted key is how "server default" is stored.
      { method: "PUT", body: { enabled: true } },
    ]);
  });

  it("adopts the value the account normalized", async () => {
    mocks.fetch.mockImplementation(async () =>
      Response.json({ enabled: true, model_name: "trimmed" }),
    );

    await setAutoTitlePreference({ modelName: "  trimmed  " });

    expect(local().modelName).toBe("trimmed");
  });

  it("puts the switch back when the account did not take the change", async () => {
    localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
    serve({ enabled: true });
    await hydrateAutoTitlePreference();
    mocks.fetch.mockImplementation(async () =>
      Response.json({ detail: "boom" }, { status: 500 }),
    );

    await expect(setAutoTitlePreference({ enabled: false })).resolves.toBe(
      "failed",
    );

    // Showing "off" while the account (and so every IM channel and other
    // device) still renames would be the original bug wearing a new face.
    expect(local().enabled).toBe(true);
  });

  it("keeps the change when nothing confirmed is known to roll back to", async () => {
    mocks.fetch.mockImplementation(async () =>
      Response.json({}, { status: 503 }),
    );
    await hydrateAutoTitlePreference();

    await expect(setAutoTitlePreference({ enabled: false })).resolves.toBe(
      "failed",
    );

    expect(local().enabled).toBe(false);
  });

  it("sends changes one at a time, in the order they were made", async () => {
    // Two whole-value PUTs racing could land out of order and leave the
    // account on the older choice while the switch shows the newer one.
    const pending: Array<() => void> = [];
    mocks.fetch.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((resolve) =>
          pending.push(() =>
            resolve(Response.json(JSON.parse(init!.body as string))),
          ),
        ),
    );

    const first = setAutoTitlePreference({ enabled: false });
    const second = setAutoTitlePreference({ enabled: true });
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    expect(calls()[0]!.body).toEqual({ enabled: false });

    pending.shift()!();
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2));
    expect(calls()[1]!.body).toEqual({ enabled: true });
    pending.shift()!();

    await expect(first).resolves.toBe("saved");
    await expect(second).resolves.toBe("saved");
    // The older write's answer never overrides the newer choice on screen.
    expect(local().enabled).toBe(true);
  });
});

describe("the workspace mount", () => {
  it("reads the account once it knows who is signed in", async () => {
    localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
    serve({ enabled: false });
    // With auth disabled every request is the `default` user, and the
    // Gateway still stores that user's preference.
    mocks.user = { id: "default" };

    render(<AutoTitlePreferenceSync />);

    await waitFor(() => expect(local().enabled).toBe(false));
    expect(calls()).toEqual([{ method: "GET", body: undefined }]);
  });

  it("does not read before the user is known, nor in the static demo", async () => {
    mocks.user = null;
    const { unmount } = render(<AutoTitlePreferenceSync />);
    unmount();
    mocks.user = { id: "alice" };
    mocks.staticMode = true;
    render(<AutoTitlePreferenceSync />);

    await act(async () => undefined);
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it("drops a read the workspace no longer wants", async () => {
    localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
    let answerRead: (response: Response) => void = () => undefined;
    let signal: AbortSignal | undefined;
    mocks.fetch.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((resolve) => {
          signal = init?.signal ?? undefined;
          answerRead = resolve;
        }),
    );

    const { unmount } = render(<AutoTitlePreferenceSync />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => answerRead(Response.json({ enabled: false })));

    expect(local().enabled).toBe(true);
  });
});
