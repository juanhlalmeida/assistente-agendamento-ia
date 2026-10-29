// app/static/sw.js
// Service Worker enxuto e seguro para SaaS B2B (Render-compatible)
// Estratégia:
// - Network-First para rotas dinâmicas (HTML, API, Dashboard, Agenda) -> Nunca exibe agenda desatualizada
// - Cache-First apenas para ativos estáticos (CSS, fontes, ícones, manifest)

const CACHE_NAME = 'agenda-saas-static-v1';
const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/manifest.json',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch(() => {});
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      )
    ).then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  return (
    url.pathname.startsWith('/static/') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') ||
    url.hostname.includes('unpkg.com')
  );
}

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Ignora métodos não-GET (POST de formulários, exclusão, webhooks, etc.)
  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);

  // 1. Cache-First para fontes e arquivos estáticos
  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }
        return fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
          }
          return networkResponse;
        });
      })
    );
    return;
  }

  // 2. Network-First para todas as rotas dinâmicas (Agenda, Dashboard, Clientes, API)
  event.respondWith(
    fetch(request)
      .then((networkResponse) => {
        return networkResponse;
      })
      .catch(() => {
        return caches.match(request);
      })
  );
});
