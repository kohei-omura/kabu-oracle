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


def fetch_last_prices(codes: Iterable[str], interval: str = "15m",
                      period: str = "5d") -> dict[str, float]:
    """指定コードの「直近の株価」だけを軽く取得する（市場時間中の更新用）。

    日中足(15分)の最後の終値を採用。約15〜20分遅延。
    休場時は直近営業日の最終値になる。{code: price} を返す。
    """
    codes = [str(c).strip() for c in codes]
    out: dict[str, float] = {}
    if not codes:
        return out
    tickers = [to_ticker(c) for c in codes]
    try:
        data = yf.download(tickers, period=period, interval=interval,
                           auto_adjust=False, progress=False,
                           group_by="ticker", threads=True)
    except Exception:
        data = None
    if data is None or getattr(data, "empty", True):
        return out
    multi = isinstance(data.columns, pd.MultiIndex)
    for c, t in zip(codes, tickers):
        try:
            sub = data[t] if multi else data
            close = sub["Close"].dropna()
            if len(close):
                out[c] = float(close.iloc[-1])
        except Exception:
            pass
    return out


def fetch_many(codes: Iterable[str], period: str = "1y",
               interval: str = "1d", chunk_size: int = 120,
               pause: float = 0.8) -> dict[str, pd.DataFrame]:
    """一括ダウンロード。全銘柄(数千)でも安定するようバッチ分割して取得。

    Yahoo の一度のリクエストに大量ティッカーを渡すと失敗/制限されるため、
    chunk_size ごとに分割し、各バッチの間に pause 秒の小休止を入れる。
    取得できなかった銘柄は単純にスキップ（{code: DataFrame} のみ返す）。
    """
    codes = [str(c).strip() for c in codes]
    out: dict[str, pd.DataFrame] = {}
    total = len(codes)

    for start in range(0, total, chunk_size):
        chunk = codes[start:start + chunk_size]
        tickers = [to_ticker(c) for c in chunk]
        try:
            data = yf.download(tickers, period=period, interval=interval,
                               auto_adjust=True, progress=False,
                               group_by="ticker", threads=True)
        except Exception:
            data = None

        if data is not None and not getattr(data, "empty", True):
            multi = isinstance(data.columns, pd.MultiIndex)
            for c, t in zip(chunk, tickers):
                try:
                    sub = (data[t].dropna() if multi else data.dropna())
                    if not sub.empty:
                        out[c] = sub
                except Exception:
                    pass

        if total > chunk_size:
            print(f"  取得 {min(start + chunk_size, total)}/{total} "
                  f"（成功 {len(out)}）")
            time.sleep(pause)
    return out
