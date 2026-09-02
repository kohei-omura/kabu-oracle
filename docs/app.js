
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
    if (gear) gear.addEventListener('click', function () {
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
})();
