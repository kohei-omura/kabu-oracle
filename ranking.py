"""ユニバースをスコアリングし、買い/売り Top-N を算出する。"""
from __future__ import annotations
import data as D
import signals as S
from config import load_universe


def analyze_universe(cfg: dict) -> list[S.Analysis]:
    """ユニバース全銘柄を分析し、スコア降順の Analysis リストを返す。"""
    universe = load_universe(cfg)
    bench_code = cfg.get("benchmark", "^N225")

    codes = [c for c, _ in universe]
    names = {c: n for c, n in universe}

    print(f"ユニバース {len(codes)} 銘柄を取得中...")
    frames = D.fetch_many(codes)
    bench_df = D.fetch_one(bench_code)
    bench = bench_df["Close"] if bench_df is not None else None

    analyses: list[S.Analysis] = []
    for c in codes:
        df = frames.get(c)
        if df is None:
            continue
        a = S.analyze(df, c, names.get(c, ""), bench=bench, cfg=cfg)
        if a.error is None:
            analyses.append(a)

    analyses.sort(key=lambda x: x.score, reverse=True)
    return analyses


def build_rankings(cfg: dict):
    """買い Top-N（既定10・Web同等）と分析総数を返す（通知用）。

    売り/警戒は既定で通知しない。出したい場合は config に notify_sells: true。
    """
    top = int(cfg.get("buy_top", cfg.get("dashboard_top", 10)))
    analyses = analyze_universe(cfg)
    analyses = apply_fundamentals(analyses, cfg)
    buys = analyses[:top]
    attach_barrier_stats(buys, cfg)
    if cfg.get("notify_sells", False):
        sells = sorted(analyses, key=lambda x: x.score)[:int(cfg.get("top_n", 5))]
    else:
        sells = []
    return buys, sells, len(analyses)


def attach_barrier_stats(items: list, cfg: dict) -> None:
    """各銘柄に利確勝率・想定保有日数（バリア試算）を付与。現在値→各自の利確/損切で判定。"""
    targets = [a for a in items if a.target and a.stop]
    if not targets:
        return
    try:
        frames = D.fetch_many([a.code for a in targets])
    except Exception:
        frames = {}
    for a in targets:
        df = frames.get(a.code)
        a.bt = S.barrier_stats(df, a.price, a.target, a.stop)
        a.ez = S.entry_zone(df, a.price, a.atr, a.stop)


# ---------- テクニカル × ファンダ 複合ランキング ----------

def _rank_norm(values: dict, higher_better: bool = True) -> dict:
    """{code: 値} を 0〜1 に順位正規化（1=最良）。値Noneは対象外。"""
    items = [(c, v) for c, v in values.items() if v is not None]
    if len(items) <= 1:
        return {c: 0.5 for c, _ in items}
    items.sort(key=lambda x: x[1])
    n = len(items)
    out = {}
    for rank, (c, _) in enumerate(items):
        p = rank / (n - 1)              # 低い値→0, 高い値→1
        out[c] = p if higher_better else (1 - p)
    return out


def _pct(v, values, higher_better: bool = True) -> float | None:
    """value が候補群 values の中でどの位置か（0〜1, 1=最良）。値Noneは対象外。"""
    vals = [x for x in values if x is not None]
    if v is None or not vals:
        return None
    below = sum(1 for x in vals if x < v) / len(vals)  # v より下にある割合
    return below if higher_better else (1 - below)


def _metrics(price: float, raw: dict, profit_years: float = 10.0,
             growth_years: float = 5.0, ref_per: float = 15.0,
             r: float = 0.08, band: float = 0.05) -> dict:
    """生財務値＋現在値から各指標＋理論株価＋3方式の割安コンセンサスを算出。

    理論株価(株マップ/ZAi式)：資産価値(BPS)＋利益価値(予想EPS×profit_years)
                              ＋成長価値(予想EPS×増益率×growth_years)
    桐谷方式コンセンサス：下記3方式の理論値と現在値を比べ、band(5%)超で割安/割高を判定。
      ①株マップ式  ②PER基準(予想EPS×ref_per)  ③ROE基準(BPS×ROE÷r)
      2方式以上で割安なら「購入検討」フラグ。
    """
    per = pbr = roe = eqr = divy = growth = None
    eps = raw.get("eps_fore") or raw.get("eps_fy")
    if eps and eps > 0 and price > 0:
        per = round(price / eps, 1)
    bps = raw.get("bps")
    if bps and bps > 0 and price > 0:
        pbr = round(price / bps, 2)
    eq = raw.get("equity")
    pf = raw.get("profit_fore") or raw.get("profit_fy")
    if eq and eq > 0 and pf is not None:
        roe = round(pf / eq * 100, 1)
    if raw.get("equity_ratio") is not None:
        eqr = round(raw["equity_ratio"] * 100, 1)
    dv = raw.get("div_fore") or raw.get("div_result")
    if dv is not None and price > 0:
        divy = round(dv / price * 100, 2)
    pfo, pfy = raw.get("profit_fore"), raw.get("profit_fy")
    if pfo is not None and pfy not in (None, 0):
        growth = round((pfo - pfy) / abs(pfy) * 100, 1)
    # 理論株価 ＝ 資産価値 ＋ 利益価値 ＋ 成長価値（株マップ/ZAi式）
    theo = None
    asset_val = bps if (bps and bps > 0) else 0.0
    if eps and eps > 0:
        profit_val = eps * profit_years
        g = 0.0
        if pfo is not None and pfy not in (None, 0) and pfy > 0:
            g = max(0.0, min((pfo - pfy) / pfy, 0.30))   # 増益率を成長率の代理に（0〜30%）
        growth_val = eps * g * growth_years
        theo = round(asset_val + profit_val + growth_val)
    elif asset_val > 0:
        theo = round(asset_val)   # 赤字等でEPS無 → 資産価値のみ
    # 桐谷方式：3つの評価方式で割安/割高を判定し、2方式以上の割安で購入検討
    fair_per_v = round(eps * ref_per) if (eps and eps > 0) else None
    fair_roe_v = (round(bps * min(roe / 100 / r, 10.0))
                  if (bps and bps > 0 and roe is not None and roe > 0 and r > 0) else None)
    methods = {"株マップ": theo, "PER": fair_per_v, "ROE": fair_roe_v}
    judg = {}
    und = avail = 0
    for k, F in methods.items():
        if F and F > 0 and price > 0:
            gap = price / F - 1.0
            lab = "u" if gap <= -band else ("o" if gap >= band else "f")
            judg[k] = {"fair": F, "lab": lab, "gap": round(gap * 100)}
            avail += 1
            if lab == "u":
                und += 1
    cons = {"judg": judg, "und": und, "avail": avail, "buy": (und >= 2)}
    return {"per": per, "pbr": pbr, "roe": roe, "eqr": eqr, "divy": divy,
            "growth": growth, "theo": theo, "cons": cons}


def apply_fundamentals(analyses: list, cfg: dict, extra_codes=None) -> list:
    """テクニカル上位にJ-Quants財務を付与し、複合スコアで再ランキング。

    extra_codes（保有銘柄など）も財務取得の対象に含め、表示用に fund を付与する。
    認証情報なし／API失敗／無効時は何もせず元のリストを返す（テクニカルのみ）。
    """
    fc = (cfg.get("fundamentals") or {})
    if not fc.get("enabled", False) or not analyses:
        return analyses
    try:
        import jquants as JQ
        key = JQ.get_api_key()
        if not key:
            return analyses

        top = int(fc.get("screen_top", 15))
        w_tech = float(fc.get("weight_tech", 0.6))
        w_fund = float(fc.get("weight_fund", 0.4))
        mw = {"per": 0.25, "pbr": 0.15, "roe": 0.25, "eqr": 0.10,
              "divy": 0.10, "growth": 0.15}
        mw.update(fc.get("metric_weights") or {})
        p_years = float(fc.get("theo_profit_years", 10.0))
        g_years = float(fc.get("theo_growth_years", 5.0))
        ref_per = float(fc.get("fair_per", 15.0))
        fair_r = float(fc.get("fair_return", 0.08))

        cands = analyses[:top]
        extra = [c for c in (extra_codes or []) if c]
        fetch_codes = list(dict.fromkeys([a.code for a in cands] + extra))
        raw = JQ.fundamentals_for(fetch_codes, key,
                                  float(fc.get("request_sleep", 13.0)))
        if not raw:
            print("[JQ] 財務取得0件 → テクニカルのみ")
            return analyses

        amap = {a.code: a for a in analyses}

        # 各指標を算出（買い候補）
        met = {a.code: _metrics(a.price, raw[a.code], p_years, g_years, ref_per, fair_r)
               for a in cands if a.code in raw}
        keys = ["per", "pbr", "roe", "eqr", "divy", "growth"]
        lower = {"per", "pbr"}
        norms = {k: _rank_norm({c: m[k] for c, m in met.items()},
                               higher_better=(k not in lower)) for k in keys}

        def _fscore(c):
            num = den = 0.0
            for k in keys:
                if c in norms[k]:
                    num += mw[k] * norms[k][c]
                    den += mw[k]
            return (100 * num / den) if den > 0 else None

        # テクニカルを候補内で min-max 正規化
        scs = [a.score for a in cands]
        tmin, tmax = min(scs), max(scs)

        def _tnorm(score):
            t = (score - tmin) / (tmax - tmin) if tmax > tmin else 0.5
            return max(0.0, min(1.0, t))

        def _combined(score, fs):
            fnorm = (fs / 100) if fs is not None else 0.5
            return round(100 * (w_tech * _tnorm(score) + w_fund * fnorm) / (w_tech + w_fund), 1)

        for a in cands:
            fs = _fscore(a.code)
            a.combined = _combined(a.score, fs)
            if a.code in met:
                a.fund = dict(met[a.code], score=(round(fs, 0) if fs is not None else None))

        # 保有銘柄など（候補外）：買い候補の分布に対する相対評価で複合スコアを付与
        cand_vals = {k: [m[k] for m in met.values() if m[k] is not None] for k in keys}
        for c in [x for x in (extra_codes or []) if x]:
            a = amap.get(c)
            if a is None or c not in raw or a.fund is not None:
                continue
            m = _metrics(a.price, raw[c], p_years, g_years, ref_per, fair_r)
            num = den = 0.0
            for k in keys:
                p = _pct(m[k], cand_vals[k], higher_better=(k not in lower))
                if p is not None:
                    num += mw[k] * p
                    den += mw[k]
            fs = (100 * num / den) if den > 0 else None
            a.combined = _combined(a.score, fs)
            a.fund = dict(m, score=(round(fs, 0) if fs is not None else None))

        cands.sort(key=lambda x: (x.combined if x.combined is not None else -1), reverse=True)
        n_theo = sum(1 for a in cands if a.fund and a.fund.get("theo"))
        print(f"[JQ] 財務 {len(raw)} 銘柄取得（候補{len(met)}＋保有等）・"
              f"複合スコアで再ランキング・理論株価 {n_theo}件")
        return cands + analyses[top:]
    except Exception as e:  # noqa
        print(f"[JQ] 複合ランキング失敗（テクニカルのみで継続）: {e}")
        return analyses


def format_ranking(buys, sells, total: int, date_str: str) -> str:
    lines = [f"📊 株オラクル｜本日のランキング（{date_str}）",
             f"対象 {total} 銘柄を分析\n"]
    # 🔥 全方式割安（3/3）＝強い買い速報（買い候補の中から抽出）
    strong = [a for a in buys
              if (a.fund or {}).get("cons", {}).get("avail") == 3
              and (a.fund or {}).get("cons", {}).get("und") == 3]
    if strong:
        lines.append("🔥 全方式割安（3/3）＝強い買い")
        for a in strong:
            theo = (a.fund or {}).get("theo")
            extra = f"／理論株価¥{theo:,}" if theo else ""
            lines.append(f"  {a.code} {a.name}  ¥{a.price:,.0f}{extra}")
        lines.append("")
    lines.append("── 買い候補 TOP ──")
    for i, a in enumerate(buys, 1):
        tag = "🟢買" if a.signal == "BUY" else "・"
        sc = f"複合{a.combined:.0f}" if a.combined is not None else f"スコア{a.score:+.0f}"
        lines.append(f"{i}. {a.code} {a.name} {tag} {sc} ¥{a.price:,.0f}")
        if a.stop and a.target:
            lines.append(f"   目標¥{a.target:,.0f} / 損切¥{a.stop:,.0f}"
                         + (f" / RR {a.rr}" if a.rr else ""))
        ez = getattr(a, "ez", None)
        if ez:
            if ez["gap"] < 1.0:
                lines.append(f"   🎯狙い目 現値¥{ez['hi']:,}〜")
            else:
                lines.append(f"   🎯狙い目 指値¥{ez['dip']:,}〜現値¥{ez['hi']:,}（-{ez['gap']:.0f}%）")
        if a.fund:
            fp = []
            if a.fund.get("per") is not None: fp.append(f"PER{a.fund['per']:.1f}")
            if a.fund.get("roe") is not None: fp.append(f"ROE{a.fund['roe']:.1f}%")
            if a.fund.get("divy") is not None: fp.append(f"利回り{a.fund['divy']:.1f}%")
            if fp:
                lines.append("   " + " ".join(fp))
        cons = (a.fund or {}).get("cons") if a.fund else None
        if cons and cons.get("avail"):
            sym = {"u": "○", "o": "×", "f": "-"}
            parts = " ".join(f"{n}{sym[d['lab']]}" for n, d in cons["judg"].items())
            tail = " ✅購入検討" if cons["buy"] else ""
            lines.append(f"   割安 {cons['und']}/{cons['avail']}（{parts}）{tail}")
        elif a.fund and a.fund.get("theo"):
            theo = a.fund["theo"]
            gap = (a.price / theo - 1) * 100 if theo else 0
            lab = (f"割安{abs(gap):.0f}%" if gap <= -5
                   else (f"割高{gap:.0f}%" if gap >= 5 else "ほぼ適正"))
            lines.append(f"   理論株価¥{theo:,} {lab}")
        if a.bt:
            bp = [f"勝率{a.bt['win_rate']}%"]
            if a.bt.get("days_tp"): bp.append(f"利確~{a.bt['days_tp']}日")
            if a.bt.get("days_sl"): bp.append(f"損切~{a.bt['days_sl']}日")
            lines.append("   " + " ".join(bp))
        if a.reasons:
            lines.append(f"   {' / '.join(a.reasons[:2])}")
    if sells:
        lines.append("\n── 売り/警戒 TOP ──")
        for i, a in enumerate(sells, 1):
            tag = "🔴売" if a.signal == "SELL" else "・"
            lines.append(f"{i}. {a.code} {a.name} {tag} スコア{a.score:+.0f} ¥{a.price:,.0f}")
            if a.reasons:
                lines.append(f"   {' / '.join(a.reasons[:2])}")
    lines.append("\n※自分用の分析補助です。投資は自己責任で。")
    return "\n".join(lines)
