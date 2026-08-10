import { describe, expect, it } from "@rstest/core";

import {
  describeDevice,
  detectPushSupport,
  urlBase64ToUint8Array,
} from "@/core/notification/push";

/**
 * Web Push support detection (fork feature, roadmap item 7).
 *
 * The property that matters most is the *insecure context* branch: the fork's
 * documented deployment is a plain-HTTP LAN address, where browsers disable
 * service workers entirely. Reporting that specifically — rather than "service
 * workers unavailable" — is the difference between a user who reaches the app
 * over Tailscale HTTPS and one who goes hunting for a browser setting that
 * does not exist.
 */
describe("detectPushSupport", () => {
  // `globalThis.navigator` is a read-only getter in the node test environment,
  // so each global is installed with defineProperty rather than assignment.
  function setGlobals(props: {
    window?: Record<string, unknown> | undefined;
    navigator?: Record<string, unknown>;
    notification?: boolean;
  }) {
    // In a browser `window === globalThis`, so the fake window carries the
    // constructors the detector probes with `in`.
    const win =
      props.window === undefined
        ? undefined
        : {
            ...props.window,
            ...(props.notification === false ? {} : { Notification: class {} }),
          };
    for (const [name, value] of [
      ["window", win],
      ["navigator", props.navigator ?? {}],
      ["Notification", props.notification === false ? undefined : class {}],
    ] as const) {
      Object.defineProperty(globalThis, name, {
        value,
        configurable: true,
        writable: true,
      });
    }
  }

  it("reports insecure-context first, because it makes everything else absent too", () => {
    setGlobals({
      window: { isSecureContext: false },
      navigator: {},
      notification: false,
    });
    expect(detectPushSupport()).toEqual({
      supported: false,
      reason: "insecure-context",
    });
  });

  it("reports a missing service worker on a secure origin", () => {
    setGlobals({
      window: { isSecureContext: true, PushManager: class {} },
      navigator: {},
    });
    expect(detectPushSupport()).toEqual({
      supported: false,
      reason: "no-service-worker",
    });
  });

  it("reports a missing Push API", () => {
    setGlobals({
      window: { isSecureContext: true },
      navigator: { serviceWorker: {} },
    });
    expect(detectPushSupport()).toEqual({
      supported: false,
      reason: "no-push-manager",
    });
  });

  it("reports a missing Notification API", () => {
    setGlobals({
      window: { isSecureContext: true, PushManager: class {} },
      navigator: { serviceWorker: {} },
      notification: false,
    });
    expect(detectPushSupport()).toEqual({
      supported: false,
      reason: "no-notifications",
    });
  });

  it("reports support when every piece is present", () => {
    setGlobals({
      window: { isSecureContext: true, PushManager: class {} },
      navigator: { serviceWorker: {} },
    });
    expect(detectPushSupport()).toEqual({ supported: true });
  });

  it("is safe on the server, where there is no window at all", () => {
    setGlobals({ window: undefined });
    expect(detectPushSupport().supported).toBe(false);
  });
});

describe("urlBase64ToUint8Array", () => {
  it("decodes an unpadded base64url VAPID key", () => {
    // "hello" as base64url, unpadded — the shape a VAPID key actually arrives in.
    const bytes = urlBase64ToUint8Array("aGVsbG8");
    expect(Array.from(bytes)).toEqual([104, 101, 108, 108, 111]);
  });

  it("maps the url-safe alphabet back", () => {
    // 0xFB 0xFF decodes from "-_8" under base64url ("+/8" under standard base64).
    expect(Array.from(urlBase64ToUint8Array("-_8"))).toEqual([251, 255]);
  });

  it("is backed by a plain ArrayBuffer so it satisfies BufferSource", () => {
    // Not cosmetic: PushManager.subscribe rejects a SharedArrayBuffer-backed view.
    expect(urlBase64ToUint8Array("aGVsbG8").buffer).toBeInstanceOf(ArrayBuffer);
  });
});

describe("describeDevice", () => {
  it("names the browser and platform so several devices are tellable apart", () => {
    expect(
      describeDevice(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
      ),
    ).toBe("Safari on iOS");
    expect(
      describeDevice(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      ),
    ).toBe("Chrome on Linux");
  });

  it("degrades to a generic label rather than throwing on an unknown agent", () => {
    expect(describeDevice("")).toBe("browser on device");
  });
});
