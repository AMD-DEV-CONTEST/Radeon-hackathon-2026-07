const CACHE_NAME = "ielts-os-demo-v95";
const MEDIA_CACHE_NAME = "ielts-os-media-v1";
const REMOTE_CONTENT_CACHE = "ielts-os-remote-content-v1";

const APP_SHELL = [
  "./",
  "./index.html",
  "./app-reliability.js?v=1",
  "./learning-core.js?v=2",
  "./remote-update.js?v=18",
  "./styles.css?v=60",
  "./app.js?v=78",
  "./manifest.json",
  "./icons/icon.svg",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./data/wordbook.json",
  "./data/practice.json",
  "./data/listening.json",
  "./data/writing.json",
  "./data/reading.json",
  "./data/wrong-questions.json",
  "./data/synonyms.json",
  "./data/tests.json",
  "./data/content-manifest.json",
  "./data/audio-map.json",
  "./data/study-paths.json",
  "./data/content-roadmap.json",
  "./content-packs/library-catalog.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME && key !== MEDIA_CACHE_NAME && key !== REMOTE_CONTENT_CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (["audio", "video"].includes(event.request.destination)) {
    event.respondWith(caches.open(MEDIA_CACHE_NAME).then(async (cache) => (await cache.match(event.request)) || fetch(event.request)));
    return;
  }
  if (url.origin !== self.location.origin) return;
  const shellRequest = APP_SHELL.some((path) => new URL(path, self.location.href).href === url.href);
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (shellRequest && response.ok && response.type === "basic") {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(async () => {
        const cached = shellRequest ? await caches.match(event.request) : null;
        if (cached) return cached;
        if (event.request.mode === "navigate") return caches.match("./index.html");
        throw new Error("offline resource unavailable");
      })
  );
});
