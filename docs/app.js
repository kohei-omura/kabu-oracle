
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
    watchSec = document.createElement('details');
    watchSec.id = 'watch-sec';
    watchSec.className = 'sec find';
    watchSec.open = true;
    watchSec.style.display = 'none';
    watchSec.innerHTML =
      '<summary class="sh"><span class="st">ウォッチリスト</span><span class="cnt" id="watch-cnt"></span>' +
      '<em>WATCHLIST</em><span class="chev" aria-hidden="true"></span></summary>' +
      '<div class="sbody"><div id="watch-results" class="cards"></div></div>';
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
    var wc = document.getElementById('watch-cnt');
    if (wc) wc.textContent = cards.length;
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
    var lt = t.getAttribute('data-lt');
    if (lt) { onLongClick(t, lt); return; }
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
      var prob = el.getAttribute('data-ez-prob');
      var pn = prob ? ' ・ 約定目安 ' + prob + '%' : '';
      if (pr <= limit) {
        el.className = 'ez hit';
        el.innerHTML = '🎯 指値 ¥' + limit.toLocaleString() +
          ' <b>✅ 指値到達</b>（現値 ¥' + pr.toLocaleString() + '）';
      } else {
        var pct = ((pr - limit) / pr * 100).toFixed(1);
        el.className = 'ez';
        el.innerHTML = '🎯 指値 ¥' + limit.toLocaleString() +
          '<span class="ezn">現値 ¥' + pr.toLocaleString() + '比 -' + pct + '%' + pn + '</span>';
      }
    });
    // 保有銘柄カード：最新株価で損益%と状態（利確圏/損切圏/保有中）を計算し直す
    document.querySelectorAll('[data-hold]').forEach(function (cd) {
      var c = cd.getAttribute('data-hold');
      if (map[c] == null) return;
      var cur = Number(map[c]);
      var buy = parseFloat(cd.getAttribute('data-hold-buy'));
      var tgt = parseFloat(cd.getAttribute('data-hold-tgt'));
      var stp = parseFloat(cd.getAttribute('data-hold-stp'));
      var pl = cd.querySelector('[data-hold-pl]');
      if (pl && buy > 0) {
        var v = (cur - buy) / buy * 100;
        pl.textContent = (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
        pl.className = 'score ' + (v >= 0 ? 'pos' : 'neg');
      }
      var st = cd.querySelector('[data-hold-st]');
      if (st) {
        var lab = '保有中', cls = 'hold';
        if (tgt && cur >= tgt) { lab = '利確圏'; cls = 'buy'; }
        else if (stp && cur <= stp) { lab = '損切圏'; cls = 'sell'; }
        st.textContent = lab;
        st.className = 'hstat ' + cls;
      }
      // 長期見通しも最新株価を起点に引き直す
      var box = cd.querySelector('[data-ltbox]');
      var g = box ? parseFloat(box.getAttribute('data-lt-g')) : NaN;
      if (box && !isNaN(g)) {
        var rate = 1 + g / 100;
        box.querySelectorAll('[data-lt-n]').forEach(function (chip) {
          var n = parseFloat(chip.getAttribute('data-lt-n'));
          var b = chip.querySelector('b');
          if (b && !isNaN(n)) b.textContent = '¥' + Math.round(cur * Math.pow(rate, n)).toLocaleString();
        });
        var ys = box.querySelector('[data-lt-years]');
        var goal = parseFloat(box.getAttribute('data-lt-target'));
        if (ys && goal > 0) {
          if (goal <= cur) ys.textContent = ' ・ すでに到達';
          else if (rate > 1) ys.textContent = ' ・ 到達目安 約' +
            (Math.log(goal / cur) / Math.log(rate)).toFixed(1) + '年';
          else ys.textContent = '';
        }
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
        applyLong(d.long);
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

  /* ---- 長期保有トグル：holdings.txt を GitHub API で書き換える ----
     ONにすると holdings.txt の行に「長期」が付き、GitHub Actions 側の
     利確通知が止まる（損切・売りシグナルは従来どおり通知）。
     トークンはこの端末の localStorage にのみ保存し、送信先は api.github.com のみ。 */
  var GH_KEY = 'kabu_gh';
  var LONG_TOKENS = ['長期', '長期保有', 'long', 'longterm', 'hold'];

  function ghLoad() { try { return JSON.parse(localStorage.getItem(GH_KEY) || 'null'); } catch (e) { return null; } }
  function ghStore(v) { try { localStorage.setItem(GH_KEY, JSON.stringify(v)); return true; } catch (e) { return false; } }
  function ghDrop() { try { localStorage.removeItem(GH_KEY); } catch (e) {} }
  function ghGuess() {
    var owner = '', repo = '';
    var m = String(location.hostname || '').match(/^([^.]+)\.github\.io$/i);
    if (m) owner = m[1];
    var seg = String(location.pathname || '/').split('/').filter(function (x) { return x && x.indexOf('.') < 0; });
    if (seg.length) repo = seg[0];
    return { owner: owner, repo: repo, branch: 'main', path: 'holdings.txt' };
  }
  function b64enc(str) {
    var bytes = new TextEncoder().encode(str), bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }
  function b64dec(b64) {
    var bin = atob(String(b64).replace(/\s/g, ''));
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder('utf-8').decode(bytes);
  }
  function isLongTok(x) { return LONG_TOKENS.indexOf(String(x).trim().toLowerCase()) >= 0; }

  /* holdings.txt の該当行に「長期」を付け外しする。行が無ければ null（config.py と同じ解釈） */
  function rewriteLong(text, code, on) {
    var lines = String(text).split('\n'), found = false;
    for (var i = 0; i < lines.length; i++) {
      var t = lines[i].trim();
      if (!t || t.charAt(0) === '#') continue;
      var parts = t.replace(/，/g, ',').split(',').map(function (x) { return x.trim(); });
      var kept = parts.filter(function (x) { return !isLongTok(x); });
      if (!kept.length || kept[0] !== String(code)) continue;
      found = true;
      while (kept.length > 1 && kept[kept.length - 1] === '') kept.pop();
      if (on) kept.push('長期');
      lines[i] = kept.join(',');
    }
    return found ? lines.join('\n') : null;
  }

  function ghContentsUrl(cfg) {
    return 'https://api.github.com/repos/' + encodeURIComponent(cfg.owner) + '/' +
      encodeURIComponent(cfg.repo) + '/contents/' + (cfg.path || 'holdings.txt');
  }
  function ghApi(cfg, method, url, body) {
    var opt = { method: method, cache: 'no-store', headers: {
      'Authorization': 'Bearer ' + cfg.token,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    } };
    if (body) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
    return fetch(url, opt).then(function (r) {
      return r.text().then(function (txt) {
        var j = null;
        try { j = txt ? JSON.parse(txt) : null; } catch (e) {}
        if (!r.ok) {
          var msg = (j && j.message) || ('HTTP ' + r.status);
          if (r.status === 401) msg = 'トークンが無効です(401)';
          else if (r.status === 403) msg = '権限不足(403) Contents: Read and write を確認';
          else if (r.status === 404) msg = '見つかりません(404) owner/repo/branch を確認';
          else if (r.status === 409) msg = '競合(409) 少し待って再実行してください';
          var err = new Error(msg); err.status = r.status; throw err;
        }
        return j;
      });
    });
  }
  function setLongRemote(cfg, code, on) {
    var url = ghContentsUrl(cfg);
    return ghApi(cfg, 'GET', url + '?ref=' + encodeURIComponent(cfg.branch || 'main') + '&t=' + Date.now())
      .then(function (j) {
        var text = b64dec((j && j.content) || '');
        var next = rewriteLong(text, code, on);
        if (next === null) throw new Error('holdings.txt に ' + code + ' の行がありません');
        if (next === text) return null;   // すでにその状態
        return ghApi(cfg, 'PUT', url, {
          message: (on ? '長期保有ON ' : '長期保有OFF ') + code + ' [skip ci]',
          content: b64enc(next), sha: j.sha, branch: (cfg.branch || 'main')
        });
      });
  }

  /* 自分の操作を prices.json（最大20分遅れ）が追いつくまで優先させる保存領域 */
  var LT_OV_KEY = 'kabu_long_ov';
  function ltOvGet() { try { return JSON.parse(localStorage.getItem(LT_OV_KEY) || '{}') || {}; } catch (e) { return {}; } }
  function ltOvSet(v) { try { localStorage.setItem(LT_OV_KEY, JSON.stringify(v)); } catch (e) {} }
  function ltOvPut(code, on) { var o = ltOvGet(); o[code] = on ? 1 : 0; ltOvSet(o); }

  /* prices.json の long 配列でカードの状態をそろえる（サーバー優先・未反映分だけ上書き） */
  function applyLong(list) {
    if (!list) return;
    var srv = {}, i;
    for (i = 0; i < list.length; i++) srv[list[i]] = 1;
    var ov = ltOvGet(), changed = false;
    Object.keys(ov).forEach(function (c) {
      if (!!srv[c] === !!ov[c]) { delete ov[c]; changed = true; }   // サーバーが追いついた
      else srv[c] = ov[c];
    });
    if (changed) ltOvSet(ov);
    document.querySelectorAll('[data-hold]').forEach(function (cd) {
      setCardLong(cd, !!srv[cd.getAttribute('data-hold')]);
    });
  }

  function setCardLong(card, on) {
    if (!card) return;
    card.setAttribute('data-hold-long', on ? '1' : '0');
    var b = card.querySelector('[data-lt]');
    if (b) {
      b.className = 'ltbtn' + (on ? ' on' : '');
      b.textContent = on ? '🌱 長期保有中' : '☾ 長期保有';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    var box = card.querySelector('[data-ltbox]');
    if (box) box.hidden = !on;
  }
  function ltMsg(card, text, isErr) {
    var m = card && card.querySelector('[data-ltmsg]');
    if (!m) return;
    m.className = 'ltmsg' + (isErr ? ' err' : '');
    m.textContent = text || '';
  }
  function onLongClick(btn, code) {
    var card = btn.closest ? btn.closest('.card') : null;
    var cfg = ghLoad();
    if (!cfg || !cfg.token) {
      ltMsg(card, 'GitHubトークンの登録が必要です', true);
      openGh('「長期保有」を使うにはトークンの登録が必要です（この端末にのみ保存されます）。');
      return;
    }
    var on = !(card && card.getAttribute('data-hold-long') === '1');
    btn.disabled = true;
    ltMsg(card, on ? '長期保有ONに更新中…' : '長期保有OFFに更新中…');
    setLongRemote(cfg, code, on).then(function () {
      ltOvPut(code, on);
      setCardLong(card, on);
      ltMsg(card, on ? '利確通知OFF（holdings.txt 更新済み）' : 'holdings.txt 更新済み');
    }).catch(function (e) {
      ltMsg(card, '失敗: ' + ((e && e.message) || e), true);
    }).then(function () { btn.disabled = false; });
  }

  /* ---- GitHub 設定パネル（⚙） ---- */
  function gv(id) { var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }
  function sv(id, v) { var el = document.getElementById(id); if (el) el.value = v == null ? '' : v; }
  function ghStat(text, cls) {
    var el = document.getElementById('ghstat');
    if (el) { el.className = 'ghstat' + (cls ? ' ' + cls : ''); el.textContent = text || ''; }
  }
  function openGh(note) {
    var panel = document.getElementById('ghpanel');
    if (!panel) return;
    panel.hidden = false;
    var cfg = ghLoad() || {}, g = ghGuess();
    sv('ghtoken', '');
    sv('ghowner', cfg.owner || g.owner);
    sv('ghrepo', cfg.repo || g.repo);
    sv('ghbranch', cfg.branch || g.branch);
    ghStat(note || (cfg.token ? 'トークン登録済み（変更するときだけ入力）' : ''), cfg.token ? 'ok' : '');
    try { panel.scrollIntoView({ block: 'nearest' }); } catch (e) {}
  }
  function wireGh() {
    var gear = document.getElementById('ghgear');
    if (gear) gear.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();          // 見出し（▼）の開閉はさせない
      var sec = document.getElementById('hold-sec');
      if (sec) sec.open = true;
      var p = document.getElementById('ghpanel');
      if (p && !p.hidden) { p.hidden = true; return; }
      openGh();
    });
    var save = document.getElementById('ghsave');
    if (save) save.addEventListener('click', function () {
      var cur = ghLoad() || {};
      var cfg = { token: gv('ghtoken') || cur.token || '', owner: gv('ghowner'),
                  repo: gv('ghrepo'), branch: gv('ghbranch') || 'main', path: 'holdings.txt' };
      if (!cfg.token) { ghStat('トークンを入力してください', 'err'); return; }
      if (!cfg.owner || !cfg.repo) { ghStat('owner と repo を入力してください', 'err'); return; }
      ghStat('確認中…');
      ghApi(cfg, 'GET', ghContentsUrl(cfg) + '?ref=' + encodeURIComponent(cfg.branch))
        .then(function () {
          if (!ghStore(cfg)) { ghStat('保存できませんでした（プライベートブラウズ？）', 'err'); return; }
          sv('ghtoken', '');
          ghStat('保存しました。カードの「長期保有」を押せます', 'ok');
        })
        .catch(function (e) { ghStat('失敗: ' + ((e && e.message) || e), 'err'); });
    });
    var del = document.getElementById('ghdel');
    if (del) del.addEventListener('click', function () {
      ghDrop(); sv('ghtoken', ''); ghStat('この端末から削除しました');
    });
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
    wireGh();
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

  /* ---- ジャンプメニュー・すべて閉じる/開く（セクションは <details> で▼開閉） ---- */
  (function wireJump() {
    var nav = document.getElementById('jump');
    if (!nav) return;
    var links = nav.querySelectorAll('a[href^="#"]');
    for (var i = 0; i < links.length; i++) {
      (function (a) {
        var t = document.getElementById(a.getAttribute('href').slice(1));
        if (!t) { a.style.display = 'none'; return; }
        a.addEventListener('click', function (e) {
          e.preventDefault();
          t.open = true;
          try { t.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (x) { t.scrollIntoView(); }
        });
      })(links[i]);
    }
    var btn = document.getElementById('foldall');
    function secs() { return document.querySelectorAll('details.sec'); }
    function sync() {
      var any = false, ss = secs();
      for (var i = 0; i < ss.length; i++) if (ss[i].open && ss[i].style.display !== 'none') any = true;
      if (btn) btn.textContent = any ? '全て閉じる' : '全て開く';
    }
    if (btn) btn.addEventListener('click', function () {
      var ss = secs(), any = false;
      for (var i = 0; i < ss.length; i++) if (ss[i].open && ss[i].style.display !== 'none') any = true;
      for (var j = 0; j < ss.length; j++) ss[j].open = !any;
      sync();
    });
    document.addEventListener('toggle', sync, true);
    sync();
  })();
})();

/* ── 日米連動（株オラクル ⇄ GLOBE ORACLE） ──
   両アプリは同じ GitHub Pages（kohei-omura.github.io）に公開しているので、相手の公開JSONを読むだけで連携する。
   端末の保存領域・トークン・既存の処理には一切触らない（読み取り専用）。
   判定は「米国株(①指数)×為替(②ドル円)」のクイックチェックに、③米金利・④日本固有の地合いを添える。 */
(function () {
  'use strict';
  var SELF = 'kabu';
  var box = document.getElementById('xlink');
  if (!box || !window.fetch) return;
  var ROOT = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? location.origin : 'https://kohei-omura.github.io';
  var K = ROOT + '/kabu-oracle/', G = ROOT + '/GLOBE-ORACLE/';

  function get(u) {
    return fetch(u + '?t=' + Date.now()).then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function esc(x) {
    return String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function num(v) { if (v === null || v === undefined || v === '') return null; v = Number(v); return isFinite(v) ? v : null; }
  function sg(v, d) { return (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(d == null ? 1 : d); }
  function pc(v, d) { return v == null ? '—' : sg(v, d) + '%'; }
  function ud(v) { return v == null ? '' : v > 0 ? ' xl-up' : v < 0 ? ' xl-dn' : ''; }
  function chgOf(idx, k) { var d = idx && idx[k]; return d ? num(d.chg) : null; }
  function pxOf(idx, k) { var d = idx && idx[k]; return d ? num(d.price) : null; }

  /* 米国株の総合値（%）：S&P500 と NASDAQ を重く、ダウを軽く。取れた指数だけで平均する */
  function usMove(idx) {
    var w = { SP500: 0.4, NASDAQ: 0.4, DOW: 0.2 }, s = 0, t = 0;
    for (var k in w) { var c = chgOf(idx, k); if (c != null) { s += c * w[k]; t += w[k]; } }
    return t ? s / t : null;
  }
  var US_TH = 0.3, FX_TH = 0.2, FX_SHARP = 0.8, SOX_TH = 1.5;

  /* クイックチェック（むらちゃんの判断軸まとめ「3. 投資判断のクイックチェック」をそのまま実装） */
  function judge(idx, rg) {
    var us = usMove(idx), fx = chgOf(idx, 'USDJPY');
    if (us == null) return null;
    var u = us >= US_TH ? 1 : us <= -US_TH ? -1 : 0;
    var f = fx == null ? 0 : fx >= FX_TH ? 1 : fx <= -FX_TH ? -1 : 0;   /* +1 = 円安, −1 = 円高 */
    var sharp = fx != null && fx <= -FX_SHARP;
    var r;
    if (u > 0 && f > 0) r = [2, '強気', '☀', '米国株高＋円安：日本株にとって最強の上昇要因。特に輸出・ハイテク株に追い風'];
    else if (u > 0 && f < 0) r = sharp
      ? [0, '上がりにくい', '🌤', '米国株高でも急な円高：輸出企業の業績悪化が意識され、日本株は上がりにくい（連動が弱まる）']
      : [0, '方向感に迷う', '🌤', '米国株高＋円高：方向感に迷いやすい。輸出株より内需株が相対的に優位'];
    else if (u > 0) r = [1, 'やや強気', '🌤', '米国株高：翌朝の日本株は買い先行（ギャップアップ）で始まりやすい'];
    else if (u < 0 && f < 0) r = [-2, '弱気・リスクオフ', '☔', '米国株安＋円高：リスクオフ。全面安に警戒（新規買いは慎重に）'];
    else if (u < 0 && f > 0) r = [-1, '下落は限定的', '☁', '米国株安＋円安：円安が下支えとなり、日本株の下落は限定的になりやすい'];
    else if (u < 0) r = [-1, 'やや弱気', '☁', '米国株安：翌朝の日本株は売り先行で始まりやすい'];
    else if (f > 0) r = [1, '小動き・円安', '⛅', '米国は小動き。円安が輸出株の支えになりやすい'];
    else if (f < 0) r = [-1, '小動き・円高', '⛅', '米国は小動き。円高が輸出株の重荷になりやすい'];
    else r = [0, '中立', '⛅', '米国・為替とも小動き。日本固有の材料（決算・自社株買い等）で動きやすい'];
    var o = { lv: r[0], label: r[1], icon: r[2], desc: r[3], us: us, fx: fx, u: u, f: f, notes: [] };

    /* ① 半導体（SOX）は日本の関連銘柄に直結 */
    var sox = chgOf(idx, 'SOX');
    if (sox != null && sox >= SOX_TH) o.notes.push('半導体指数SOXが' + pc(sox) + '：日本の半導体関連（東京エレクトロン・アドバンテスト等）に追い風');
    else if (sox != null && sox <= -SOX_TH) o.notes.push('半導体指数SOXが' + pc(sox) + '：日本の半導体関連に逆風');
    /* ③ 金利差：米金利の上げ下げは日米金利差→ドル円を通じて効く */
    var tn = pxOf(idx, 'US10Y'), tc = chgOf(idx, 'US10Y');
    if (tn != null && tc != null) {
      var bp = tn - tn / (1 + tc / 100);              /* 前日比（%ポイント） */
      if (bp >= 0.05) o.notes.push('米10年金利が上昇（' + tn.toFixed(2) + '%）：日米金利差の拡大は円安・日本株高の方向');
      else if (bp <= -0.05) o.notes.push('米10年金利が低下（' + tn.toFixed(2) + '%）：金利差の縮小は円高・日本株の重荷の方向');
    }
    /* ④ 日本固有の地合い（デカップリング） */
    if (rg && rg.label) {
      if (u < 0 && rg.label === '上昇基調') o.notes.push('日経は上昇基調：米国安でも日本独自の強さ（業績・株主還元）で底堅い可能性');
      else if (u > 0 && rg.label === '下落基調') o.notes.push('日経は下落基調：米国高でも戻り売りが出やすい。推奨株数は半分のまま');
      else if (rg.label === '下落基調') o.notes.push('日経は下落基調：株オラクルの推奨株数は地合いに合わせて半分');
    }
    return o;
  }

  function idxTile(name, d, yen) {
    var p = d ? num(d.price) : null, c = d ? num(d.chg) : null;
    return '<div class="xl-i"><div class="xl-n">' + esc(name) + '</div><div class="xl-v">' +
      (p == null ? '—' : (yen ? '¥' : '') + p.toLocaleString(undefined, { maximumFractionDigits: 2 })) +
      '</div><div class="xl-c' + ud(c) + '">' + pc(c, 2) + '</div></div>';
  }
  function gauge(lv) {
    var h = '';
    for (var i = -2; i <= 2; i++) h += '<span class="' + (i === lv ? 'on ' : '') + (i < 0 ? 'neg' : i > 0 ? 'pos' : 'mid') + '"></span>';
    return '<div class="xl-gauge" aria-hidden="true">' + h + '</div>';
  }

  /* 保有：日米どちらの画面でも同じ一覧（自分の市場も含めて1つの表にする） */
  function rowsOf(hj, pj, mk) {
    var out = [], px = (pj && pj.px) || {};
    ((hj && hj.items) || []).forEach(function (h) {
      var cur = num(px[h.c]); if (cur == null) cur = num(h.p);
      out.push({ mk: mk, c: h.c, n: h.n || '', px: cur, buy: num(h.buy), tgt: num(h.tgt), stp: num(h.stp),
                 qty: num(h.qty) || 0, long: !!h.long });
    });
    return out;
  }
  function money(mk, v) {
    if (v == null) return '—';
    return mk === 'US' ? '$' + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                       : '¥' + Math.round(v).toLocaleString();
  }
  function holdTable(rows, rate) {
    if (!rows.length) return '<p class="xl-mut">保有銘柄はありません。</p>';
    rows.forEach(function (r) {
      r.pl = (r.px != null && r.buy) ? (r.px / r.buy - 1) * 100 : null;
      r.toS = (r.px && r.stp) ? (r.stp / r.px - 1) * 100 : null;
      r.toT = (r.px && r.tgt) ? (r.tgt / r.px - 1) * 100 : null;
      if (r.px != null && r.stp && r.px <= r.stp) { r.st = '損切圏'; r.sc = 'sell'; r.o = 0; }
      else if (r.px != null && r.tgt && r.px >= r.tgt && !r.long) { r.st = '利確圏'; r.sc = 'buy'; r.o = 1; }
      else if (r.toS != null && r.toS > -3) { r.st = '損切接近'; r.sc = 'warn'; r.o = 2; }
      else { r.st = r.long ? '長期' : '保有中'; r.sc = 'hold'; r.o = 3; }
    });
    rows.sort(function (a, b) { return a.o - b.o || (a.pl == null) - (b.pl == null) || (a.pl || 0) - (b.pl || 0); });
    var h = '<div class="xl-hl">';
    rows.forEach(function (r) {
      h += '<div class="xl-h">' +
        '<span class="xl-mk ' + (r.mk === 'US' ? 'us' : 'jp') + '">' + (r.mk === 'US' ? '米' : '日') + '</span>' +
        '<span class="xl-hn"><b>' + esc(r.c) + '</b><small>' + esc(r.n) + '</small></span>' +
        '<span class="xl-hp">' + money(r.mk, r.px) + '<small class="' + ud(r.pl).trim() + '">' + pc(r.pl) + '</small></span>' +
        '<span class="xl-hd"><small>損切まで ' + (r.toS == null ? '—' : pc(r.toS)) + '</small><small>' +
        (r.long ? '利確通知OFF' : '利確まで ' + (r.toT == null ? '—' : pc(r.toT))) + '</small></span>' +
        '<span class="xl-st ' + r.sc + '">' + r.st + '</span></div>';
    });
    h += '</div>';
    /* 合計：株数がある銘柄だけ実額（ドルは円換算して合算） */
    var yen = 0, have = 0, miss = 0;
    rows.forEach(function (r) {
      if (r.qty && r.px != null && r.buy) { yen += (r.px - r.buy) * r.qty * (r.mk === 'US' ? (rate || 0) : 1); have++; }
      else miss++;
    });
    var jp = rows.filter(function (r) { return r.mk === 'JP' && r.pl != null; });
    var us = rows.filter(function (r) { return r.mk === 'US' && r.pl != null; });
    function avg(a) { return a.length ? a.reduce(function (s, r) { return s + r.pl; }, 0) / a.length : null; }
    var s = [];
    if (jp.length) s.push('🇯🇵 ' + jp.length + '銘柄 平均 <b class="' + ud(avg(jp)).trim() + '">' + pc(avg(jp)) + '</b>');
    if (us.length) s.push('🇺🇸 ' + us.length + '銘柄 平均 <b class="' + ud(avg(us)).trim() + '">' + pc(avg(us)) + '</b>');
    if (have && rate) s.push('株数のある' + have + '銘柄の評価損益 <b class="' + ud(yen).trim() + '">' + (yen >= 0 ? '+' : '−') + '¥' + Math.round(Math.abs(yen)).toLocaleString() + '</b>');
    return '<div class="xl-sum">' + s.join('<span class="xl-sep">／</span>') + '</div>' + h +
      (miss ? '<p class="xl-mut">※株数が未登録の銘柄は損益率のみ（holdings.txt に株数を書くと実額で合算）</p>' : '');
  }

  function render(gp, kd, gh, kh, kp) {
    var idx = (gp && gp.idx) || {}, rg = kd && kd.regime, j = judge(idx, rg);
    var rate = pxOf(idx, 'USDJPY');
    var live = gp && gp.mkt && gp.mkt.open_ms && gp.mkt.close_ms && Date.now() >= gp.mkt.open_ms && Date.now() < gp.mkt.close_ms;
    var h = '';
    if (j) {
      h += '<div class="xl-verdict lv' + (j.lv + 2) + '"><div class="xl-vh"><span class="xl-ic">' + j.icon + '</span>' +
        '<span class="xl-vt"><small>' + (live ? '米国市場 取引中の途中経過から見た 次の東京市場' : '前夜の米国市場から見た 次の東京市場') + '</small>' +
        '<b>日本株：' + esc(j.label) + '</b></span>' + gauge(j.lv) + '</div>' +
        '<p class="xl-desc">' + esc(j.desc) + '</p>' +
        '<div class="xl-ax"><span>①米国株 <b class="' + ud(j.us).trim() + '">' + pc(j.us, 2) + '</b></span>' +
        '<span>②ドル円 <b>' + (j.fx == null ? '—' : (j.f > 0 ? '円安 ' : j.f < 0 ? '円高 ' : '横ばい ') + pc(j.fx, 2)) + '</b></span></div>' +
        (j.notes.length ? '<ul class="xl-notes">' + j.notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' : '') +
        '</div>';
    } else {
      h += '<p class="xl-mut">米国市場のデータを読み込めませんでした（GLOBE ORACLE の更新待ち）。</p>';
    }
    h += '<div class="xl-grid">' + idxTile('S&P 500', idx.SP500) + idxTile('NASDAQ', idx.NASDAQ) + idxTile('NYダウ', idx.DOW) +
      idxTile('SOX 半導体', idx.SOX) + idxTile('ドル円', idx.USDJPY, true) +
      (rg ? '<div class="xl-i"><div class="xl-n">日経平均</div><div class="xl-v">' + (num(rg.price) == null ? '—' : num(rg.price).toLocaleString()) +
        '</div><div class="xl-c' + ud(num(rg.chg1)) + '">' + (num(rg.chg1) == null ? '' : '前日 ' + pc(num(rg.chg1), 2)) + '</div></div>' : '') +
      '</div>';
    var meta = [];
    if (rg) meta.push('④ 日本の地合い ' + esc((rg.icon || '') + ' ' + rg.label) + '（日経20日 ' + pc(num(rg.chg20)) + '）');
    if (pxOf(idx, 'US10Y') != null) meta.push('③ 米10年金利 ' + pxOf(idx, 'US10Y').toFixed(2) + '%');
    if (meta.length) h += '<p class="xl-meta">' + meta.join('<span class="xl-sep">／</span>') + '</p>';
    h += '<h3 class="xl-h3">日米の保有まとめ</h3>' +
      holdTable(rowsOf(kh, kp, 'JP').concat(rowsOf(gh, gp, 'US')), rate);
    var src = [];
    if (gp && gp.asof) src.push('米国 ' + esc(gp.asof) + ' JST');
    if (kd && kd.generated) src.push('日本 ' + esc(kd.generated));
    h += '<p class="xl-src">' + src.join('・') + ' 時点 ／ ' +
      (SELF === 'kabu' ? '<a href="' + G + '">🌎 GLOBE ORACLE で米国株を見る ›</a>' : '<a href="' + K + '">🇯🇵 株オラクルで日本株を見る ›</a>') +
      '<br>判定は「米国株×ドル円」の目安です。日銀・FRBの会合や日本の決算発表がある日は、そちらが優先されることがあります。</p>';
    box.innerHTML = h;
    var cnt = document.getElementById('xlcnt');
    if (cnt && j) cnt.textContent = j.icon + ' ' + j.label;
  }

  function load() {
    return Promise.all([get(G + 'prices.json'), get(K + 'data.json'), get(G + 'holdings.json'),
                        get(K + 'holdings.json'), get(K + 'prices.json')])
      .then(function (a) { render(a[0], a[1], a[2], a[3], a[4]); })
      .catch(function (e) { console.warn('[xlink] 失敗', e); });
  }
  load();
  setInterval(function () { if (!document.hidden) load(); }, 10 * 60 * 1000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });
})();
