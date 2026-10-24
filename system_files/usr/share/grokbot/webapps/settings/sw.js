// Settings app shell cache: the window opens (with an offline notice)
// even when grokbotd is down. OS API calls are never cached.
const CACHE = "settings-v6";
const SHELL = ["./", "index.html", "app.js", "i18n.js", "style.css", "/_grokbot/tokens.css", "/_grokbot/base.css", "/_grokbot/mascot.js"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/v1/")) return;
  if (u.searchParams.has("gbt")) return; // launcher token: let the server set the cookie
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then((r) => r || caches.match("index.html"))));
});
