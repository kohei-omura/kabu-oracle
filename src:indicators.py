"""テクニカル指標（純関数）。すべて pandas.Series / DataFrame を入出力する。"""
from __future__ import annotations
import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder の RSI。"""
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / n, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / n, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n).std()
    upper = mid + k * sd
    lower = mid - k * sd
    width = (upper - lower)
    pctb = (close - lower) / width.replace(0, np.nan)
    return mid, upper, lower, pctb


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range（Wilder 平滑）。"""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def slope(s: pd.Series, n: int = 5) -> float:
    """直近 n 本の線形回帰の傾き（正規化済み）。"""
    y = s.dropna().tail(n).values
    if len(y) < n or np.all(y == 0):
        return 0.0
    x = np.arange(len(y))
    a = np.polyfit(x, y, 1)[0]
    return float(a / (np.mean(np.abs(y)) + 1e-9))


def crossed_up(fast: pd.Series, slow: pd.Series, lookback: int = 3) -> bool:
    """直近 lookback 本以内に fast が slow を上抜けたか。"""
    diff = (fast - slow)
    tail = diff.tail(lookback + 1)
    return bool((tail.shift(1) < 0).any() and tail.iloc[-1] > 0)


def crossed_down(fast: pd.Series, slow: pd.Series, lookback: int = 3) -> bool:
    diff = (fast - slow)
    tail = diff.tail(lookback + 1)
    return bool((tail.shift(1) > 0).any() and tail.iloc[-1] < 0)
