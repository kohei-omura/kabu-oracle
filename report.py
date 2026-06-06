"""GitHub Pages 用の静的ダッシュボード（docs/index.html）を生成する。

- 全銘柄を分析し、買い/売りTOPをサーバー側で描画。
- 全銘柄の結果をページに埋め込み:
    * 検索バー … コード/名前から即引き（最大5件）
    * マイ銘柄  … ブラウザに保存した自分の銘柄の判定を一覧表示（端末内保存）
  （静的ページなのでサーバー計算不要・CORS問題なし）
"""
from __future__ import annotations
import html
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ranking as R

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"


def _esc(s) -> str:
    return html.escape(str(s))


def _score_bar(score: float) -> str:
    pct = max(-100, min(100, score)) / 100
    if pct >= 0:
        return ('<span class="bar"><span class="bar-pos" '
                f'style="width:{pct*50:.0f}%"></span></span>')
    return ('<span class="bar"><span class="bar-neg" '
            f'style="width:{abs(pct)*50:.0f}%;margin-left:{50-abs(pct)*50:.0f}%">'
            '</span></span>')


def _badge(signal: str) -> str:
    m = {"BUY": ("買", "buy"), "SELL": ("売", "sell"), "HOLD": ("待", "hold")}
    label, cls = m.get(signal, ("待", "hold"))
    return f'<span class="badge {cls}">{label}</span>'


def _card(rank: int, a, show_levels: bool) -> str:
    levels = ""
    if show_levels and a.signal == "BUY" and a.entry and a.target and a.stop:
        rr = f' ・ RR {a.rr}' if a.rr else ''
        levels = ('<div class="levels">'
                  f'<span class="lv tgt">利確 ¥{a.target:,.0f}</span>'
                  f'<span class="lv stp">損切 ¥{a.stop:,.0f}</span>'
                  f'<span class="lv rr">{_esc(rr.strip(" ・"))}</span></div>')
    reasons = ""
    if a.reasons:
        chips = "".join(f'<span class="chip">{_esc(r)}</span>'
                        for r in a.reasons[:3])
        reasons = f'<div class="reasons">{chips}</div>'
    sc_cls = "pos" if a.score >= 0 else "neg"
    return (f'<div class="card" style="animation-delay:{rank*0.05:.2f}s">'
            f'<div class="row1"><span class="rank">{rank}</span>'
            f'<div class="title"><span class="code">{_esc(a.code)}</span>'
            f'<span class="name">{_esc(a.name)}</span></div>{_badge(a.signal)}</div>'
            f'<div class="row2"><span class="price">¥{a.price:,.0f}</span>'
            f'<span class="score {sc_cls}">{a.score:+.0f}</span>{_score_bar(a.score)}</div>'
            f'{levels}{reasons}</div>')


def _section(title: str, sub: str, cards_html: str, accent: str) -> str:
    return (f'<section><h2 class="{accent}"><span>{_esc(title)}</span>'
            f'<em>{_esc(sub)}</em></h2>'
            f'<div class="cards">{cards_html}</div></section>')


CSS = """
:root{
  --bg:#0c0e13; --bg2:#12151d; --card:#161a24; --line:#242a37;
  --ink:#e8e6df; --mut:#8b93a7; --gold:#d4af56; --gold-d:#9a7c30;
  --buy:#46c46a; --sell:#ef5f7a; --hold:#6b7286;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:'Zen Kaku Gothic New',sans-serif; color:var(--ink);
  background:
    radial-gradient(1200px 600px at 80% -10%, rgba(212,175,86,.10), transparent 60%),
    radial-gradient(900px 500px at -10% 20%, rgba(70,90,140,.10), transparent 55%),
    var(--bg);
  background-attachment:fixed; line-height:1.6;
  padding:env(safe-area-inset-top) 0 64px; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:680px;margin:0 auto;padding:0 18px}
header{padding:34px 0 10px;border-bottom:1px solid var(--line);margin-bottom:8px}
.brand{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.brand h1{font-family:'Shippori Mincho',serif;font-weight:800;font-size:30px;
  letter-spacing:.04em;color:var(--gold)}
.brand .en{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.32em;
  color:var(--mut);text-transform:uppercase}
.meta{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--mut);
  margin-top:8px;display:flex;gap:14px;flex-wrap:wrap}
.meta b{color:var(--gold-d);font-weight:600}
section{margin-top:30px}
h2{font-family:'Shippori Mincho',serif;font-size:19px;font-weight:600;
  display:flex;align-items:baseline;gap:10px;margin-bottom:14px;
  padding-left:12px;border-left:3px solid var(--gold)}
h2.sell{border-color:var(--sell)} h2.watch{border-color:var(--mut)}
h2.find{border-color:var(--gold)}
h2 em{font-style:normal;font-family:'IBM Plex Mono',monospace;font-size:10px;
  letter-spacing:.2em;color:var(--mut);text-transform:uppercase}
.cards{display:flex;flex-direction:column;gap:10px}
.card{background:linear-gradient(180deg,var(--card),var(--bg2));
  border:1px solid var(--line);border-radius:14px;padding:14px 15px;
  opacity:0;transform:translateY(8px);animation:rise .5s ease forwards;
  box-shadow:0 1px 0 rgba(255,255,255,.02) inset}
@keyframes rise{to{opacity:1;transform:none}}
.row1{display:flex;align-items:center;gap:11px}
.rank{font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:13px;
  color:var(--gold);min-width:22px;height:22px;display:grid;place-items:center;
  border:1px solid var(--gold-d);border-radius:50%;flex:none;padding:0 4px}
.title{flex:1;min-width:0;display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.code{font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:600}
.name{font-size:13px;color:var(--mut)}
.badge{flex:none;width:26px;height:26px;display:grid;place-items:center;
  border-radius:8px;font-size:13px;font-weight:700}
.badge.buy{color:var(--buy);background:rgba(70,196,106,.12);border:1px solid rgba(70,196,106,.3)}
.badge.sell{color:var(--sell);background:rgba(239,95,122,.12);border:1px solid rgba(239,95,122,.3)}
.badge.hold{color:var(--mut);background:rgba(139,147,167,.1);border:1px solid var(--line)}
.rm{flex:none;width:26px;height:26px;border-radius:8px;border:1px solid var(--line);
  background:var(--bg);color:var(--mut);font-size:16px;line-height:1;cursor:pointer}
.rm:active{background:var(--card)}
.row2{display:flex;align-items:center;gap:12px;margin-top:11px}
.price{font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:600}
.score{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;
  min-width:42px;text-align:right}
.score.pos{color:var(--buy)} .score.neg{color:var(--sell)}
.bar{flex:1;height:6px;background:var(--bg);border-radius:99px;position:relative;
  overflow:hidden;border:1px solid var(--line)}
.bar::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line)}
.bar-pos{position:absolute;left:50%;top:0;bottom:0;background:linear-gradient(90deg,var(--gold-d),var(--buy));border-radius:99px}
.bar-neg{position:absolute;top:0;bottom:0;background:linear-gradient(90deg,var(--sell),var(--gold-d));border-radius:99px}
.levels{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px}
.lv{font-family:'IBM Plex Mono',monospace;font-size:11px;padding:3px 9px;
  border-radius:7px;border:1px solid var(--line)}
.lv.tgt{color:var(--buy)} .lv.stp{color:var(--sell)} .lv.rr{color:var(--mut)}
.reasons{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.chip{font-size:11px;color:var(--mut);background:var(--bg);border:1px solid var(--line);
  padding:3px 9px;border-radius:99px}
.rankline{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--gold-d);margin-top:10px}
.empty{color:var(--mut);font-size:13px;padding:8px 2px}
#q,#myq{width:100%;font-family:'IBM Plex Mono',monospace;font-size:16px;color:var(--ink);
  background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:13px 15px;outline:none}
#q:focus,#myq:focus{border-color:var(--gold-d)}
#q::placeholder,#myq::placeholder{color:var(--mut)}
#results,#mylist{margin-top:12px}
.myadd{display:flex;gap:8px}
.myadd #myq{flex:1}
#myadd{flex:none;padding:0 18px;border-radius:12px;border:1px solid var(--gold-d);
  background:rgba(212,175,86,.12);color:var(--gold);font-weight:700;font-size:15px;cursor:pointer}
#myadd:active{background:rgba(212,175,86,.22)}
.mytools{display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap}
#mycopy{padding:8px 14px;border-radius:10px;border:1px solid var(--line);
  background:var(--bg2);color:var(--ink);font-size:13px;cursor:pointer}
#mycopy:active{background:var(--card)}
.mut{font-size:12px;color:var(--mut)}
footer{margin-top:38px;padding-top:18px;border-top:1px solid var(--line);
  font-size:11px;color:var(--mut);line-height:1.8}
footer b{color:var(--gold-d)}
"""

JS = r"""
const TOTAL = STOCKS.length;
function badge(g){
  const m = {BUY:['買','buy'], SELL:['売','sell'], HOLD:['待','hold']};
  const x = m[g] || m.HOLD;
  return '<span class="badge ' + x[1] + '">' + x[0] + '</span>';
}
function bar(sc){
  const p = Math.max(-100, Math.min(100, sc)) / 100;
  if (p >= 0) return '<span class="bar"><span class="bar-pos" style="width:' + (p*50) + '%"></span></span>';
  return '<span class="bar"><span class="bar-neg" style="width:' + (Math.abs(p)*50) + '%;margin-left:' + (50-Math.abs(p)*50) + '%"></span></span>';
}
function card(s, removable){
  const scls = s.sc >= 0 ? 'pos' : 'neg';
  let levels = '';
  if (s.g === 'BUY' && s.t && s.st) {
    levels = '<div class="levels"><span class="lv tgt">利確 ¥' + s.t.toLocaleString() +
      '</span><span class="lv stp">損切 ¥' + s.st.toLocaleString() + '</span>' +
      (s.rr ? '<span class="lv rr">RR ' + s.rr + '</span>' : '') + '</div>';
  }
  let reasons = '';
  if (s.r && s.r.length) {
    reasons = '<div class="reasons">' + s.r.map(function(r){return '<span class="chip">' + r + '</span>';}).join('') + '</div>';
  }
  const rm = removable ? '<button class="rm" data-c="' + s.c + '">×</button>' : '';
  return '<div class="card">' +
    '<div class="row1"><span class="rank">' + s.rk + '</span>' +
    '<div class="title"><span class="code">' + s.c + '</span><span class="name">' + s.n + '</span></div>' +
    badge(s.g) + rm + '</div>' +
    '<div class="row2"><span class="price">¥' + s.p.toLocaleString() + '</span>' +
    '<span class="score ' + scls + '">' + (s.sc >= 0 ? '+' : '') + s.sc + '</span>' + bar(s.sc) + '</div>' +
    levels + reasons +
    '<div class="rankline">スコア順 総合 ' + s.rk + ' 位 / ' + TOTAL + ' 銘柄中</div>' +
    '</div>';
}
function byCode(code){
  const v = code.toLowerCase();
  for (let i=0;i<STOCKS.length;i++){ if (STOCKS[i].c.toLowerCase() === v) return STOCKS[i]; }
  return null;
}

/* ---- 検索バー ---- */
const q = document.getElementById('q');
const results = document.getElementById('results');
const hint = document.getElementById('hint');
function run(){
  const v = q.value.trim().toLowerCase();
  if (!v) { results.innerHTML = ''; hint.style.display = ''; return; }
  hint.style.display = 'none';
  const m = STOCKS.filter(function(s){
    return s.c.toLowerCase().indexOf(v) === 0 || s.n.toLowerCase().indexOf(v) >= 0;
  }).sort(function(a,b){return b.sc - a.sc;}).slice(0, 5);
  results.innerHTML = m.length ? m.map(function(s){return card(s,false);}).join('')
    : '<p class="empty">該当する銘柄が見つかりません。コードや銘柄名を確認してください。</p>';
}
q.addEventListener('input', run);

/* ---- マイ銘柄（この端末に保存） ---- */
const MYKEY = 'kabu_watch';
const myq = document.getElementById('myq');
const myadd = document.getElementById('myadd');
const mylist = document.getElementById('mylist');
const myhint = document.getElementById('myhint');
function getMy(){ try { return JSON.parse(localStorage.getItem(MYKEY)) || []; } catch(e){ return []; } }
function setMy(a){ try { localStorage.setItem(MYKEY, JSON.stringify(a)); } catch(e){} }
function renderMy(){
  const list = getMy();
  if (!list.length){ mylist.innerHTML=''; myhint.style.display=''; return; }
  myhint.style.display='none';
  mylist.innerHTML = list.map(function(code){
    const s = byCode(code);
    if (s) return card(s, true);
    return '<div class="card"><div class="row1">' +
      '<div class="title"><span class="code">' + code + '</span>' +
      '<span class="name">対象外/データなし</span></div>' +
      '<button class="rm" data-c="' + code + '">×</button></div></div>';
  }).join('');
}
function addCode(){
  const v = myq.value.trim();
  if (!v) return;
  const list = getMy();
  const lower = list.map(function(x){return x.toLowerCase();});
  if (lower.indexOf(v.toLowerCase()) < 0){ list.push(v); setMy(list); }
  myq.value=''; renderMy();
}
myadd.addEventListener('click', addCode);
myq.addEventListener('keydown', function(e){ if (e.key === 'Enter') addCode(); });
mylist.addEventListener('click', function(e){
  if (e.target.classList.contains('rm')){
    const c = e.target.getAttribute('data-c');
    setMy(getMy().filter(function(x){ return x.toLowerCase() !== c.toLowerCase(); }));
    renderMy();
  }
});

/* push用にコピー（watchlist.txt へ貼り付ける用） */
const mycopy = document.getElementById('mycopy');
const mystatus = document.getElementById('mystatus');
function copyMy(){
  const text = getMy().join('\n');
  if (!text){ mystatus.textContent = '登録がありません'; return; }
  function done(){ mystatus.textContent = 'コピーしました → watchlist.txt に貼り付け'; }
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done).catch(function(){ window.prompt('コピーしてください:', text); });
  } else {
    window.prompt('コピーしてください:', text);
  }
}
mycopy.addEventListener('click', copyMy);

renderMy();
"""


def build_html(cfg: dict) -> tuple[str, dict]:
    now = datetime.now(JST)
    date_str = now.strftime("%Y.%m.%d %H:%M")
    top_n = int(cfg.get("top_n", 5))

    analyses = R.analyze_universe(cfg)
    total = len(analyses)
    buys = analyses[:top_n]
    sells = sorted(analyses, key=lambda x: x.score)[:top_n]

    buy_cards = "".join(_card(i, a, True) for i, a in enumerate(buys, 1))
    sell_cards = "".join(_card(i, a, False) for i, a in enumerate(sells, 1))

    index = []
    for rank, a in enumerate(analyses, 1):
        index.append({
            "c": _esc(a.code), "n": _esc(a.name), "g": a.signal,
            "sc": round(a.score), "p": round(a.price),
            "t": round(a.target) if a.target else None,
            "st": round(a.stop) if a.stop else None,
            "rr": a.rr, "r": [_esc(x) for x in (a.reasons or [])[:3]],
            "rk": rank,
        })
    index_json = json.dumps(index, ensure_ascii=False, default=str).replace("</", "<\\/")

    data = {
        "generated": date_str, "total": total,
        "buys": [vars(a) for a in buys],
        "sells": [vars(a) for a in sells],
    }

    head = (
        '<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<title>株オラクル — Kabu Oracle</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800'
        '&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=IBM+Plex+Mono:wght@500;600'
        '&display=swap" rel="stylesheet"><style>' + CSS + '</style></head>'
    )

    body = f'''<body><div class="wrap">
  <header>
    <div class="brand"><h1>株オラクル</h1><span class="en">Kabu Oracle</span></div>
    <div class="meta"><span>更新 <b>{date_str}</b> JST</span><span>分析 <b>{total}</b> 銘柄</span></div>
  </header>

  <section id="search-sec">
    <h2 class="find"><span>銘柄サーチ</span><em>CODE SEARCH</em></h2>
    <input id="q" type="search" inputmode="text" autocomplete="off"
           placeholder="証券コード や 銘柄名（例: 7203 / トヨタ）">
    <div id="results" class="cards"></div>
    <p id="hint" class="empty">コードや銘柄名を入れると買い/売り判定と総合順位を表示します（最大5件）。</p>
  </section>

  <section id="my-sec">
    <h2 class="watch"><span>マイ銘柄</span><em>MY WATCHLIST</em></h2>
    <div class="myadd">
      <input id="myq" type="search" inputmode="text" autocomplete="off"
             placeholder="証券コードを入力して追加（例: 7203）">
      <button id="myadd" type="button">追加</button>
    </div>
    <div id="mylist" class="cards"></div>
    <div class="mytools">
      <button id="mycopy" type="button">push用にコピー</button>
      <span id="mystatus" class="mut"></span>
    </div>
    <p id="myhint" class="empty">よく見る銘柄を登録すると、ここに買い/売り判定が並びます（この端末に保存・更新ごとに最新化）。LINE/メールでも知らせてほしい時は「push用にコピー」→ GitHubの watchlist.txt に貼り付け。</p>
  </section>

  {_section("買い候補", "BUY SIGNALS", buy_cards, "buy")}
  {_section("売り・警戒", "SELL / CAUTION", sell_cards, "sell")}

  <footer>
    <b>免責</b>：本ページは自分用の分析補助であり投資助言ではありません。
    株価は約15〜20分遅延（yfinance）。シグナルは確率的で利益を保証しません。
    投資判断はご自身の責任で行ってください。<br>Generated by Kabu Oracle on GitHub Actions.
  </footer>
</div>'''

    script = "<script>\nconst STOCKS = " + index_json + ";\n" + JS + "\n</script>"
    page = head + body + script + "</body></html>"
    return page, data


def write_dashboard(cfg: dict) -> Path:
    DOCS.mkdir(exist_ok=True)
    page, data = build_html(cfg)
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    (DOCS / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"ダッシュボード生成: {DOCS/'index.html'}")
    return DOCS / "index.html"
