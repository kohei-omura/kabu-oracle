"""GitHub Pages 用の静的ダッシュボード（docs/index.html）を生成する。

データは生成時に HTML へ直接埋め込む（fetch 不要・CORS 問題なし）。
毎回の自動実行で docs/index.html を上書き → GitHub Pages が最新を配信。
"""
from __future__ import annotations
import html
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ranking as R
import watch as W

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"


def _esc(s) -> str:
    return html.escape(str(s))


def _score_bar(score: float) -> str:
    """-100〜+100 を中央起点のバーに変換。"""
    pct = max(-100, min(100, score)) / 100
    if pct >= 0:
        return (f'<span class="bar"><span class="bar-pos" '
                f'style="width:{pct*50:.0f}%"></span></span>')
    return (f'<span class="bar"><span class="bar-neg" '
            f'style="width:{abs(pct)*50:.0f}%;margin-left:{50-abs(pct)*50:.0f}%">'
            f'</span></span>')


def _badge(signal: str) -> str:
    m = {"BUY": ("買", "buy"), "SELL": ("売", "sell"), "HOLD": ("待", "hold")}
    label, cls = m.get(signal, ("待", "hold"))
    return f'<span class="badge {cls}">{label}</span>'


def _card(rank: int, a, show_levels: bool) -> str:
    levels = ""
    if show_levels and a.signal == "BUY" and a.entry and a.target and a.stop:
        rr = f' ・ RR {a.rr}' if a.rr else ''
        levels = (f'<div class="levels">'
                  f'<span class="lv tgt">利確 ¥{a.target:,.0f}</span>'
                  f'<span class="lv stp">損切 ¥{a.stop:,.0f}</span>'
                  f'<span class="lv rr">{_esc(rr.strip(" ・"))}</span></div>')
    reasons = ""
    if a.reasons:
        chips = "".join(f'<span class="chip">{_esc(r)}</span>'
                        for r in a.reasons[:3])
        reasons = f'<div class="reasons">{chips}</div>'
    sc_cls = "pos" if a.score >= 0 else "neg"
    return f'''<div class="card" style="animation-delay:{rank*0.05:.2f}s">
      <div class="row1">
        <span class="rank">{rank}</span>
        <div class="title">
          <span class="code">{_esc(a.code)}</span>
          <span class="name">{_esc(a.name)}</span>
        </div>
        {_badge(a.signal)}
      </div>
      <div class="row2">
        <span class="price">¥{a.price:,.0f}</span>
        <span class="score {sc_cls}">{a.score:+.0f}</span>
        {_score_bar(a.score)}
      </div>
      {levels}
      {reasons}
    </div>'''


def _section(title: str, sub: str, cards_html: str, accent: str) -> str:
    return f'''<section>
      <h2 class="{accent}"><span>{_esc(title)}</span><em>{_esc(sub)}</em></h2>
      <div class="cards">{cards_html}</div>
    </section>'''


def build_html(cfg: dict) -> tuple[str, dict]:
    now = datetime.now(JST)
    date_str = now.strftime("%Y.%m.%d %H:%M")
    buys, sells, total = R.build_rankings(cfg)
    results, _ = W.check_watchlist(cfg)

    buy_cards = "".join(_card(i, a, True) for i, a in enumerate(buys, 1))
    sell_cards = "".join(_card(i, a, False) for i, a in enumerate(sells, 1))
    watch_cards = "".join(
        _card(i, a, True)
        for i, a in enumerate(sorted(results, key=lambda x: x.score, reverse=True), 1)
    ) or '<p class="empty">監視銘柄が未設定です（config.yaml の watchlist）。</p>'

    data = {
        "generated": date_str, "total": total,
        "buys": [vars(a) for a in buys],
        "sells": [vars(a) for a in sells],
        "watch": [vars(a) for a in results],
    }

    page = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>株オラクル — Kabu Oracle</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0c0e13; --bg2:#12151d; --card:#161a24; --line:#242a37;
  --ink:#e8e6df; --mut:#8b93a7; --gold:#d4af56; --gold-d:#9a7c30;
  --buy:#46c46a; --sell:#ef5f7a; --hold:#6b7286;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:'Zen Kaku Gothic New',sans-serif; color:var(--ink);
  background:
    radial-gradient(1200px 600px at 80% -10%, rgba(212,175,86,.10), transparent 60%),
    radial-gradient(900px 500px at -10% 20%, rgba(70,90,140,.10), transparent 55%),
    var(--bg);
  background-attachment:fixed; line-height:1.6;
  padding:env(safe-area-inset-top) 0 64px;
  -webkit-font-smoothing:antialiased;
}}
.wrap{{max-width:680px;margin:0 auto;padding:0 18px}}
header{{padding:34px 0 10px;border-bottom:1px solid var(--line);margin-bottom:8px}}
.brand{{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}}
.brand h1{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:30px;
  letter-spacing:.04em;color:var(--gold)}}
.brand .en{{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.32em;
  color:var(--mut);text-transform:uppercase}}
.meta{{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--mut);
  margin-top:8px;display:flex;gap:14px;flex-wrap:wrap}}
.meta b{{color:var(--gold-d);font-weight:600}}
section{{margin-top:30px}}
h2{{font-family:'Shippori Mincho',serif;font-size:19px;font-weight:600;
  display:flex;align-items:baseline;gap:10px;margin-bottom:14px;
  padding-left:12px;border-left:3px solid var(--gold)}}
h2.sell{{border-color:var(--sell)}} h2.watch{{border-color:var(--mut)}}
h2 em{{font-style:normal;font-family:'IBM Plex Mono',monospace;font-size:10px;
  letter-spacing:.2em;color:var(--mut);text-transform:uppercase}}
.cards{{display:flex;flex-direction:column;gap:10px}}
.card{{background:linear-gradient(180deg,var(--card),var(--bg2));
  border:1px solid var(--line);border-radius:14px;padding:14px 15px;
  opacity:0;transform:translateY(8px);animation:rise .5s ease forwards;
  box-shadow:0 1px 0 rgba(255,255,255,.02) inset}}
@keyframes rise{{to{{opacity:1;transform:none}}}}
.row1{{display:flex;align-items:center;gap:11px}}
.rank{{font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:13px;
  color:var(--gold);width:22px;height:22px;display:grid;place-items:center;
  border:1px solid var(--gold-d);border-radius:50%;flex:none}}
.title{{flex:1;min-width:0;display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}}
.code{{font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:600}}
.name{{font-size:13px;color:var(--mut)}}
.badge{{flex:none;width:26px;height:26px;display:grid;place-items:center;
  border-radius:8px;font-size:13px;font-weight:700}}
.badge.buy{{color:var(--buy);background:rgba(70,196,106,.12);border:1px solid rgba(70,196,106,.3)}}
.badge.sell{{color:var(--sell);background:rgba(239,95,122,.12);border:1px solid rgba(239,95,122,.3)}}
.badge.hold{{color:var(--mut);background:rgba(139,147,167,.1);border:1px solid var(--line)}}
.row2{{display:flex;align-items:center;gap:12px;margin-top:11px}}
.price{{font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:600}}
.score{{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;
  min-width:42px;text-align:right}}
.score.pos{{color:var(--buy)}} .score.neg{{color:var(--sell)}}
.bar{{flex:1;height:6px;background:var(--bg);border-radius:99px;position:relative;
  overflow:hidden;border:1px solid var(--line)}}
.bar::before{{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;
  background:var(--line)}}
.bar-pos{{position:absolute;left:50%;top:0;bottom:0;background:linear-gradient(90deg,var(--gold-d),var(--buy));border-radius:99px}}
.bar-neg{{position:absolute;top:0;bottom:0;background:linear-gradient(90deg,var(--sell),var(--gold-d));border-radius:99px}}
.levels{{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px}}
.lv{{font-family:'IBM Plex Mono',monospace;font-size:11px;padding:3px 9px;
  border-radius:7px;border:1px solid var(--line)}}
.lv.tgt{{color:var(--buy)}} .lv.stp{{color:var(--sell)}} .lv.rr{{color:var(--mut)}}
.reasons{{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}}
.chip{{font-size:11px;color:var(--mut);background:var(--bg);border:1px solid var(--line);
  padding:3px 9px;border-radius:99px}}
.empty{{color:var(--mut);font-size:13px;padding:8px 2px}}
footer{{margin-top:38px;padding-top:18px;border-top:1px solid var(--line);
  font-size:11px;color:var(--mut);line-height:1.8}}
footer b{{color:var(--gold-d)}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <h1>株オラクル</h1><span class="en">Kabu Oracle</span>
    </div>
    <div class="meta">
      <span>更新 <b>{date_str}</b> JST</span>
      <span>分析 <b>{total}</b> 銘柄</span>
    </div>
  </header>

  {_section("買い候補", "BUY SIGNALS", buy_cards, "buy")}
  {_section("売り・警戒", "SELL / CAUTION", sell_cards, "sell")}
  {_section("監視銘柄", "WATCHLIST", watch_cards, "watch")}

  <footer>
    <b>免責</b>：本ページは自分用の分析補助であり投資助言ではありません。
    株価は約15〜20分遅延（yfinance）。シグナルは確率的で利益を保証しません。
    投資判断はご自身の責任で行ってください。<br>
    Generated by Kabu Oracle on GitHub Actions.
  </footer>
</div>
</body>
</html>'''
    return page, data


def write_dashboard(cfg: dict) -> Path:
    DOCS.mkdir(exist_ok=True)
    page, data = build_html(cfg)
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    (DOCS / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8")
    # Jekyll を無効化（_ 始まりや特殊処理を避ける）
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"ダッシュボード生成: {DOCS/'index.html'}")
    return DOCS / "index.html"
