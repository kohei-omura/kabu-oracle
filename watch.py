"""監視銘柄（watchlist）の売買タイミングを判定する。

タイミングが出た銘柄だけを通知対象にする（HOLD は通知しない）ことで
ノイズ通知を抑制する。
"""
from __future__ import annotations
import data as D
import signals as S


def check_watchlist(cfg: dict):
    watch = [str(c) for c in (cfg.get("watchlist") or [])]
    bench_code = cfg.get("benchmark", "^N225")
    bench_df = D.fetch_one(bench_code)
    bench = bench_df["Close"] if bench_df is not None else None

    frames = D.fetch_many(watch)
    results: list[S.Analysis] = []
    for c in watch:
        df = frames.get(c)
        if df is None:
            continue
        a = S.analyze(df, c, cfg=cfg, bench=bench)
        if a.error is None:
            results.append(a)
    triggered = [a for a in results if a.signal in ("BUY", "SELL")]
    return results, triggered


def format_watch(triggered, date_str: str) -> str:
    lines = [f"⏰ 株オラクル｜売買タイミング検知（{date_str}）\n"]
    for a in triggered:
        head = "🟢 買いサイン" if a.signal == "BUY" else "🔴 売りサイン"
        lines.append(f"{head}  {a.code} {a.name}")
        lines.append(f"  現在値 ¥{a.price:,.0f} / 確信度 {a.confidence}%")
        if a.signal == "BUY" and a.entry and a.stop and a.target:
            lines.append(f"  目安: 取得¥{a.entry:,.0f} → 利確¥{a.target:,.0f} / 損切¥{a.stop:,.0f}"
                         + (f" (RR {a.rr})" if a.rr else ""))
        elif a.signal == "SELL" and a.target and a.stop:
            lines.append(f"  目安: 手仕舞い検討 / 反発ライン¥{a.stop:,.0f}")
        if a.reasons:
            lines.append(f"  根拠: {' / '.join(a.reasons[:3])}")
        lines.append("")
    lines.append("※自分用の分析補助です。最終判断はご自身で。")
    return "\n".join(lines)


def format_watch_status(results, date_str: str) -> str:
    """タイミングが無い時の現況サマリ（手動実行用）。"""
    lines = [f"📋 監視銘柄の現況（{date_str}）\n"]
    for a in sorted(results, key=lambda x: x.score, reverse=True):
        mark = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[a.signal]
        lines.append(f"{mark} {a.code} {a.name} スコア{a.score:+.0f} "
                     f"¥{a.price:,.0f} [{a.signal}]")
    return "\n".join(lines)
