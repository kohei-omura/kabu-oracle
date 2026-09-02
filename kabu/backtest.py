"""簡易バックテスト（シグナルの妥当性検証用）。

指定銘柄の過去データに対し、BUY シグナルで仮想エントリーし、
利確/損切り/反対シグナルで決済した場合の勝率・平均損益を表示する。
※手数料・スリッページ・約定ズレは未考慮の概算。過去成績は将来を保証しない。
"""
from __future__ import annotations
import sys
import numpy as np

from .config import load_config
from . import data as D
from . import signals as S
from . import indicators as ind


def backtest_one(code: str, cfg: dict, period: str = "2y") -> dict:
    df = D.fetch_one(code, period=period)
    if df is None or len(df) < 120:
        return {"code": code, "error": "データ不足"}

    th = cfg.get("thresholds", {})
    stop_mult = th.get("atr_stop_mult", 2.0)
    tgt_mult = th.get("atr_target_mult", 3.0)
    a = ind.atr(df, 14)

    trades = []
    pos = None  # (entry_idx, entry, stop, target)
    for i in range(100, len(df)):
        window = df.iloc[: i + 1]
        if pos is None:
            res = S.analyze(window, code, cfg=cfg)
            if res.signal == "BUY":
                entry = float(window["Close"].iloc[-1])
                atr_now = float(a.iloc[i])
                pos = (i, entry, entry - atr_now * stop_mult,
                       entry + atr_now * tgt_mult)
        else:
            ei, entry, stop, target = pos
            hi = float(df["High"].iloc[i]); lo = float(df["Low"].iloc[i])
            close = float(df["Close"].iloc[i])
            exit_px = None
            if lo <= stop:
                exit_px = stop
            elif hi >= target:
                exit_px = target
            elif i - ei >= 20:  # 最大保有20営業日
                exit_px = close
            if exit_px is not None:
                trades.append((exit_px / entry - 1))
                pos = None

    if not trades:
        return {"code": code, "trades": 0}
    arr = np.array(trades)
    wins = arr[arr > 0]
    return {
        "code": code,
        "trades": len(arr),
        "win_rate": round(len(wins) / len(arr) * 100, 1),
        "avg_ret_%": round(arr.mean() * 100, 2),
        "total_ret_%": round((np.prod(1 + arr) - 1) * 100, 2),
        "best_%": round(arr.max() * 100, 2),
        "worst_%": round(arr.min() * 100, 2),
    }


if __name__ == "__main__":
    cfg = load_config()
    from .config import load_universe
    codes = sys.argv[1:] or [c for c, _ in load_universe(cfg)][:10]
    for c in codes:
        print(backtest_one(str(c), cfg))
