self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open("dispatch-desk-static-v6").then((cache) =>
      cache.addAll(["/", "/index.html", "/styles.css", "/app.js", "/manifest.webmanifest", "/dispatch-icon.svg"])
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== "dispatch-desk-static-v6").map((key) => caches.delete(key)))
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
        caches.open("dispatch-desk-static-v6").then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
