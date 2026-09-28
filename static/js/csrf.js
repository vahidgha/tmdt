/* CSRF — همه درخواست‌های تغییردهنده (POST/PATCH/DELETE) به‌صورت خودکار
   هدر X-CSRFToken می‌گیرند. توکن از تگ meta در <head> خوانده می‌شود. */
(function () {
  var meta  = document.querySelector('meta[name="csrf-token"]');
  var token = meta ? meta.getAttribute('content') : '';
  if (!token) return;

  var SAFE = ['GET', 'HEAD', 'OPTIONS', 'TRACE'];
  var origFetch = window.fetch;

  window.fetch = function (input, init) {
    init = init || {};
    var method = (init.method || (input && input.method) || 'GET').toUpperCase();
    var url    = typeof input === 'string' ? input : (input && input.url) || '';
    var sameOrigin = !/^https?:\/\//i.test(url) || url.indexOf(location.origin) === 0;

    if (sameOrigin && SAFE.indexOf(method) === -1) {
      if (input instanceof Request && !init.headers) {
        input = new Request(input);
        input.headers.set('X-CSRFToken', token);
      } else {
        var h = new Headers(init.headers || {});
        h.set('X-CSRFToken', token);
        init.headers = h;
      }
    }
    return origFetch.call(this, input, init);
  };
})();
