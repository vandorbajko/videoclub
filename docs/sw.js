// La aplicación y las carátulas vistas quedan en el móvil para consultar sin cobertura.
// Los datos del catálogo los guarda app.js en localStorage.
const APP = "videoclub-app-v2";
const CARATULAS = "videoclub-caratulas-v1";
const ARCHIVOS = ["./", "index.html", "estilos.css", "app.js", "config.js", "manifest.webmanifest", "icono.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(APP).then((c) => c.addAll(ARCHIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((claves) => Promise.all(claves.filter((k) => ![APP, CARATULAS].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;

  // Carátulas: de la caché si ya se vieron; si no, de TMDB y se guardan.
  if (url.hostname === "image.tmdb.org") {
    e.respondWith(caches.open(CARATULAS).then(async (c) => {
      const guardada = await c.match(e.request);
      if (guardada) return guardada;
      const r = await fetch(e.request);
      if (r.ok || r.type === "opaque") c.put(e.request, r.clone());
      return r;
    }));
    return;
  }

  // La propia aplicación y la librería de Supabase: red primero, caché si no hay conexión.
  if (url.origin === location.origin || url.hostname === "cdn.jsdelivr.net") {
    e.respondWith(fetch(e.request)
      .then((r) => {
        if (r.ok) caches.open(APP).then((c) => c.put(e.request, r.clone()));
        return r;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true })));
  }
});
