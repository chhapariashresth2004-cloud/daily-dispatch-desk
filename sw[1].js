self.CACHE_NAME = "dispatch-desk-static-v7-reviewer-refresh";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(self.CACHE_NAME).then((cache) =>
      cache.addAll(["/", "/index.html", "/styles.css?v=20260602-reviewer-refresh", "/app.js?v=20260602-reviewer-refresh", "/manifest.webmanifest", "/dispatch-icon.svg"])
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== self.CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/uploads/")) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(self.CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
