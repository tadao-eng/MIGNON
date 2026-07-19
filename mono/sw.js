// MONO Service Worker — アプリシェルをキャッシュしてオフライン閲覧を可能にする。
// バージョンを上げると古いキャッシュは activate 時に破棄される。
const CACHE = 'mono-v5';

const ASSETS = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './db.js',
  './ai.js',
  './ai-labels.js',
  './scanner.js',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// 同一オリジン: stale-while-revalidate(即表示しつつ裏で更新)
// クロスオリジン(zxing CDN 等): cache-first で一度取れたらオフラインでも使えるようにする
self.addEventListener('fetch', (e) => {
  const { request } = e;
  if (request.method !== 'GET') return;

  e.respondWith(
    caches.match(request).then((cached) => {
      const fetched = fetch(request)
        .then((res) => {
          if (res && res.status === 200 && (res.type === 'basic' || res.type === 'cors')) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(request, clone));
          }
          return res;
        })
        .catch(() => cached);
      return cached || fetched;
    })
  );
});
