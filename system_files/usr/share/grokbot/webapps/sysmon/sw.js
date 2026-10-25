// System monitor service worker: the app shell works offline; live data
// needs grokbotd, history comes from IndexedDB.
const CACHE = "sysmon-v4";
const SHELL = ["./", "index.html", "app.js", "style.css", "icon.svg", "manifest.json", "/_grokbot/tokens.css", "/_grokbot/base.css", "/_grokbot/mascot.js"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/v1/")) return;
  if (u.searchParams.has("gbt")) return; // launcher token: let the server set the cookie
  // network first (updates show at once), cache when grokbotd is not answering
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("index.html"))));
});
