/*
 * DeerFlow service worker (fork feature).
 *
 * Deliberately minimal: it exists so Web Push can be delivered with the browser
 * closed, and so the app is installable. It does NOT cache application assets.
 *
 * That last point is a decision, not an omission. DeerFlow is a live,
 * server-driven app — SSE streams, per-thread state, an API that changes with
 * every backend release. A stale cached shell served after an upgrade produces
 * bugs that look like backend faults and are miserable to diagnose, which is a
 * far worse trade than the offline support nobody asked for. Adding caching
 * later means adding a version/cleanup strategy with it.
 */

self.addEventListener("install", () => {
  // Take over immediately rather than waiting for every tab to close; there is
  // no cached state to migrate, so there is nothing to be careful about.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    // A push whose payload will not parse is still worth surfacing — the user
    // asked to be told when something finished, and silence is the one
    // outcome that makes them stop trusting the feature.
    payload = {};
  }

  const title = payload.title || "DeerFlow";
  const options = {
    body: payload.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: payload.tag || "deerflow",
    renotify: true,
    data: { url: payload.url || "/" },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target =
    (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        // Prefer focusing an open tab over opening another one: a notification
        // that spawns a duplicate window every time is its own annoyance.
        for (const client of clientList) {
          if ("focus" in client) {
            if ("navigate" in client && client.url !== target) {
              return client.navigate(target).then((c) => c && c.focus());
            }
            return client.focus();
          }
        }
        return self.clients.openWindow(target);
      }),
  );
});
