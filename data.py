"""株価データ取得（yfinance）。

- 日本株は証券コードに ".T" を付与（例: 7203 -> 7203.T）。
- 単一/一括ダウンロードに対応。
- データは約15〜20分遅延（無料・準リアルタイム）。デイトレ用ではなくスイング向け。
"""
from __future__ import annotations
from typing import Iterable, Optional
import time
import pandas as pd
import yfinance as yf


def to_ticker(code: str) -> str:
    code = str(code).strip()
    if code.startswith("^") or "." in code:
        return code  # 指数(^N225) や既に .T 付きはそのまま
    return f"{code}.T"


def fetch_one(code: str, period: str = "1y", interval: str = "1d",
              retries: int = 2) -> Optional[pd.DataFrame]:
    ticker = to_ticker(code)
    for i in range(retries + 1):
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False, threads=False)
            if df is None or df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna()
        except Exception:
            if i < retries:
                time.sleep(1.5)
            else:
                return None
    return None


def fetch_many(codes: Iterable[str], period: str = "1y",
               interval: str = "1d") -> dict[str, pd.DataFrame]:
    """一括ダウンロード（高速）。{code: DataFrame} を返す。"""
    codes = [str(c).strip() for c in codes]
    tickers = [to_ticker(c) for c in codes]
    out: dict[str, pd.DataFrame] = {}
    try:
        data = yf.download(tickers, period=period, interval=interval,
                           auto_adjust=True, progress=False,
                           group_by="ticker", threads=True)
    except Exception:
        data = None

    if data is None or data.empty:
        # フォールバック: 1銘柄ずつ
        for c in codes:
            d = fetch_one(c, period, interval)
            if d is not None:
                out[c] = d
        return out

    for c, t in zip(codes, tickers):
        try:
            if isinstance(data.columns, pd.MultiIndex):
                sub = data[t].dropna()
            else:
                sub = data.dropna()
            if not sub.empty:
                out[c] = sub
        except Exception:
            d = fetch_one(c, period, interval)
            if d is not None:
                out[c] = d
    return out
