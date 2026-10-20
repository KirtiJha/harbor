// Porthaven's service worker exists so the dashboard can be installed as an app (its own window, dock icon and
// badge). It caches nothing: the dashboard is always live.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
