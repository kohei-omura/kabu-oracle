"""ユニバースをスコアリングし、買い/売り Top-N を算出する。"""
from __future__ import annotations
import data as D
import signals as S
from config import load_universe


def build_rankings(cfg: dict):
    universe = load_universe(cfg)
    top_n = int(cfg.get("top_n", 5))
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

    buys = sorted([a for a in analyses], key=lambda x: x.score, reverse=True)[:top_n]
    sells = sorted([a for a in analyses], key=lambda x: x.score)[:top_n]
    return buys, sells, len(analyses)


def format_ranking(buys, sells, total: int, date_str: str) -> str:
    lines = [f"📊 株オラクル｜本日のランキング（{date_str}）",
             f"対象 {total} 銘柄を分析\n",
             "── 買い候補 TOP ──"]
    for i, a in enumerate(buys, 1):
        tag = "🟢買" if a.signal == "BUY" else "・"
        lines.append(f"{i}. {a.code} {a.name} {tag} スコア{a.score:+.0f} ¥{a.price:,.0f}")
        if a.signal == "BUY" and a.stop and a.target:
            lines.append(f"   目標¥{a.target:,.0f} / 損切¥{a.stop:,.0f}"
                         + (f" / RR {a.rr}" if a.rr else ""))
        if a.reasons:
            lines.append(f"   {' / '.join(a.reasons[:2])}")
    lines.append("\n── 売り/警戒 TOP ──")
    for i, a in enumerate(sells, 1):
        tag = "🔴売" if a.signal == "SELL" else "・"
        lines.append(f"{i}. {a.code} {a.name} {tag} スコア{a.score:+.0f} ¥{a.price:,.0f}")
        if a.reasons:
            lines.append(f"   {' / '.join(a.reasons[:2])}")
    lines.append("\n※自分用の分析補助です。投資は自己責任で。")
    return "\n".join(lines)
