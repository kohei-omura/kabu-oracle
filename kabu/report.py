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
import math
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import ranking as R
from .config import market_map, load_holdings

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent   # リポジトリ直下
DOCS = ROOT / "docs"


def _seg(market: str) -> str:
    m = {"prime": ("P", "p"), "standard": ("S", "s"), "growth": ("G", "g")}
    if market not in m:
        return ""
    label, cls = m[market]
    return f'<span class="seg {cls}">{label}</span>'


def _esc(s) -> str:
    return html.escape(str(s))


def _search_key(name: str, code: str) -> str:
    """検索用キー：NFKC正規化＋小文字化＋ひらがな→カタカナ変換した名前＋半角空白＋コード。"""
    s = unicodedata.normalize("NFKC", str(name)).lower()
    kata = "".join(
        chr(ord(ch) + 0x60) if "\u3041" <= ch <= "\u3096" else ch
        for ch in s
    )
    return f"{kata} {str(code).lower()}"


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


def _val_block(price: float, fund) -> str:
    """桐谷方式：3方式の割安/割高チップ＋『割安N/M（購入検討）』判定を描画。"""
    cons = (fund or {}).get("cons")
    if not cons or not cons.get("judg"):
        theo = (fund or {}).get("theo")
        if not theo:
            return ""
        gap = (price / theo - 1) * 100
        lab = "割安" if gap <= -5 else ("割高" if gap >= 5 else "ほぼ適正")
        cls = "und" if gap <= -5 else ("over" if gap >= 5 else "fair")
        return (f'<div class="val"><span class="tchip {cls}">'
                f'理論株価 ¥{theo:,} ・ {lab}</span></div>')
    cmap = {"u": "und", "o": "over", "f": "fair"}
    lmap = {"u": "割安", "o": "割高", "f": "適正"}
    chips = "".join(
        f'<span class="cchip {cmap[d["lab"]]}">{_esc(name)} ¥{d["fair"]:,}'
        f'<i>{lmap[d["lab"]]}</i></span>'
        for name, d in cons["judg"].items())
    und, avail, buy = cons["und"], cons["avail"], cons["buy"]
    vcls = "buy" if buy else ""
    verdict = f'コンセンサス 割安 {und}/{avail}' + ('　✅ 購入検討' if buy else '')
    return (f'<div class="cons"><div class="cchips">{chips}</div>'
            f'<div class="cverdict {vcls}">{verdict}</div></div>')


def _card(rank: int, a, show_levels: bool, market: str = "") -> str:
    levels = ""
    if show_levels and a.entry and a.target and a.stop:
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
    fund = ""
    if a.fund:
        f = a.fund
        fc = []
        if f.get("per") is not None: fc.append(f'<span class="fchip">PER {f["per"]:.1f}</span>')
        if f.get("pbr") is not None: fc.append(f'<span class="fchip">PBR {f["pbr"]:.2f}</span>')
        if f.get("roe") is not None: fc.append(f'<span class="fchip">ROE {f["roe"]:.1f}%</span>')
        if f.get("divy") is not None: fc.append(f'<span class="fchip">利回り {f["divy"]:.1f}%</span>')
        if f.get("growth") is not None: fc.append(f'<span class="fchip">増益 {f["growth"]:+.0f}%</span>')
        if fc:
            fund = f'<div class="funds">{"".join(fc)}</div>'
    val = _val_block(a.price, a.fund)
    ez_html = ""
    ez = getattr(a, "ez", None)
    if ez:
        ezc, dip, hi, gap = _esc(a.code), ez["dip"], ez["hi"], ez["gap"]
        if gap < 1.0:
            inner = (f'🎯 狙い目 現値 ¥{hi:,}〜'
                     f'<span class="ezn">押し目余地は小</span>')
        else:
            inner = (f'🎯 狙い目 指値 ¥{dip:,} 〜 現値 ¥{hi:,}'
                     f'<span class="ezn">-{gap:.0f}% の押し目</span>')
        ez_html = (f'<div class="ez" data-ez-c="{ezc}" data-ez-limit="{dip}" '
                   f'data-ez-pct="{gap:.0f}">{inner}</div>')
    bt_html = ""
    if a.bt:
        b = a.bt
        items = [f'<span class="btchip win">利確勝率 {b["win_rate"]}%</span>']
        if b.get("days_tp"):
            items.append(f'<span class="btchip">利確まで ~{b["days_tp"]}日</span>')
        if b.get("days_sl"):
            items.append(f'<span class="btchip">損切まで ~{b["days_sl"]}日</span>')
        bt_html = f'<div class="bt">{"".join(items)}</div>'
    has_c = a.combined is not None
    disp = a.combined if has_c else a.score
    sc_cls = "pos" if disp >= 0 else "neg"
    sc_txt = f'複合 {a.combined:.0f}' if has_c else f'{a.score:+.0f}'
    return (f'<div class="card" style="animation-delay:{rank*0.05:.2f}s">'
            f'<div class="row1"><span class="rank">{rank}</span>'
            f'<div class="title"><span class="code">{_esc(a.code)}</span>'
            f'<span class="name">{_esc(a.name)}</span>{_seg(market)}</div>{_badge(a.signal)}</div>'
            f'<div class="row2"><span class="price" data-px="{_esc(a.code)}">¥{a.price:,.0f}</span>'
            f'<span class="score {sc_cls}">{sc_txt}</span>{_score_bar(disp)}</div>'
            f'{levels}{ez_html}{fund}{val}{bt_html}{reasons}</div>')


def _section(title: str, sub: str, cards_html: str, accent: str,
             extra: str = "", head_extra: str = "") -> str:
    """extra=見出し行の右端に置く要素 / head_extra=見出し直下に置くブロック。"""
    return (f'<section><h2 class="{accent}"><span>{_esc(title)}</span>'
            f'<em>{_esc(sub)}</em>{extra}</h2>{head_extra}'
            f'<div class="cards">{cards_html}</div></section>')


# 長期保有ボタンから holdings.txt を書き換えるための GitHub 設定パネル
# （トークンは端末のブラウザにのみ保存。詳しい手順はパネル内に表示する）
GH_GEAR = '<button type="button" class="ghgear" id="ghgear" title="GitHub連携の設定">⚙</button>'

GH_PANEL = """<div class="ghpanel" id="ghpanel" hidden>
  <p class="ghlead">「長期保有」ボタンで <b>holdings.txt</b> を書き換えるために、GitHubのトークンを1回だけ登録します。</p>
  <ol class="ghsteps">
    <li>GitHub → Settings → Developer settings → <b>Fine-grained tokens</b> → Generate new token</li>
    <li>Repository access: <b>Only select repositories</b> → このリポジトリだけを選択</li>
    <li>Permissions → Repository permissions → <b>Contents: Read and write</b></li>
  </ol>
  <input id="ghtoken" type="password" autocomplete="off" spellcheck="false" placeholder="github_pat_… を貼り付け">
  <div class="ghrow"><input id="ghowner" placeholder="owner" autocapitalize="off" spellcheck="false"><input id="ghrepo" placeholder="repo" autocapitalize="off" spellcheck="false"><input id="ghbranch" placeholder="main" autocapitalize="off" spellcheck="false"></div>
  <div class="ghbtns"><button type="button" id="ghsave">保存</button><button type="button" id="ghdel">削除</button><span class="ghstat" id="ghstat"></span></div>
  <p class="ghnote">※トークンはこの端末のブラウザ(localStorage)にのみ保存され、リポジトリには書き込まれません。権限は上記の最小構成にしてください。</p>
</div>"""


# 長期見通しで使う年成長率の上限（高い増益率がそのまま何年も続く前提は取らない）
LT_MAX_GROWTH = 0.15
LT_YEARS = (1, 3, 5)


def _long_outlook(price: float, fund) -> dict | None:
    """長期保有した場合の目安株価（理論株価＋利益成長率）。算出不可なら None。

    年成長率 g ＝ min(増益率, 持続可能成長率 ROE×(1−配当性向), 15%) を 0〜15% にクランプ。
    n年後 ＝ 現値×(1+g)^n（PER 維持・年率一定の前提）。
    長期目標 ＝ 理論株価3方式（株マップ/PER/ROE）の中央値。到達目安年数も出す。
    """
    if not fund or not price or price <= 0:
        return None
    cands = []
    if fund.get("growth") is not None:
        cands.append(fund["growth"] / 100.0)          # 増益率
    roe, eps, div = fund.get("roe"), fund.get("eps"), fund.get("div")
    if roe is not None and roe > 0:
        payout = 0.0
        if div and eps and eps > 0:
            payout = max(0.0, min(div / eps, 1.0))    # 配当性向
        cands.append(roe / 100.0 * (1.0 - payout))    # 持続可能成長率
    if not cands:
        return None
    g = max(0.0, min(min(cands), LT_MAX_GROWTH))
    fairs = sorted(float(d["fair"]) for d in ((fund.get("cons") or {}).get("judg") or {}).values()
                   if d.get("fair"))
    if fairs:
        i = len(fairs) // 2
        target = fairs[i] if len(fairs) % 2 else (fairs[i - 1] + fairs[i]) / 2
    else:
        target = float(fund["theo"]) if fund.get("theo") else None
    years = None
    if target and target > price and g > 0:
        years = round(math.log(target / price) / math.log(1 + g), 1)
    return {
        "g": round(g * 100, 1),
        "proj": [(n, round(price * (1 + g) ** n)) for n in LT_YEARS],
        "target": round(target) if target else None,
        "years": years,
        "div5": round(div * 5) if div else None,
        "flat": (min(cands) <= 0),                    # 減益予想などで横ばい想定にした
    }


def _long_box(price: float, fund, on: bool) -> str:
    """長期見通しブロック。ONのときだけ表示（OFFでも hidden で埋めておきJSで切替）。"""
    o = _long_outlook(price, fund)
    if not o:
        return ('<div class="ltbox" data-ltbox hidden><div class="ltnote">'
                '財務データが未取得のため、長期の目安株価は表示できません。</div></div>')
    chips = "".join(f'<span class="ltc" data-lt-n="{n}">{n}年後 <b>¥{v:,}</b></span>'
                    for n, v in o["proj"])
    glabel = "横ばい想定" if o["flat"] else "+{:.1f}% 想定".format(o["g"])
    head = (f'<div class="lthd">📈 長期保有の目安'
            f'<span class="ltg">年 {glabel}</span></div>')
    notes = []
    if o["target"]:
        if o["years"]:
            yr = f' ・ 到達目安 約{o["years"]:.1f}年'
        elif o["target"] <= price:
            yr = ' ・ すでに到達'
        else:
            yr = ''
        notes.append(f'長期目標 ¥{o["target"]:,}（理論株価の中央値）'
                     f'<span data-lt-years>{yr}</span>')
    if o["div5"]:
        notes.append(f'配当 5年累計 ¥{o["div5"]:,}/株')
    note = f'<div class="ltnote">{" ／ ".join(notes)}</div>' if notes else ""
    hid = "" if on else " hidden"
    # data-lt-g / data-lt-target は app.js が最新株価で n年後を計算し直すために使う
    return (f'<div class="ltbox" data-ltbox data-lt-g="{o["g"]}" '
            f'data-lt-target="{o["target"] or ""}"{hid}>{head}'
            f'<div class="ltrow">{chips}</div>{note}'
            '<div class="ltnote2">※PER維持・年率一定で伸ばした単純計算です。予想や保証ではありません。</div>'
            '</div>')


def _holding_levels(h, a, cfg):
    from . import signals as S
    cur = a.price
    tgt, stp = h.get("target"), h.get("stop")
    if tgt is None or stp is None:
        at, as_ = S.holding_levels(h.get("buy") or cur, a.atr, cfg)
        tgt = at if tgt is None else tgt
        stp = as_ if stp is None else stp
    return tgt, stp


def _holding_card(h, a, cfg) -> str:
    code = h["code"]
    buy = h.get("buy")
    if a is None:
        lt_on = bool(h.get("long"))
        return (f'<div class="card" data-hold-long="{"1" if lt_on else "0"}">'
                '<div class="row1"><div class="title">'
                f'<span class="code">{_esc(code)}</span>'
                '<span class="name">データ取得待ち</span></div></div>'
                f'<div class="ltbar"><button type="button" class="ltbtn{" on" if lt_on else ""}" '
                f'data-lt="{_esc(code)}" aria-pressed="{"true" if lt_on else "false"}">'
                f'{"🌱 長期保有中" if lt_on else "☾ 長期保有"}</button>'
                f'<span class="ltmsg" data-ltmsg>{"利確通知OFF" if lt_on else ""}</span></div></div>')
    cur, name = a.price, a.name
    tgt, stp = _holding_levels(h, a, cfg)
    pl = ((cur - buy) / buy * 100) if buy else 0.0
    pl_cls = "pos" if pl >= 0 else "neg"
    if cur >= tgt:
        st_label, st_cls = "利確圏", "buy"
    elif cur <= stp:
        st_label, st_cls = "損切圏", "sell"
    else:
        st_label, st_cls = "保有中", "hold"
    buy_s = f"¥{buy:,.0f}" if buy else "—"
    fund = ""
    if a.fund:
        f = a.fund
        fc = []
        if a.combined is not None:
            fc.append(f'<span class="fchip cmb">複合 {a.combined:.0f}</span>')
        if f.get("per") is not None: fc.append(f'<span class="fchip">PER {f["per"]:.1f}</span>')
        if f.get("pbr") is not None: fc.append(f'<span class="fchip">PBR {f["pbr"]:.2f}</span>')
        if f.get("roe") is not None: fc.append(f'<span class="fchip">ROE {f["roe"]:.1f}%</span>')
        if f.get("divy") is not None: fc.append(f'<span class="fchip">利回り {f["divy"]:.1f}%</span>')
        if f.get("growth") is not None: fc.append(f'<span class="fchip">増益 {f["growth"]:+.0f}%</span>')
        if fc:
            fund = f'<div class="funds">{"".join(fc)}</div>'
    val = _val_block(cur, a.fund)
    sig_badge = _badge(a.signal)
    bt_html = ""
    if a.bt:
        b = a.bt
        items = [f'<span class="btchip win">利確勝率 {b["win_rate"]}%</span>']
        if b.get("days_tp"):
            items.append(f'<span class="btchip">利確まで ~{b["days_tp"]}日</span>')
        if b.get("days_sl"):
            items.append(f'<span class="btchip">損切まで ~{b["days_sl"]}日</span>')
        bt_html = f'<div class="bt">{"".join(items)}</div>'
    sell_warn = ""
    if a.signal == "SELL":
        sell_warn = '<div class="hsell">⚠ テクニカルは売りシグナル</div>'
    reasons = ""
    if a.reasons:
        chips = "".join(f'<span class="chip">{_esc(r)}</span>' for r in a.reasons[:3])
        reasons = f'<div class="reasons">{chips}</div>'
    # 長期保有トグル。ONなら利確通知OFF＋長期見通しを表示（実体は holdings.txt の「長期」）
    lt_on = bool(h.get("long"))
    lt_bar = (f'<div class="ltbar">'
              f'<button type="button" class="ltbtn{" on" if lt_on else ""}" '
              f'data-lt="{_esc(code)}" aria-pressed="{"true" if lt_on else "false"}">'
              f'{"🌱 長期保有中" if lt_on else "☾ 長期保有"}</button>'
              f'<span class="ltmsg" data-ltmsg>{"利確通知OFF" if lt_on else ""}</span></div>')
    lt_box = _long_box(cur, a.fund, lt_on)
    # data-hold-* は app.js が最新株価で損益%・状態を計算し直すために使う
    return (f'<div class="card" data-hold="{_esc(code)}" '
            f'data-hold-buy="{buy if buy else ""}" '
            f'data-hold-tgt="{tgt}" data-hold-stp="{stp}" '
            f'data-hold-long="{"1" if lt_on else "0"}"><div class="row1">'
            f'<div class="title"><span class="code">{_esc(code)}</span>'
            f'<span class="name">{_esc(name)}</span></div>'
            f'<span class="hstat {st_cls}" data-hold-st>{st_label}</span>{sig_badge}</div>'
            f'<div class="row2"><span class="price" data-px="{_esc(code)}">¥{cur:,.0f}</span>'
            f'<span class="score {pl_cls}" data-hold-pl>{pl:+.1f}%</span></div>'
            f'<div class="levels"><span class="lv">買値 {buy_s}</span>'
            f'<span class="lv tgt">利確 ¥{tgt:,.0f}</span>'
            f'<span class="lv stp">損切 ¥{stp:,.0f}</span></div>'
            f'{lt_bar}{lt_box}{bt_html}{fund}{val}{sell_warn}{reasons}</div>')


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
.seg{flex:none;font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;
  padding:1px 6px;border-radius:6px;border:1px solid var(--line);color:var(--mut)}
.seg.p{color:#6fa8ff;border-color:rgba(111,168,255,.4)}
.seg.g{color:var(--gold);border-color:var(--gold-d)}
.hstat{flex:none;font-size:12px;font-weight:700;padding:3px 11px;border-radius:8px;
  border:1px solid var(--line);color:var(--mut)}
.hstat.buy{color:var(--buy);border-color:rgba(70,196,106,.35)}
.hstat.sell{color:var(--sell);border-color:rgba(239,95,122,.35)}
.funds{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.fchip{font-size:11px;font-weight:700;color:var(--gold);background:rgba(212,175,99,.08);
  border:1px solid var(--gold-d);border-radius:7px;padding:2px 8px}
.fchip.cmb{color:#0c1118;background:var(--gold);border-color:var(--gold)}
.hsell{margin-top:8px;font-size:13px;font-weight:700;color:var(--sell);
  background:rgba(239,95,122,.10);border:1px solid rgba(239,95,122,.35);
  border-radius:9px;padding:7px 11px}
.bt{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.btchip{font-size:11px;font-weight:700;color:var(--mut);background:rgba(139,147,167,.10);
  border:1px solid var(--line);border-radius:7px;padding:2px 8px}
.btchip.win{color:var(--buy);border-color:rgba(70,196,106,.35)}
.val{margin-top:8px}
.tchip{display:inline-block;font-size:12px;font-weight:800;border-radius:8px;
  padding:3px 11px;border:1px solid var(--line);color:var(--mut)}
.tchip.und{color:var(--buy);background:rgba(70,196,106,.10);border-color:rgba(70,196,106,.35)}
.tchip.over{color:var(--sell);background:rgba(239,95,122,.10);border-color:rgba(239,95,122,.35)}
.cons{margin-top:8px}
.cchips{display:flex;flex-wrap:wrap;gap:6px}
.cchip{font-size:11px;font-weight:700;border-radius:7px;padding:2px 8px;
  border:1px solid var(--line);color:var(--mut)}
.cchip i{font-style:normal;font-weight:800;margin-left:5px}
.cchip.und{color:var(--buy);border-color:rgba(70,196,106,.40);background:rgba(70,196,106,.08)}
.cchip.over{color:var(--sell);border-color:rgba(239,95,122,.40);background:rgba(239,95,122,.08)}
.cchip.fair{color:var(--mut)}
.cverdict{margin-top:6px;font-size:12px;font-weight:800;color:var(--mut)}
.cverdict.buy{color:var(--buy)}
.ez{margin-top:8px;font-size:12px;font-weight:800;color:var(--fg);
  background:rgba(90,140,255,.10);border:1px solid rgba(90,140,255,.30);
  border-radius:9px;padding:6px 10px}
.ezn{margin-left:8px;font-size:11px;font-weight:700;color:var(--mut)}
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

/* --- 長期保有トグル & 長期見通し & GitHub連携パネル --- */
.ltbar{display:flex;align-items:center;gap:10px;margin-top:11px;flex-wrap:wrap}
.ltbtn{font-family:inherit;font-size:12px;font-weight:700;color:var(--mut);cursor:pointer;
  background:var(--bg);border:1px solid var(--line);border-radius:99px;padding:5px 13px}
.ltbtn.on{color:#0c1118;background:var(--gold);border-color:var(--gold)}
.ltbtn:disabled{opacity:.55}
.ltmsg{font-size:11px;color:var(--mut)}
.ltmsg.err{color:var(--sell)}
.ltbox{margin-top:9px;border:1px solid rgba(212,175,86,.30);background:rgba(212,175,86,.06);
  border-radius:10px;padding:9px 11px}
.lthd{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;font-size:12px;font-weight:800;color:var(--gold)}
.lthd .ltg{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;color:var(--mut)}
.ltrow{display:flex;flex-wrap:wrap;gap:8px;margin-top:7px}
.ltc{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--mut);
  border:1px solid var(--line);border-radius:7px;padding:3px 9px}
.ltc b{color:var(--ink);font-size:12.5px}
.ltnote{margin-top:7px;font-size:11.5px;color:var(--ink)}
.ltnote2{margin-top:5px;font-size:10.5px;color:var(--mut);line-height:1.6}
.ghgear{margin-left:auto;background:none;border:1px solid var(--line);color:var(--mut);
  border-radius:8px;padding:2px 9px;font-size:13px;cursor:pointer}
.ghpanel{margin-bottom:12px;border:1px solid var(--line);background:var(--bg2);
  border-radius:12px;padding:13px 14px}
.ghlead{font-size:12.5px;color:var(--ink)}
.ghsteps{margin:8px 0 10px 18px;font-size:11.5px;color:var(--mut);line-height:1.8}
.ghpanel input{width:100%;margin-top:6px;font-family:'IBM Plex Mono',monospace;font-size:16px;
  color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:10px;
  padding:10px 12px;outline:none}
.ghpanel input:focus{border-color:var(--gold-d)}
.ghrow{display:flex;gap:8px}
.ghrow input{flex:1;min-width:0;font-size:14px}
.ghbtns{display:flex;align-items:center;gap:9px;margin-top:10px;flex-wrap:wrap}
.ghbtns button{font-family:inherit;font-size:13px;font-weight:700;cursor:pointer;
  border-radius:10px;padding:8px 16px;border:1px solid var(--gold-d);
  background:rgba(212,175,86,.12);color:var(--gold)}
.ghbtns #ghdel{border-color:var(--line);background:var(--bg);color:var(--mut)}
.ghstat{font-size:11.5px;color:var(--mut)}
.ghstat.err{color:var(--sell)} .ghstat.ok{color:var(--buy)}
.ghnote{margin-top:9px;font-size:10.5px;color:var(--mut);line-height:1.7}

/* --- app.js 追加分（クラス追加のみ・既存は不変） --- */
.star{margin-left:8px;background:none;border:none;font-size:18px;line-height:1;
  cursor:pointer;color:var(--mut);padding:0 2px}
.star.on{color:#f5c518}
.rm{margin-left:6px;background:none;border:1px solid var(--line);color:var(--mut);
  border-radius:7px;font-size:13px;line-height:1;padding:2px 7px;cursor:pointer}
.ez.hit{background:rgba(70,196,106,.16);border-color:rgba(70,196,106,.55);color:var(--fg)}
.ez.hit b{color:var(--buy)}
#hitcount{color:var(--mut);font-size:12px;margin:2px 2px 8px}
.refresh{margin-left:6px;background:none;border:1px solid var(--line);color:var(--fg);
  border-radius:8px;padding:2px 9px;cursor:pointer;font-size:12px;font-weight:700}
.refresh:disabled{opacity:.5}
.sec-tenbagger{margin-top:22px}
.tb-card{border-color:rgba(212,175,86,.28)}
.tb-score{margin-left:auto;font-family:var(--mono);font-size:20px;font-weight:600;color:var(--gold)}
.tb-score i{font-size:11px;color:var(--mut);font-style:normal;margin-left:1px}
.tb-meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;font-family:var(--mono);font-size:11px;color:var(--mut)}
.tb-meta .tb-mcap{color:var(--ink)}
.tb-bar{position:relative;height:7px;border-radius:99px;background:rgba(255,255,255,.06);margin-top:9px;overflow:hidden}
.tb-bar span{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,var(--gold-d),var(--gold));border-radius:99px}
.tb-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.tb-tag{font-family:var(--mono);font-size:10.5px;padding:3px 8px;border-radius:99px;border:1px solid var(--line)}
.tb-tag.t100{color:var(--gold);border-color:rgba(212,175,86,.5);background:rgba(212,175,86,.08)}
.tb-tag.t10{color:var(--ink);border-color:rgba(212,175,86,.35)}
.tb-tag.tbuy{color:var(--buy);border-color:rgba(70,196,106,.4);background:rgba(70,196,106,.08)}
.tb-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tb-chips .tb-chip{font-family:var(--mono);font-size:10px;color:var(--mut);padding:2px 7px;border:1px solid var(--line);border-radius:99px}
.tb-foot{margin-top:12px;font-size:10.5px;line-height:1.7;color:var(--mut)}
.tb-foot .tb-note2{color:var(--hold)}
"""

APP_JS = r"""
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
"""


# ─────────────────────────────────────────────────────────────
#  🚀 テンバガー候補レーダー（近似設計）
#  ※ J-Quants無料枠(/fins/summary)は 売上高・営業利益・発行済株式数・業種 を返さない。
#    そのため取得可能な 純利益(FNP/NP)・EPS・純資産(Eq) で指示書の意図を近似する:
#      ・時価総額 ≈ 株価 × (純利益 / EPS)   … 発行済株式数=純利益/EPSで近似
#      ・売上高成長率 → 純利益成長率（2期）で代替
#      ・営業利益率 → ROE(純利益/純資産)で代替
#      ・増収継続 → 増益継続で代替 ・ 流動性 → 20日平均売買代金（日足から算出）
#      ・17業種ボーナスは業種データが無いため対象外（脚注に明記）
# ─────────────────────────────────────────────────────────────
TENBAGGER_CACHE = DOCS / "tenbagger_cache.json"


def _tb_load_cache() -> dict:
    try:
        if TENBAGGER_CACHE.exists():
            return json.loads(TENBAGGER_CACHE.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _tb_turnover20(df) -> float | None:
    """日足から直近20日平均売買代金（円）＝ Close×Volume の平均。"""
    try:
        if df is None or "Close" not in df or "Volume" not in df:
            return None
        c = df["Close"].astype(float)
        v = df["Volume"].astype(float)
        tv = (c * v).dropna().tail(20)
        if tv.empty:
            return None
        return float(tv.mean())
    except Exception:
        return None


def _tb_score(price: float, raw: dict, turnover20: float | None):
    """近似スコア(100点満点)。対象外は None。返り値: dict(score, mcap_oku, parts, growth, roe)。"""
    if not raw or price is None or price <= 0:
        return None
    eps = raw.get("eps_fore") or raw.get("eps_fy")
    profit = raw.get("profit_fore")
    if profit is None:
        profit = raw.get("profit_fy")
    # 発行済株式数 ≈ 純利益 / EPS（同期）。EPS/純利益が無い＝時価総額を近似できず対象外
    if not eps or eps <= 0 or profit is None:
        return None
    shares = profit / eps
    if shares <= 0:
        return None
    mcap_oku = price * shares / 1e8  # 億円

    # ① 時価総額(30点)：300億超は候補除外。100億未満=30／100〜300億=反比例で15〜25
    if mcap_oku > 300:
        return None
    if mcap_oku < 100:
        s_mcap = 30.0
    else:
        s_mcap = 25.0 - (mcap_oku - 100.0) / 200.0 * 10.0  # 100億→25 ・ 300億→15

    # ② 純利益成長率(30点・売上高成長率の代替)：直近予想 vs 前期／前期 vs 前々期の2期で判定
    pf_fore, pf_fy, pf_prev = raw.get("profit_fore"), raw.get("profit_fy"), raw.get("prev_profit_fy")
    g1 = ((pf_fore - pf_fy) / abs(pf_fy) * 100.0) if (pf_fore is not None and pf_fy not in (None, 0)) else None
    g2 = ((pf_fy - pf_prev) / abs(pf_prev) * 100.0) if (pf_fy is not None and pf_prev not in (None, 0)) else None
    if g1 is None:
        return None  # 成長不明は対象外
    if g1 >= 20 and (g2 is not None and g2 >= 20):
        s_growth = 30.0  # 2期連続+20%以上
    elif g1 >= 20:
        s_growth = 20.0
    elif g1 >= 10:
        s_growth = 10.0
    else:
        return None  # 直近+10%未満は候補除外

    # ③ ROE(20点・営業利益率の代替)：15%↑=20／8〜15%=12／黒字〜8%=6／赤字は高成長(+30%超)なら6・他は除外
    eq = raw.get("equity")
    roe = (profit / eq * 100.0) if (eq and eq > 0) else None
    if roe is None:
        s_prof = 6.0 if profit > 0 else (6.0 if g1 > 30 else None)
    elif roe >= 15:
        s_prof = 20.0
    elif roe >= 8:
        s_prof = 12.0
    elif profit > 0:
        s_prof = 6.0  # 黒字〜8%
    else:
        s_prof = 6.0 if g1 > 30 else None  # 営業赤字は高成長なら6
    if s_prof is None:
        return None

    # ④ 増益継続(10点・増収継続の代替)：増益連続期数×3（上限10）
    streak = 0
    if g2 is not None and g2 > 0:
        streak += 1
    if g1 > 0:
        streak += 1
    s_cont = min(10.0, streak * 3.0)

    # ⑤ 流動性(10点)：20日平均売買代金 3,000万〜30億=10／低すぎ・大きすぎ=各5／不明=5
    if turnover20 is None:
        s_liq = 5.0
    elif 3.0e7 <= turnover20 <= 3.0e9:
        s_liq = 10.0
    else:
        s_liq = 5.0

    # ※ 17業種ボーナス(+5)は業種データが無いため対象外
    total = min(100.0, s_mcap + s_growth + s_prof + s_cont + s_liq)
    return {
        "score": round(total),
        "mcap_oku": round(mcap_oku),
        "growth": round(g1, 1) if g1 is not None else None,
        "roe": round(roe, 1) if roe is not None else None,
        "parts": {"mcap": round(s_mcap), "growth": round(s_growth),
                  "prof": round(s_prof), "cont": round(s_cont), "liq": round(s_liq)},
    }


def build_tenbagger(analyses: list, cfg: dict, buy_codes: set) -> tuple[str, list]:
    """テンバガー候補レーダー TOP10 を生成。返り値: (section_html, index_rows)。
    既存出力・スコア計算・判定には非干渉（report.py内の追加のみ）。"""
    tcfg = (cfg.get("tenbagger") or {})
    if not tcfg.get("enabled", True):
        return "", []
    fetch_cap = int(tcfg.get("fetch_cap", 12))       # 1回あたりの財務API新規取得の上限（+3分以内に抑える）
    cache_days = int(tcfg.get("cache_days", 7))
    amap = {a.code: a for a in analyses}
    today = datetime.now(JST).strftime("%Y-%m-%d")

    cache = _tb_load_cache()
    # 7日以内キャッシュを有効とし、期限切れ／未取得のみ新規取得（上限fetch_cap）
    fresh, need = {}, []
    for a in analyses:
        e = cache.get(a.code)
        ok = False
        if e and e.get("fetched"):
            try:
                d0 = datetime.strptime(e["fetched"], "%Y-%m-%d")
                if (datetime.now() - d0).days < cache_days and e.get("raw") is not None:
                    fresh[a.code] = e["raw"]
                    ok = True
            except Exception:
                ok = False
        if not ok:
            need.append(a.code)

    # 新規財務取得（無料枠5/分・既定13秒間隔。APIエラー銘柄はスキップしログ）
    key = None
    try:
        from . import jquants as JQ
        key = JQ.get_api_key()
    except Exception as e:  # noqa
        print(f"[tenbagger] jquants未使用: {e}")
    if key and need:
        pick = need[:max(0, fetch_cap)]
        try:
            from . import jquants as JQ
            raw_new = JQ.fundamentals_for(pick, key, float(tcfg.get("request_sleep", 13.0)))
        except Exception as e:  # noqa
            print(f"[tenbagger] 財務取得失敗（キャッシュ分のみ継続）: {e}")
            raw_new = {}
        for c in pick:
            r = raw_new.get(c)
            cache[c] = {"fetched": today, "raw": r}  # 失敗はraw=Noneでキャッシュ（連日リトライ回避）
            if r is not None:
                fresh[c] = r
    _tb_save_cache(cache)

    # 300億以下の候補のみ日足で売買代金を算出（財務APIは使わない）
    prelim = [c for c in fresh if c in amap]
    turns: dict = {}
    if prelim:
        try:
            frames = R.D.fetch_many(prelim)
        except Exception as e:  # noqa
            print(f"[tenbagger] 日足取得失敗: {e}")
            frames = {}
        for c in prelim:
            turns[c] = _tb_turnover20(frames.get(c))

    scored = []
    for c in prelim:
        a = amap.get(c)
        if a is None:
            continue
        sc = _tb_score(a.price, fresh.get(c), turns.get(c))
        if sc is None:
            continue
        scored.append((a, sc))
    scored.sort(key=lambda x: x[1]["score"], reverse=True)
    top = scored[:10]

    print(f"[tenbagger] 財務キャッシュ {len(fresh)} ・ 候補 {len(scored)} ・ 表示 {len(top)}")

    if not top:
        return "", []

    cards = "".join(_tb_card(i, a, sc, (a.code in buy_codes)) for i, (a, sc) in enumerate(top, 1))
    foot = (
        '<p class="tb-foot">※テンバガーの共通特徴への適合度であり、株価上昇の予想・保証ではありません。'
        '超小型株は流動性が低く、値動きが極端になりやすいハイリスク領域です。'
        '株主構成・事業内容は必ずご自身でご確認ください。投資判断は自己責任です。'
        '<br><span class="tb-note2">（データ制約により 売上高→純利益成長率、営業利益率→ROE、'
        '発行済株式数→純利益/EPS で近似。17業種ボーナス・株主構成はJ-Quants無料枠で取得不可のため対象外です。）</span></p>'
    )
    section = (
        '<section class="sec-tenbagger">'
        '<h2 class="find"><span>🚀 テンバガー候補レーダー TOP10</span><em>TENBAGGER RADAR</em></h2>'
        f'<div class="cards">{cards}</div>{foot}</section>'
    )
    index_rows = []
    for a, sc in top:
        index_rows.append({
            "c": _esc(a.code), "n": _esc(a.name), "g": a.signal,
            "sc": round(a.score), "p": round(a.price),
            "t": round(a.target) if a.target else None,
            "st": round(a.stop) if a.stop else None,
            "rr": a.rr, "r": [_esc(x) for x in (a.reasons or [])[:3]],
            "rk": 0, "m": "", "k": _search_key(a.name, a.code),
        })
    return section, index_rows


def _tb_save_cache(cache: dict) -> None:
    try:
        DOCS.mkdir(exist_ok=True)
        TENBAGGER_CACHE.write_text(json.dumps(cache, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception as e:  # noqa
        print(f"[tenbagger] cache保存失敗: {e}")


def _tb_card(rank: int, a, sc: dict, is_buy: bool) -> str:
    p = sc["parts"]
    tag = ""
    if sc["score"] >= 85:
        tag = '<span class="tb-tag t100">💎 100倍級の特徴</span>'
    elif sc["score"] >= 70:
        tag = '<span class="tb-tag t10">🚀 10倍級の特徴</span>'
    buy_badge = '<span class="tb-tag tbuy">⭐ テクニカルも買い</span>' if is_buy else ""
    growth = f'<span class="tb-chip">増益 {sc["growth"]:+.0f}%</span>' if sc.get("growth") is not None else ""
    roe = f'<span class="tb-chip">ROE {sc["roe"]:.1f}%</span>' if sc.get("roe") is not None else ""
    chips = (
        f'<span class="tb-chip">時価総額 {p["mcap"]}</span>'
        f'<span class="tb-chip">成長 {p["growth"]}</span>'
        f'<span class="tb-chip">利益性 {p["prof"]}</span>'
        f'<span class="tb-chip">継続 {p["cont"]}</span>'
        f'<span class="tb-chip">流動性 {p["liq"]}</span>'
    )
    pct = max(0, min(100, sc["score"]))
    return (
        f'<div class="card tb-card" style="animation-delay:{rank*0.05:.2f}s">'
        f'<div class="row1"><span class="rank">{rank}</span>'
        f'<div class="title"><span class="code">{_esc(a.code)}</span>'
        f'<span class="name">{_esc(a.name)}</span>{_seg("")}</div>'
        f'<span class="tb-score">{sc["score"]}<i>点</i></span></div>'
        f'<div class="tb-meta"><span class="tb-mcap">時価総額 ~{sc["mcap_oku"]}億円</span>'
        f'<span class="tb-gr">売上(≈利益)成長 {sc["growth"]:+.0f}%</span>'
        + (f'<span class="tb-roe">営業利益率(≈ROE) {sc["roe"]:.1f}%</span>' if sc.get("roe") is not None else "")
        + '</div>'
        f'<div class="tb-bar"><span style="width:{pct}%"></span></div>'
        f'<div class="tb-tags">{tag}{buy_badge}</div>'
        f'<div class="tb-chips">{chips}</div></div>'
    )


def build_html(cfg: dict) -> tuple[str, dict]:
    now = datetime.now(JST)
    date_str = now.strftime("%Y.%m.%d %H:%M")
    top = int(cfg.get("dashboard_top", 10))

    analyses = R.analyze_universe(cfg)
    total = len(analyses)
    holds = load_holdings()
    analyses = R.apply_fundamentals(analyses, cfg,
                                    extra_codes=[h["code"] for h in holds])
    buys = analyses[:top]
    R.attach_barrier_stats(buys, cfg)

    # 🚀 テンバガー候補レーダー（買い候補TOP10の下に新設・既存出力には非干渉）
    buy_codes = {b.code for b in buys}
    tenbagger_section, _tb_index = build_tenbagger(analyses, cfg, buy_codes)

    mk = market_map(cfg)
    buy_sub = "TECH × FUNDAMENTAL" if any(b.combined is not None for b in buys) else "BUY SIGNALS"
    buy_cards = "".join(_card(i, a, True, mk.get(a.code, "")) for i, a in enumerate(buys, 1))

    amap = {a.code: a for a in analyses}
    hold_section = ""
    if holds:
        # 保有株の「利確勝率・想定保有日数」を日足から試算
        try:
            hframes = R.D.fetch_many([h["code"] for h in holds])
        except Exception:
            hframes = {}
        for h in holds:
            a = amap.get(h["code"])
            if a is None:
                continue
            tgt, stp = _holding_levels(h, a, cfg)
            a.bt = R.S.barrier_stats(hframes.get(h["code"]), a.price, tgt, stp)
        hc = "".join(_holding_card(h, amap.get(h["code"]), cfg) for h in holds)
        hold_section = _section("保有銘柄", "MY HOLDINGS", hc, "watch",
                                extra=GH_GEAR, head_extra=GH_PANEL)

    index = []
    for rank, a in enumerate(analyses, 1):
        index.append({
            "c": _esc(a.code), "n": _esc(a.name), "g": a.signal,
            "sc": round(a.score), "p": round(a.price),
            "t": round(a.target) if a.target else None,
            "st": round(a.stop) if a.stop else None,
            "rr": a.rr, "r": [_esc(x) for x in (a.reasons or [])[:3]],
            "rk": rank, "m": mk.get(a.code, ""),
            "k": _search_key(a.name, a.code),
        })
    data = {
        "generated": date_str, "total": total,
        "buys": [vars(a) for a in buys],
        "stocks": index,
    }

    head = (
        '<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<title>株オラクル — Kabu Oracle</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800'
        '&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=IBM+Plex+Mono:wght@500;600'
        '&display=swap" rel="stylesheet">'
        '<link rel="manifest" href="manifest.json">'
        '<meta name="theme-color" content="#0c0e13">'
        '<meta name="mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
        '<meta name="apple-mobile-web-app-title" content="株オラクル">'
        '<link rel="apple-touch-icon" href="apple-touch-icon.png">'
        '<style>' + CSS + '</style></head>'
    )

    body = f'''<body data-total="{total}"><div class="wrap">
  <header>
    <div class="brand"><h1>株オラクル</h1><span class="en">Kabu Oracle</span></div>
    <div class="meta"><span>更新 <b>{date_str}</b> JST</span><span>分析 <b>{total}</b> 銘柄</span><span id="pxasof"></span></div>
  </header>

  <section id="search-sec">
    <h2 class="find"><span>銘柄サーチ</span><em>CODE SEARCH</em></h2>
    <input id="q" type="search" inputmode="text" autocomplete="off"
           placeholder="証券コード や 銘柄名（例: 7203 / トヨタ）">
    <div id="results" class="cards"></div>
    <p id="hint" class="empty">コードや銘柄名を入れると買い/売り判定・利確/損切・総合順位を表示します（上位8件）。</p>
  </section>

  {hold_section}

  {_section("買い候補 TOP10", buy_sub, buy_cards, "buy")}

  {tenbagger_section}

  <footer>
    <b>免責</b>：本ページは自分用の分析補助であり投資助言ではありません。
    株価は約15〜20分遅延（yfinance）。シグナルは確率的で利益を保証しません。
    投資判断はご自身の責任で行ってください。<br>Generated by Kabu Oracle on GitHub Actions.
  </footer>
</div>'''

    ver = now.strftime("%Y%m%d%H%M")
    script = f'<script src="app.js?v={ver}" defer></script>'
    page = head + body + script + "</body></html>"
    return page, data


def write_dashboard(cfg: dict) -> Path:
    DOCS.mkdir(exist_ok=True)
    page, data = build_html(cfg)
    stocks = data.pop("stocks", [])
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    (DOCS / "stocks.json").write_text(
        json.dumps(stocks, ensure_ascii=False, default=str), encoding="utf-8")
    (DOCS / "app.js").write_text(APP_JS, encoding="utf-8")
    (DOCS / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    manifest = {
        "name": "株オラクル", "short_name": "株オラクル",
        "start_url": "./", "scope": "./", "display": "standalone",
        "background_color": "#0c0e13", "theme_color": "#0c0e13",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (DOCS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ダッシュボード生成: {DOCS/'index.html'}")
    return DOCS / "index.html"


def write_prices(cfg: dict) -> dict:
    """表示中の買い/売りTOP・保有銘柄・監視銘柄の最新株価を docs/prices.json に書く。"""
    from . import data as D
    DOCS.mkdir(exist_ok=True)
    codes: set[str] = {str(c).strip() for c in (cfg.get("watchlist") or [])}
    # 保有銘柄はダッシュボードに常時表示されるので必ず対象に含める
    # （data.json の買い候補に入らない銘柄は、ここで足さないと価格が更新されない）
    holds = load_holdings()
    codes.update(str(h["code"]).strip() for h in holds if h.get("code"))
    # 長期保有マークも載せる。ダッシュボード生成(1日4回)を待たずに
    # ボタンの状態が holdings.txt と合うようにするため。
    longs = [str(h["code"]).strip() for h in holds if h.get("long")]
    dj = DOCS / "data.json"
    if dj.exists():
        try:
            d = json.loads(dj.read_text(encoding="utf-8"))
            for key in ("buys", "sells"):
                for a in d.get(key, []):
                    if a.get("code"):
                        codes.add(str(a["code"]))
        except Exception:
            pass
    prices = D.fetch_last_prices(sorted(codes))
    now = datetime.now(JST).strftime("%H:%M")
    out = {"asof": now, "px": {k: round(v) for k, v in prices.items()}, "long": longs}
    (DOCS / "prices.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"価格更新: {len(prices)} 件 @ {now} JST")
    return out


def check_holdings(cfg: dict) -> None:
    """holdings.txt の各銘柄を監視し、利確/損切ラインに到達したらLINE/メール通知。

    同じ到達は1日1回だけ通知（data/holdings_state.json で管理）。約15〜20分遅延。
    """
    from . import data as D
    from . import signals as S
    from . import notify as N
    from .config import load_holdings, load_universe

    holds = load_holdings()
    if not holds:
        print("保有銘柄なし（holdings.txt）")
        return

    codes = [h["code"] for h in holds]
    px = D.fetch_last_prices(codes)            # 現在値（日中足・約20分遅延）
    frames = D.fetch_many(codes)               # ATR・シグナル用の日足
    bench_df = D.fetch_one(cfg.get("benchmark", "^N225"))
    bench = bench_df["Close"] if bench_df is not None else None
    namemap = {c: n for c, n in load_universe(
        {"universe_file": cfg.get("universe_file", "data/universe_all.csv"), "markets": "all"})}

    state_path = ROOT / "data" / "holdings_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    today = datetime.now(JST).strftime("%Y-%m-%d")

    tp, sl, sg = [], [], []
    for h in holds:
        c = h["code"]
        buy = h.get("buy")
        cur = px.get(c)
        if cur is None:
            continue
        name = namemap.get(c, "")
        df = frames.get(c)
        atr = float(S.ind.atr(df, 14).iloc[-1]) if (df is not None and len(df) > 20) else 0.0
        tgt, stp = h.get("target"), h.get("stop")
        if (tgt is None or stp is None) and atr > 0:
            at, as_ = S.holding_levels(buy or cur, atr, cfg)
            tgt = at if tgt is None else tgt
            stp = as_ if stp is None else stp
        # ATR が出せない（日足の取得失敗など）場合は自動ラインを作らない。
        # 作ると 利確=損切=買値 になり、到達アラートが誤発報するため。
        pl = ((cur - buy) / buy * 100) if buy else 0.0
        # 長期保有マークが付いている銘柄は利確通知を出さない（損切・売りシグナルは出す）
        long_hold = bool(h.get("long"))
        if tgt and not long_hold and cur >= tgt and state.get(f"{c}:tp") != today:
            tp.append(f"  {c} {name}  現在¥{cur:,.0f} / 買値¥{(buy or 0):,.0f} ({pl:+.1f}%)  利確¥{tgt:,.0f}")
            state[f"{c}:tp"] = today
        if stp and cur <= stp and state.get(f"{c}:sl") != today:
            sl.append(f"  {c} {name}  現在¥{cur:,.0f} / 買値¥{(buy or 0):,.0f} ({pl:+.1f}%)  損切¥{stp:,.0f}")
            state[f"{c}:sl"] = today
        # テクニカルの売りシグナル転換（価格ラインとは別の早期サイン）
        if df is not None and len(df) > 80:
            an = S.analyze(df, c, name, bench=bench, cfg=cfg)
            if an.error is None and an.signal == "SELL" and state.get(f"{c}:sg") != today:
                reason = an.reasons[0] if an.reasons else "下降サイン"
                sg.append(f"  {c} {name}  現在¥{cur:,.0f} ({pl:+.1f}%)  {reason}")
                state[f"{c}:sg"] = today

    if tp or sl or sg:
        now = datetime.now(JST).strftime("%H:%M")
        parts = [f"🔔 株オラクル｜保有アラート（{now} JST・約20分遅延）"]
        if tp:
            parts.append("✅ 利確の目安に到達")
            parts += tp
        if sl:
            parts.append("🛑 損切の目安に到達")
            parts += sl
        if sg:
            parts.append("⚠ 売りシグナルに転換（テクニカル）")
            parts += sg
        parts.append("※自分用の目安です。最終判断はご自身で。")
        msg = "\n".join(parts)
        print(msg)
        N.notify_all(cfg, "【株オラクル】保有アラート", msg)
    else:
        print("到達アラートなし")

    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
