/**
 * Web Push subscription plumbing (fork feature).
 *
 * The fork's use case is "start a run from my phone over Tailscale, pocket it,
 * get pinged when it's done". The plain `Notification` API cannot do that — it
 * only fires while the tab is open, and iOS Safari will not deliver at all
 * without an installed PWA. This module owns the service worker + Web Push
 * path that can.
 *
 * The awkward part is the **secure context** requirement, and it is the reason
 * for most of the code below. Service workers are only available on a secure
 * origin: `https://…` or `http://localhost`. The fork's documented deployment
 * — a plain-HTTP LAN address like `http://192.168.1.10:2026` — is *not* one,
 * so on exactly the device this feature targets the API is simply absent.
 *
 * Silently doing nothing there is the worst possible behavior: the user toggles
 * a switch, nothing happens, and there is no way to find out why. So the
 * unsupported cases are enumerated and each returns a reason the UI shows
 * verbatim, including the fix (reach the app over Tailscale's HTTPS name, or
 * over `localhost` on the machine itself).
 */

export type PushSupport =
  | { supported: true }
  | { supported: false; reason: PushUnsupportedReason };

export type PushUnsupportedReason =
  | "insecure-context"
  | "no-service-worker"
  | "no-push-manager"
  | "no-notifications";

export interface PushConfig {
  available: boolean;
  reason: string;
  public_key: string | null;
  subscriptions: number;
}

/**
 * Why the browser cannot do push here — checked in the order that produces the
 * most useful message, since an insecure origin makes everything else absent
 * too and "service workers are unavailable" would send the user hunting for a
 * browser setting that does not exist.
 */
export function detectPushSupport(): PushSupport {
  if (typeof window === "undefined") {
    return { supported: false, reason: "no-service-worker" };
  }
  if (!window.isSecureContext) {
    return { supported: false, reason: "insecure-context" };
  }
  if (!("serviceWorker" in navigator)) {
    return { supported: false, reason: "no-service-worker" };
  }
  if (!("PushManager" in window)) {
    return { supported: false, reason: "no-push-manager" };
  }
  if (!("Notification" in window)) {
    return { supported: false, reason: "no-notifications" };
  }
  return { supported: true };
}

/**
 * VAPID keys arrive base64url; `PushManager.subscribe` wants raw bytes.
 *
 * Backed by an explicit `ArrayBuffer` rather than the `new Uint8Array(length)`
 * shorthand: since TS 5.7 the latter is `Uint8Array<ArrayBufferLike>`, which
 * does not satisfy `BufferSource` because it could be a `SharedArrayBuffer`.
 */
export function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalized);
  const output = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) {
    output[i] = raw.charCodeAt(i);
  }
  return output;
}

/** A human label for the device, so a user with several can tell them apart. */
export function describeDevice(userAgent: string): string {
  const ua = userAgent || "";
  const platform = /iPhone|iPad|iPod/i.test(ua)
    ? "iOS"
    : /Android/i.test(ua)
      ? "Android"
      : /Mac OS X/i.test(ua)
        ? "macOS"
        : /Windows/i.test(ua)
          ? "Windows"
          : /Linux/i.test(ua)
            ? "Linux"
            : "device";
  const browser = /Edg\//i.test(ua)
    ? "Edge"
    : /OPR\//i.test(ua)
      ? "Opera"
      : /Chrome\//i.test(ua)
        ? "Chrome"
        : /Firefox\//i.test(ua)
          ? "Firefox"
          : /Safari\//i.test(ua)
            ? "Safari"
            : "browser";
  return `${browser} on ${platform}`;
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  const support = detectPushSupport();
  if (!support.supported) {
    return null;
  }
  try {
    return await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch (error) {
    console.warn("Service worker registration failed", error);
    return null;
  }
}

export async function fetchPushConfig(): Promise<PushConfig | null> {
  try {
    const response = await fetch("/api/push/config", {
      credentials: "include",
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as PushConfig;
  } catch {
    return null;
  }
}

/**
 * Subscribe this browser and register it server-side.
 *
 * Reuses an existing subscription when the browser already has one for our
 * key: re-subscribing mints a new endpoint, which would leave the old one
 * stored server-side and undeliverable until a push service 410s it.
 */
export async function subscribeToPush(publicKey: string): Promise<boolean> {
  const registration = await registerServiceWorker();
  if (!registration) {
    return false;
  }
  if (Notification.permission !== "granted") {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      return false;
    }
  }

  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    }));

  const payload = {
    ...subscription.toJSON(),
    label: describeDevice(
      typeof navigator === "undefined" ? "" : navigator.userAgent,
    ),
  };
  const response = await fetch("/api/push/subscribe", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.ok;
}

export async function unsubscribeFromPush(): Promise<boolean> {
  const support = detectPushSupport();
  if (!support.supported) {
    return false;
  }
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) {
    return true;
  }
  // Tell the server first: if the browser-side unsubscribe succeeds and the
  // server call then fails, the server keeps pushing to a dead endpoint until
  // a 410 prunes it.
  await fetch("/api/push/unsubscribe", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  return subscription.unsubscribe();
}

export async function sendTestPush(): Promise<{
  delivered: number;
  subscriptions: number;
} | null> {
  try {
    const response = await fetch("/api/push/test", {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as {
      delivered: number;
      subscriptions: number;
    };
  } catch {
    return null;
  }
}
