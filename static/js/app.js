/* ══════════════════════════════════════════════════════
   سامانه مدیریت اعضا و امور مالی — App JS v2
   ══════════════════════════════════════════════════════ */

/* ── Theme ─────────────────────────────────────────── */
function _applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const btn = document.getElementById('themeBtn');
  if (btn) btn.textContent = t === 'dark' ? '☀️' : '🌙';
}
function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  localStorage.setItem('theme', next);
  _applyTheme(next);
}
_applyTheme(localStorage.getItem('theme') || 'light');

/* ── HTML escaping ──────────────────────────────────────
   استفاده در همه‌جا که متن آزاد کاربر (نام، پیام، توضیحات و...) داخل
   innerHTML/template literal قرار می‌گیرد — چه در متن، چه داخل attribute.
   اگر یک فایل خودش تابع esc محلی جداگانه تعریف کرده باشد، همان اولویت
   دارد (این تابع سراسری فقط برای فایل‌هایی است که تابع محلی ندارند). */
if (typeof window.esc === 'undefined') {
  window.esc = function (s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
}

/* ── Helper ─────────────────────────────────────────── */
function $v(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
}

/* ── Toast ──────────────────────────────────────────── */
function toast(msg, type = 'default', ms = 3000) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  const icons = { default: '✓', error: '✕', warn: '⚠' };
  el.textContent = (icons[type] || icons.default) + '  ' + msg;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), ms);
}

/* ── Modal ──────────────────────────────────────────── */
const modal = {
  open(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add('open');
    // trap focus
    setTimeout(() => {
      const first = el.querySelector('input,select,textarea,button');
      if (first) first.focus();
    }, 50);
  },
  close(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('open');
    // فرم‌های داخل مودال به‌طور پیش‌فرض پاک می‌شوند تا دفعه بعد که مودال باز
    // می‌شود، مقادیر نیمه‌کاره قبلی نمانَد (مثلاً «+ افزودن» که با انصراف بسته
    // شده). مودال‌هایی که باید مقدارشان بماند (نادر) با data-no-autoreset
    // می‌توانند این رفتار را غیرفعال کنند.
    if (el.dataset.noAutoreset === undefined) {
      el.querySelectorAll('input, textarea').forEach(f => {
        if (f.dataset.keep !== undefined || f.type === 'hidden' || f.type === 'button' || f.type === 'submit') return;
        if (f.type === 'checkbox' || f.type === 'radio') f.checked = f.defaultChecked;
        else f.value = f.defaultValue || '';
      });
      el.querySelectorAll('select').forEach(s => {
        if (s.dataset.keep !== undefined) return;
        const defOpt = Array.from(s.options).findIndex(o => o.defaultSelected);
        s.selectedIndex = defOpt >= 0 ? defOpt : 0;
      });
    }
  },
};

/* ── Image Viewer (لایت‌باکس مشترک) ──────────────────────────────────────
   استفاده: imgViewer.open([{src:'/uploads/x.jpg', label:'نام فایل'}, ...], startIndex)
   یک آیتم هم قابل قبول است — گروه تک‌عضوی، دکمه‌های قبلی/بعدی خودکار مخفی می‌شوند. */
const imgViewer = {
  images: [],
  idx: 0,
  zoomed: false,
  _el: null,

  open(images, startIndex) {
    this.images = (Array.isArray(images) ? images : [images]).filter(x => x && x.src);
    if (!this.images.length) return;
    this.idx = startIndex || 0;
    this.zoomed = false;
    this._ensure();
    this._render();
    this._el.classList.add('open');
    document.body.style.overflow = 'hidden';
  },
  close() {
    if (!this._el) return;
    this._el.classList.remove('open');
    document.body.style.overflow = '';
  },
  next() { if (this.images.length < 2) return; this.idx = (this.idx + 1) % this.images.length; this.zoomed = false; this._render(); },
  prev() { if (this.images.length < 2) return; this.idx = (this.idx - 1 + this.images.length) % this.images.length; this.zoomed = false; this._render(); },
  toggleZoom() { this.zoomed = !this.zoomed; this._render(); },

  _ensure() {
    if (this._el) return;
    const el = document.createElement('div');
    el.className = 'imgv-overlay';
    el.innerHTML = `
      <div class="imgv-toolbar">
        <span class="imgv-counter"></span>
        <span class="imgv-label"></span>
        <div class="imgv-actions">
          <a class="imgv-btn imgv-download" download title="دانلود">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
          </a>
          <button type="button" class="imgv-btn imgv-zoom-btn" title="زوم">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M11 8v6M8 11h6"/></svg>
          </button>
          <button type="button" class="imgv-btn imgv-close" title="بستن (Esc)">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      </div>
      <button type="button" class="imgv-nav imgv-prev" title="قبلی">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
      </button>
      <div class="imgv-stage"><img class="imgv-img" alt=""></div>
      <button type="button" class="imgv-nav imgv-next" title="بعدی">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
      </button>`;
    document.body.appendChild(el);
    this._el = el;

    el.querySelector('.imgv-close').addEventListener('click', () => this.close());
    el.querySelector('.imgv-prev').addEventListener('click', () => this.prev());
    el.querySelector('.imgv-next').addEventListener('click', () => this.next());
    el.querySelector('.imgv-zoom-btn').addEventListener('click', () => this.toggleZoom());
    el.querySelector('.imgv-img').addEventListener('click', () => this.toggleZoom());
    el.addEventListener('click', e => { if (e.target === el || e.target.classList.contains('imgv-stage')) this.close(); });
  },
  _render() {
    const cur = this.images[this.idx];
    const img = this._el.querySelector('.imgv-img');
    img.src = cur.src;
    img.classList.toggle('zoomed', this.zoomed);
    this._el.querySelector('.imgv-label').textContent = cur.label || '';
    this._el.querySelector('.imgv-counter').textContent = this.images.length > 1 ? (this.idx + 1) + ' / ' + this.images.length : '';
    this._el.querySelector('.imgv-download').href = cur.src;
    this._el.querySelector('.imgv-prev').style.display = this.images.length > 1 ? '' : 'none';
    this._el.querySelector('.imgv-next').style.display = this.images.length > 1 ? '' : 'none';
  },
};
document.addEventListener('keydown', e => {
  if (!imgViewer._el || !imgViewer._el.classList.contains('open')) return;
  if (e.key === 'Escape') imgViewer.close();
  else if (e.key === 'ArrowLeft') imgViewer.prev();
  else if (e.key === 'ArrowRight') imgViewer.next();
});

// Close on backdrop click
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal')) {
    e.target.classList.remove('open');
  }
});
// Close on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal.open').forEach(m => m.classList.remove('open'));
  }
});

/* ── Tabs ───────────────────────────────────────────── */
function initTabs(root) {
  (root || document).querySelectorAll('.tabs').forEach(tabs => {
    tabs.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        const pane = btn.dataset.pane;
        tabs.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b === btn));
        const scope = tabs.closest('.main') || document;
        scope.querySelectorAll('.tab-pane').forEach(p =>
          p.classList.toggle('active', p.id === 'pane-' + pane)
        );
      });
    });
  });
}
document.addEventListener('DOMContentLoaded', () => initTabs());

/* ── Table search ───────────────────────────────────── */
function filterTable(input, tableId) {
  const q = input.value.toLowerCase();
  document.querySelectorAll(`#${tableId} tbody tr`).forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}

/* ── Ripple on .btn ─────────────────────────────────── */
document.addEventListener('click', e => {
  const btn = e.target.closest('.btn');
  if (!btn || btn.disabled) return;
  const ripple = document.createElement('span');
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height) * 2;
  ripple.style.cssText = `
    position:absolute; border-radius:50%; pointer-events:none;
    width:${size}px; height:${size}px;
    left:${e.clientX - rect.left - size/2}px;
    top:${e.clientY - rect.top - size/2}px;
    background:rgba(255,255,255,.25);
    transform:scale(0); animation:ripple .5s ease-out forwards;
  `;
  if (getComputedStyle(btn).position === 'static') btn.style.position = 'relative';
  btn.appendChild(ripple);
  ripple.addEventListener('animationend', () => ripple.remove());
});

/* ── Notification badge ─────────────────────────────────────
   فقط شمارش سبک (COUNT، نه کل لیست) و فقط وقتی تب واقعاً باز/دیده‌شونده
   است poll می‌شود — با ده‌ها تب پنل باز در پس‌زمینه، سرور دیگر هر ۳۰ ثانیه
   برای تب‌های غیرفعال هم بار اضافه نمی‌بیند. */
async function _loadBadge() {
  try {
    const d = await fetch('/api/notifications/unread-count').then(r => r.json());
    document.querySelectorAll('#notifBadge').forEach(el => {
      el.textContent = d.unread_count;
      el.style.display = d.unread_count > 0 ? '' : 'none';
    });
  } catch {}
}
if (document.getElementById('notifBadge')) {
  let _badgeTimer = null;
  const _startBadgePolling = () => {
    if (_badgeTimer) return;
    _loadBadge();
    _badgeTimer = setInterval(_loadBadge, 30_000);
  };
  const _stopBadgePolling = () => {
    if (!_badgeTimer) return;
    clearInterval(_badgeTimer);
    _badgeTimer = null;
  };
  if (document.visibilityState === 'visible') _startBadgePolling();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') _startBadgePolling();
    else _stopBadgePolling();
  });
}

/* ── Button loading helper ──────────────────────────── */
function btnLoading(el, loading) {
  if (loading) {
    el.dataset.origText = el.innerHTML;
    el.classList.add('loading');
    el.disabled = true;
  } else {
    el.innerHTML = el.dataset.origText || el.innerHTML;
    el.classList.remove('loading');
    el.disabled = false;
  }
}

/* ── Confirm helper ─────────────────────────────────── */
function confirmAction(msg) {
  return new Promise(resolve => {
    // Simple native for now — can be upgraded to custom modal
    resolve(window.confirm(msg));
  });
}

/* ── Number formatter ───────────────────────────────── */
function fmtNum(n) {
  return Number(n || 0).toLocaleString('fa-IR');
}

/* ── PWA Install Prompt ─────────────────────────────── */
(function() {
  let _deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', function(e) {
    e.preventDefault();
    _deferredPrompt = e;
    if (localStorage.getItem('pwa-dismissed')) return;
    _showBanner();
  });
  function _showBanner() {
    let banner = document.getElementById('pwa-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'pwa-banner';
      banner.innerHTML =
        '<img src="/static/icons/icon-192.png" alt="">' +
        '<div class="pwa-text"><b>نصب اپلیکیشن</b><br>هیئت امنای مسکن را روی دستگاه خود نصب کنید</div>' +
        '<div class="pwa-btns">' +
          '<button class="pwa-install" id="pwaInstallBtn">نصب</button>' +
          '<button class="pwa-dismiss" id="pwaDismissBtn">بعداً</button>' +
        '</div>';
      document.body.appendChild(banner);
      document.getElementById('pwaInstallBtn').addEventListener('click', function() {
        if (!_deferredPrompt) return;
        _deferredPrompt.prompt();
        _deferredPrompt.userChoice.then(function(r) {
          _deferredPrompt = null;
          banner.classList.remove('show');
          if (r.outcome === 'accepted') localStorage.setItem('pwa-dismissed', '1');
        });
      });
      document.getElementById('pwaDismissBtn').addEventListener('click', function() {
        banner.classList.remove('show');
        localStorage.setItem('pwa-dismissed', '1');
      });
    }
    setTimeout(function() { banner.classList.add('show'); }, 2000);
  }
})();

/* ── Jalali today helper ────────────────────────────── */
function jalaliToday() {
  const d = new Date();
  const jy = d.getFullYear() - 621;
  const jm = String(d.getMonth() + 1).padStart(2, '0');
  const jd = String(d.getDate()).padStart(2, '0');
  return `${jy}/${jm}/${jd}`;
}

/* ── Persian ↔ English digits ───────────────────────────
   تبدیل خودکار اعداد فارسی به انگلیسی در همه فیلدهای عددی */
function toEnDigits(str) {
  return String(str).replace(/[۰-۹]/g, function(d) {
    return String.fromCharCode(d.charCodeAt(0) - 1728);
  }).replace(/[٠-٩]/g, function(d) {
    return String.fromCharCode(d.charCodeAt(0) - 1584);
  });
}
document.addEventListener('input', function(e) {
  var el = e.target;
  if (!el || !el.tagName) return;
  var type = (el.type || '').toLowerCase();
  var isNum = type === 'number' || type === 'tel' || el.inputMode === 'numeric' ||
    el.dataset && (el.dataset.amount !== undefined || el.dataset.numeric !== undefined) ||
    el.classList.contains('mono') ||
    (el.id && /nat|code|phone|amount|serial|booklet|contract|share|price|count|num|mobile/i.test(el.id));
  if (!isNum) return;
  var pos = el.selectionStart;
  var converted = toEnDigits(el.value);
  if (converted !== el.value) {
    el.value = converted;
    try { el.setSelectionRange(pos, pos); } catch(e2) {}
  }
}, true);

/* ── Image compression before upload ────────────────────
   فشرده‌سازی تصاویر قبل از آپلود (برای فایل‌های بزرگ) */
window.compressImage = function(file, maxW, maxH, quality, callback) {
  if (!file.type.startsWith('image/')) { callback(file); return; }
  var reader = new FileReader();
  reader.onload = function(e) {
    var img = new Image();
    img.onload = function() {
      var w = img.width, h = img.height;
      if (w <= maxW && h <= maxH && file.size < 500*1024) { callback(file); return; }
      var scale = Math.min(maxW/w, maxH/h, 1);
      var cw = Math.round(w*scale), ch = Math.round(h*scale);
      var canvas = document.createElement('canvas');
      canvas.width = cw; canvas.height = ch;
      canvas.getContext('2d').drawImage(img, 0, 0, cw, ch);
      canvas.toBlob(function(blob) {
        callback(new File([blob], file.name, {type:'image/jpeg', lastModified:Date.now()}));
      }, 'image/jpeg', quality || 0.82);
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
};
