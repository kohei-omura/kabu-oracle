
/* 株オラクル app.js — 遅延読込検索 / ウォッチリスト / ライブ価格 / 市場時間ポーリング
   すべて素のJS(ES2018)・iOS Safari動作。生成日時でキャッシュ更新。 */
(function () {
  'use strict';

  var TOTAL = parseInt((document.body && document.body.getAttribute('data-total')) || '0', 10) || 0;
  var WATCH_KEY = 'kabu_watch';
  var STOCKS = null;      // stocks.json（遅延読込）
  var loading = false;
  var loadTries = 0;

  var q = document.getElementById('q');
  var results = document.getElementById('results');
  var hint = document.getElementById('hint');
  var searchSec = document.getElementById('search-sec');

  /* ---- 正規化：NFKC → 小文字 → ひらがな→カタカナ ---- */
  function norm(s) {
    s = (s == null ? '' : String(s));
    try { s = s.normalize('NFKC'); } catch (e) {}
    s = s.toLowerCase();
    var out = '';
    for (var i = 0; i < s.length; i++) {
      var ch = s.charCodeAt(i);
      if (ch >= 0x3041 && ch <= 0x3096) out += String.fromCharCode(ch + 0x60); // かな→カナ
      else out += s.charAt(i);
    }
    return out;
  }

  /* ---- ウォッチリスト（localStorage） ---- */
  function getWatch() {
    try { return JSON.parse(localStorage.getItem(WATCH_KEY) || '[]') || []; }
    catch (e) { return []; }
  }
  function setWatch(arr) {
    try { localStorage.setItem(WATCH_KEY, JSON.stringify(arr)); } catch (e) { console.warn('watch save失敗', e); }
  }
  function inWatch(c) { return getWatch().indexOf(c) >= 0; }
  function toggleWatch(c) {
    var w = getWatch(); var i = w.indexOf(c);
    if (i >= 0) w.splice(i, 1); else w.push(c);
    setWatch(w);
  }

  /* ---- カード描画（検索結果・ウォッチ用） ---- */
  function badge(g) {
    var m = { BUY: ['買', 'buy'], SELL: ['売', 'sell'], HOLD: ['待', 'hold'] };
    var x = m[g] || m.HOLD;
    return '<span class="badge ' + x[1] + '">' + x[0] + '</span>';
  }
  function segTag(mk) {
    var x = { prime: ['P', 'p'], standard: ['S', 's'], growth: ['G', 'g'] }[mk];
    return x ? '<span class="seg ' + x[1] + '">' + x[0] + '</span>' : '';
  }
  function bar(sc) {
    var p = Math.max(-100, Math.min(100, sc)) / 100;
    if (p >= 0) return '<span class="bar"><span class="bar-pos" style="width:' + (p * 50) + '%"></span></span>';
    return '<span class="bar"><span class="bar-neg" style="width:' + (Math.abs(p) * 50) + '%;margin-left:' + (50 - Math.abs(p) * 50) + '%"></span></span>';
  }
  function starBtn(c) {
    var on = inWatch(c);
    return '<button class="star' + (on ? ' on' : '') + '" data-star="' + c + '" aria-label="ウォッチ">' + (on ? '★' : '☆') + '</button>';
  }
  function card(s, mode) {
    var scls = s.sc >= 0 ? 'pos' : 'neg';
    var levels = '';
    if (s.t && s.st) {
      levels = '<div class="levels"><span class="lv tgt">利確 ¥' + s.t.toLocaleString() +
        '</span><span class="lv stp">損切 ¥' + s.st.toLocaleString() + '</span>' +
        (s.rr ? '<span class="lv rr">RR ' + s.rr + '</span>' : '') + '</div>';
    }
    var reasons = '';
    if (s.r && s.r.length) {
      reasons = '<div class="reasons">' + s.r.map(function (r) { return '<span class="chip">' + r + '</span>'; }).join('') + '</div>';
    }
    var rm = (mode === 'watch') ? '<button class="rm" data-rm="' + s.c + '">×</button>' : '';
    return '<div class="card">' +
      '<div class="row1"><span class="rank">' + s.rk + '</span>' +
      '<div class="title"><span class="code">' + s.c + '</span><span class="name">' + s.n + '</span>' + segTag(s.m) + '</div>' +
      badge(s.g) + starBtn(s.c) + rm + '</div>' +
      '<div class="row2"><span class="price" data-px="' + s.c + '">¥' + s.p.toLocaleString() + '</span>' +
      '<span class="score ' + scls + '">' + (s.sc >= 0 ? '+' : '') + s.sc + '</span>' + bar(s.sc) + '</div>' +
      levels + reasons +
      '<div class="rankline">スコア順 総合 ' + s.rk + ' 位 / ' + TOTAL + ' 銘柄中</div>' +
      '</div>';
  }
  function byCode(code) {
    if (!STOCKS) return null;
    var v = String(code).toLowerCase();
    for (var i = 0; i < STOCKS.length; i++) { if (STOCKS[i].c.toLowerCase() === v) return STOCKS[i]; }
    return null;
  }

  /* ---- stocks.json 遅延読込（初回のみ・失敗時3秒×最大3回） ---- */
  function ensureStocks(cb) {
    if (STOCKS) { if (cb) cb(); return; }
    if (loading) return;
    loading = true;
    if (results && !(q && q.value.trim())) { /* 読込中表示は run() 側で */ }
    (function attempt() {
      fetch('stocks.json?t=' + Date.now())
        .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
        .then(function (j) {
          STOCKS = j; loading = false; loadTries = 0;
          if (cb) cb();
          renderWatch();
          if (q && q.value.trim()) run();
        })
        .catch(function (e) {
          loadTries++;
          console.warn('[kabu] stocks.json 読込失敗 (' + loadTries + ')', e);
          if (loadTries < 3) { setTimeout(attempt, 3000); }
          else {
            loading = false;
            if (results && q && q.value.trim()) {
              results.innerHTML = '<p class="empty">銘柄データの読込に失敗しました。通信環境を確認して、もう一度お試しください。</p>';
            }
          }
        });
    })();
  }

  /* ---- 検索（150ms debounce・正規化・最大8件・件数表示） ---- */
  function ensureHitEl() {
    var el = document.getElementById('hitcount');
    if (!el && results && results.parentNode) {
      el = document.createElement('p');
      el.id = 'hitcount';
      results.parentNode.insertBefore(el, results);
    }
    return el;
  }
  function run() {
    if (!q || !results) return;
    var raw = q.value.trim();
    var hitEl = ensureHitEl();
    if (!raw) {
      results.innerHTML = '';
      if (hint) hint.style.display = '';
      if (hitEl) hitEl.textContent = '';
      return;
    }
    if (hint) hint.style.display = 'none';
    if (!STOCKS) {
      if (hitEl) hitEl.textContent = '';
      results.innerHTML = '<p class="empty">銘柄データを読込中…</p>';
      ensureStocks();
      return;
    }
    var v = norm(raw);
    var code = raw.toLowerCase();
    var m = STOCKS.filter(function (s) {
      return (s.k && s.k.indexOf(v) >= 0) || s.c.toLowerCase().indexOf(code) === 0;
    }).sort(function (a, b) { return b.sc - a.sc; });
    var shown = m.slice(0, 8);
    if (hitEl) hitEl.textContent = m.length ? (m.length + '件ヒット / 上位' + shown.length + '件表示') : '';
    results.innerHTML = shown.length
      ? shown.map(function (s) { return card(s, 'search'); }).join('')
      : '<p class="empty">該当する銘柄が見つかりません。コードや銘柄名を確認してください。</p>';
  }
  var deb = null;
  function runDebounced() { if (deb) clearTimeout(deb); deb = setTimeout(run, 150); }

  if (q) {
    q.addEventListener('focus', function () { ensureStocks(); });
    q.addEventListener('input', function () { ensureStocks(); runDebounced(); });
  }

  /* ---- ウォッチリストのセクション生成・描画 ---- */
  var watchSec = null, watchResults = null;
  function ensureWatchSec() {
    if (watchSec) return;
    watchSec = document.createElement('section');
    watchSec.id = 'watch-sec';
    watchSec.style.display = 'none';
    watchSec.innerHTML =
      '<h2 class="find"><span>ウォッチリスト</span><em>WATCHLIST</em></h2>' +
      '<div id="watch-results" class="cards"></div>';
    if (searchSec && searchSec.parentNode) {
      searchSec.parentNode.insertBefore(watchSec, searchSec.nextSibling);
    }
    watchResults = watchSec.querySelector('#watch-results');
  }
  function renderWatch() {
    ensureWatchSec();
    var w = getWatch();
    if (!w.length) { watchSec.style.display = 'none'; if (watchResults) watchResults.innerHTML = ''; return; }
    if (!STOCKS) { ensureStocks(); return; }   // 読込後に再度呼ばれる
    var cards = [];
    for (var i = 0; i < w.length; i++) {
      var s = byCode(w[i]);
      if (s) cards.push(card(s, 'watch'));
    }
    watchSec.style.display = cards.length ? '' : 'none';
    if (watchResults) watchResults.innerHTML = cards.join('');
  }

  /* サーバー生成カード（買い候補・保有）にも☆を後付け */
  function injectStars() {
    var cards = document.querySelectorAll('.card');
    for (var i = 0; i < cards.length; i++) {
      var cd = cards[i];
      if (cd.querySelector('[data-star]')) continue;      // 既に有り
      var px = cd.querySelector('[data-px]'); if (!px) continue;
      var c = px.getAttribute('data-px');
      var r1 = cd.querySelector('.row1'); if (!r1) continue;
      var b = document.createElement('button');
      b.className = 'star' + (inWatch(c) ? ' on' : '');
      b.setAttribute('data-star', c);
      b.textContent = inWatch(c) ? '★' : '☆';
      r1.appendChild(b);
    }
  }
  function syncStars() {
    var btns = document.querySelectorAll('[data-star]');
    for (var i = 0; i < btns.length; i++) {
      var c = btns[i].getAttribute('data-star');
      var on = inWatch(c);
      btns[i].className = 'star' + (on ? ' on' : '');
      btns[i].textContent = on ? '★' : '☆';
    }
  }

  /* クリック委譲：☆トグル / ×解除 */
  document.addEventListener('click', function (ev) {
    var t = ev.target;
    if (!t || !t.getAttribute) return;
    var sc = t.getAttribute('data-star');
    if (sc) { toggleWatch(sc); syncStars(); renderWatch(); return; }
    var rm = t.getAttribute('data-rm');
    if (rm) { toggleWatch(rm); syncStars(); renderWatch(); return; }
  });

  /* ---- ライブ価格（data-px の更新＋狙い目行の再計算） ---- */
  function applyPrices(map) {
    document.querySelectorAll('[data-px]').forEach(function (el) {
      var c = el.getAttribute('data-px');
      if (map[c] != null) el.textContent = '¥' + Number(map[c]).toLocaleString();
    });
    // 🎯狙い目行：現値と乖離%を新価格で再計算
    document.querySelectorAll('.ez[data-ez-c]').forEach(function (el) {
      var c = el.getAttribute('data-ez-c');
      var limit = parseFloat(el.getAttribute('data-ez-limit'));
      if (map[c] == null || !limit) return;
      var pr = Math.round(Number(map[c]));
      if (pr <= limit) {
        el.className = 'ez hit';
        el.innerHTML = '🎯 狙い目 指値 ¥' + limit.toLocaleString() +
          ' <b>✅ 指値到達</b>（現値 ¥' + pr.toLocaleString() + '）';
      } else {
        var pct = Math.round((pr - limit) / pr * 100);
        el.className = 'ez';
        el.innerHTML = '🎯 狙い目 指値 ¥' + limit.toLocaleString() +
          ' 〜 現値 ¥' + pr.toLocaleString() +
          '<span class="ezn">-' + pct + '% の押し目</span>';
      }
    });
    // メモリ上の STOCKS 価格も更新（検索結果に反映）
    if (STOCKS) {
      for (var i = 0; i < STOCKS.length; i++) {
        if (map[STOCKS[i].c] != null) STOCKS[i].p = Math.round(Number(map[STOCKS[i].c]));
      }
    }
  }
  function refreshPrices() {
    return fetch('prices.json?t=' + Date.now())
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.px) return;
        applyPrices(d.px);
        var lab = document.getElementById('pxasof');
        if (lab && d.asof) lab.textContent = '株価 ' + d.asof + ' 時点（約20分遅延）';
        if (q && q.value.trim()) run();
        renderWatch();
      })
      .catch(function (e) { console.warn('[kabu] prices取得失敗', e); });
  }

  /* ---- 市場時間ポーリング：JST平日 8:55〜16:10 のみ5分毎 ---- */
  function nowJST() {
    return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
  }
  function isOpen(d) {
    var wd = d.getDay();
    var mins = d.getHours() * 60 + d.getMinutes();
    return (wd >= 1 && wd <= 5) && (mins >= 535 && mins <= 970); // 8:55〜16:10
  }
  function msToNextOpen(d) {
    var t = new Date(d.getTime());
    var mins = d.getHours() * 60 + d.getMinutes();
    var biz = (d.getDay() >= 1 && d.getDay() <= 5);
    if (biz && mins < 535) {
      t.setHours(8, 55, 0, 0);
    } else {
      t.setHours(8, 55, 0, 0);
      do { t.setDate(t.getDate() + 1); } while (!(t.getDay() >= 1 && t.getDay() <= 5));
    }
    return Math.max(1000, t.getTime() - d.getTime());
  }
  function tick() {
    var d = nowJST();
    if (isOpen(d)) {
      refreshPrices();
      console.log('[kabu] 価格ポーリング（開場中）', d.toLocaleTimeString('ja-JP'));
      setTimeout(tick, 5 * 60 * 1000);
    } else {
      var ms = Math.min(msToNextOpen(d), 6 * 3600 * 1000); // 最大6h毎に再判定
      console.log('[kabu] 閉場中：次回開場まで約' + Math.round(ms / 60000) + '分');
      setTimeout(tick, ms);
    }
  }

  /* ---- ヘッダーに手動更新ボタン（⟳） ---- */
  function addRefreshBtn() {
    var meta = document.querySelector('header .meta');
    if (!meta || document.getElementById('pxrefresh')) return;
    var b = document.createElement('button');
    b.id = 'pxrefresh'; b.className = 'refresh'; b.type = 'button';
    b.textContent = '⟳ 更新';
    b.addEventListener('click', function () {
      b.disabled = true;
      refreshPrices().then(function () { setTimeout(function () { b.disabled = false; }, 1500); });
    });
    meta.appendChild(b);
  }

  /* ---- 初期化 ---- */
  function init() {
    addRefreshBtn();
    injectStars();
    // ウォッチが1件以上あれば stocks.json を自動読込してウォッチ描画
    if (getWatch().length) { ensureStocks(renderWatch); } else { ensureWatchSec(); }
    // 初回の価格反映＋ポーリング開始
    refreshPrices();
    tick();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
