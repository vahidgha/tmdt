/* Service Worker — هیئت امنای مسکن دادگستری زنجان */
const CACHE = 'noyan-v2';
const STATIC = [
  '/static/css/main.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // فقط GET — POST/API را bypass کن
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/login') || url.pathname.startsWith('/logout')) return;

  // استراتژی: network first → cache fallback برای صفحات
  // cache first → network fallback برای static assets
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }))
    );
  } else {
    // برای صفحات HTML همیشه واقعاً از شبکه بگیر (نه از کش دیسک مرورگر)،
    // وگرنه ممکن است تغییرات تازه‌ذخیره‌شده (مثل تنظیمات سایت) دیده نشوند
    e.respondWith(
      fetch(e.request, { cache: 'no-store' })
        .then(res => {
          if (res && res.status === 200 && res.type === 'basic') {
            const clone = res.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return res;
        })
        .catch(() => caches.match(e.request))
    );
  }
});
