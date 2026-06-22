"""マルチファクター・スコアリングと売買シグナル生成。

設計方針（透明性重視）:
  - 各ファクターは -1.0〜+1.0 の寄与を返す
  - 重み付き合計をスコア（-100〜+100）に変換
  - エントリー/損切り/利確は ATR ベースで算出（再現可能）
  - 「タイミング」は直近のクロスやバンドタッチなどの“きっかけ”で判定
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

import indicators as ind


# ファクターの重み（合計 = 1.0）
WEIGHTS = {
    "trend": 0.30,        # 中期トレンド（EMA 配列）
    "momentum": 0.25,     # MACD / RSI
    "meanrev": 0.15,      # ボリンジャー %B（押し目/戻り）
    "volume": 0.10,       # 出来高の裏付け
    "relstr": 0.20,       # ベンチマーク相対力
}


@dataclass
class Analysis:
    code: str
    name: str = ""
    price: float = 0.0
    score: float = 0.0          # -100〜+100
    signal: str = "HOLD"        # BUY / SELL / HOLD
    confidence: int = 0          # 0〜100
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    rr: Optional[float] = None   # リスクリワード比
    atr: float = 0.0             # ATR(14)。保有銘柄のライン計算に使う
    reasons: list = field(default_factory=list)
    factors: dict = field(default_factory=dict)
    error: Optional[str] = None
    fund: Optional[dict] = None        # ファンダ指標(PER/PBR/ROE/利回り/増益率/スコア)
    combined: Optional[float] = None   # テク×ファンダ複合スコア(0〜100)
    bt: Optional[dict] = None          # バリア試算(勝率/想定保有日数)


def _clip(x: float) -> float:
    return float(max(-1.0, min(1.0, x)))


def price_limit(base: float) -> float:
    """東証の制限値幅（基準値段→1日の上下限の値幅・円）を返す。"""
    table = [
        (100, 30), (200, 50), (500, 80), (700, 100), (1000, 150),
        (1500, 300), (2000, 400), (3000, 500), (5000, 700),
        (7000, 1000), (10000, 1500), (15000, 3000), (20000, 4000),
        (30000, 5000), (50000, 7000), (70000, 10000), (100000, 15000),
        (150000, 30000), (200000, 40000), (300000, 50000),
        (500000, 70000), (700000, 100000), (1000000, 150000),
        (1500000, 300000), (2000000, 400000), (3000000, 500000),
        (5000000, 700000),
    ]
    for thr, lim in table:
        if base < thr:
            return float(lim)
    return 1000000.0


def holding_levels(buy: float, atr: float, cfg: dict | None = None) -> tuple:
    """保有銘柄の利確/損切ライン（買値基準・ATR）。発注は到達時に行う前提でクランプなし。"""
    cfg = cfg or {}
    th = (cfg.get("thresholds") or {})
    stop_mult = th.get("atr_stop_mult", 2.0)
    tgt_mult = th.get("atr_target_mult", 3.0)
    target = round(buy + atr * tgt_mult, 1)
    stop = round(buy - atr * stop_mult, 1)
    return target, stop


def analyze(
    df: pd.DataFrame,
    code: str,
    name: str = "",
    bench: Optional[pd.Series] = None,
    cfg: Optional[dict] = None,
) -> Analysis:
    cfg = cfg or {}
    th = (cfg.get("thresholds") or {})
    rsi_os = th.get("rsi_oversold", 30)
    rsi_ob = th.get("rsi_overbought", 70)
    stop_mult = th.get("atr_stop_mult", 2.0)
    tgt_mult = th.get("atr_target_mult", 3.0)

    if df is None or len(df) < 80:
        return Analysis(code=code, name=name, error="データ不足（80営業日未満）")

    close = df["Close"]
    price = float(close.iloc[-1])

    e25 = ind.ema(close, 25)
    e75 = ind.ema(close, 75)
    r = ind.rsi(close, 14)
    macd_line, sig, hist = ind.macd(close)
    mid, up, low, pctb = ind.bollinger(close, 20, 2.0)
    a = ind.atr(df, 14)
    atr_now = float(a.iloc[-1])
    vol = df["Volume"]
    vol_ma = ind.sma(vol, 20)

    reasons: list[str] = []
    f: dict[str, float] = {}

    # --- 1) トレンド ---
    trend = 0.0
    if e25.iloc[-1] > e75.iloc[-1]:
        trend += 0.5; 
        if price > e25.iloc[-1]:
            trend += 0.5
    else:
        trend -= 0.5
        if price < e25.iloc[-1]:
            trend -= 0.5
    trend += ind.slope(e25, 10) * 20  # 傾きで微調整
    f["trend"] = _clip(trend)
    if f["trend"] > 0.4:
        reasons.append("中期上昇トレンド（EMA25>EMA75）")
    elif f["trend"] < -0.4:
        reasons.append("中期下降トレンド")

    # --- 2) モメンタム（MACD + RSI）---
    rsi_now = float(r.iloc[-1])
    mom = 0.0
    mom += _clip(ind.slope(hist, 5) * 30)           # ヒストグラムの向き
    mom += 0.4 if hist.iloc[-1] > 0 else -0.4
    mom += (rsi_now - 50) / 50 * 0.5                 # RSI 位置
    f["momentum"] = _clip(mom)
    if rsi_now <= rsi_os:
        reasons.append(f"RSI {rsi_now:.0f}（売られすぎ）")
    elif rsi_now >= rsi_ob:
        reasons.append(f"RSI {rsi_now:.0f}（買われすぎ）")

    # --- 3) 平均回帰（%B）---
    b = float(pctb.iloc[-1]) if not np.isnan(pctb.iloc[-1]) else 0.5
    # 上昇トレンド中の押し目（%B 低）は買い寄り、戻り（%B 高）は売り寄り
    meanrev = (0.5 - b) * 2 * (1 if f["trend"] >= 0 else 0.3)
    f["meanrev"] = _clip(meanrev)
    if b <= 0.1:
        reasons.append("下バンド接近（押し目）")
    elif b >= 0.9:
        reasons.append("上バンド接近（過熱）")

    # --- 4) 出来高 ---
    vr = float(vol.iloc[-1] / (vol_ma.iloc[-1] + 1e-9)) if not np.isnan(vol_ma.iloc[-1]) else 1.0
    volf = _clip((vr - 1.0))
    # 出来高は方向（騰落）と組み合わせて評価
    chg = float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) > 1 else 0.0
    f["volume"] = _clip(volf * np.sign(chg) if chg != 0 else 0.0)
    if vr >= 1.5:
        reasons.append(f"出来高急増（平均比 {vr:.1f}倍）")

    # --- 5) 相対力（vs ベンチマーク, 20日）---
    rel = 0.0
    if bench is not None and len(bench) > 25:
        aligned = pd.concat([close, bench], axis=1).dropna()
        if len(aligned) > 25:
            s_ret = aligned.iloc[-1, 0] / aligned.iloc[-21, 0] - 1
            b_ret = aligned.iloc[-1, 1] / aligned.iloc[-21, 1] - 1
            rel = _clip((s_ret - b_ret) * 10)
    f["relstr"] = rel
    if rel > 0.3:
        reasons.append("指数より強い（相対力プラス）")
    elif rel < -0.3:
        reasons.append("指数より弱い")

    # --- 合成スコア ---
    score = sum(WEIGHTS[k] * f[k] for k in WEIGHTS) * 100
    score = float(round(score, 1))

    # --- タイミング判定（“きっかけ”）---
    golden = ind.crossed_up(e25, e75, 3) or ind.crossed_up(macd_line, sig, 2)
    dead = ind.crossed_down(e25, e75, 3) or ind.crossed_down(macd_line, sig, 2)
    rsi_recover = bool((r.shift(1).tail(3) < rsi_os).any() and rsi_now > rsi_os)
    rsi_turn = bool((r.shift(1).tail(3) > rsi_ob).any() and rsi_now < rsi_ob)
    bb_bounce = b <= 0.15 and chg > 0

    signal = "HOLD"
    if score >= 25 and (golden or rsi_recover or bb_bounce):
        signal = "BUY"
        if golden: reasons.insert(0, "ゴールデンクロス発生")
        if rsi_recover: reasons.insert(0, "RSIが売られすぎから回復")
        if bb_bounce: reasons.insert(0, "下バンドから反発")
    elif score <= -25 and (dead or rsi_turn or b >= 0.95):
        signal = "SELL"
        if dead: reasons.insert(0, "デッドクロス発生")
        if rsi_turn: reasons.insert(0, "RSIが買われすぎから反落")

    # --- エントリー/損切り/利確（ATRベース＋制限値幅で“発注できる値”に調整）---
    entry = price
    raw_stop = price - atr_now * stop_mult
    raw_target = price + atr_now * tgt_mult
    lim = price_limit(price)
    upper = price + lim
    lower = max(1.0, price - lim)
    stop = round(max(raw_stop, lower), 1)
    target = round(min(raw_target, upper), 1)
    if raw_target > upper or raw_stop < lower:
        reasons.append("値幅制限内に調整")
    risk = entry - stop
    rr = round((target - entry) / risk, 2) if risk > 0 else None

    confidence = int(min(100, abs(score) + (20 if signal != "HOLD" else 0)))

    return Analysis(
        code=code, name=name, price=round(price, 1), score=score,
        signal=signal, confidence=confidence,
        entry=entry, stop=stop, target=target, rr=rr, atr=round(atr_now, 2),
        reasons=reasons[:5], factors={k: round(v, 2) for k, v in f.items()},
    )


def barrier_stats(df, entry: float, target: float, stop: float,
                  horizon: int = 60, lookback: int = 480) -> dict | None:
    """トリプルバリア法で「利確勝率」と「想定保有日数」を過去データから試算。

    現在値(entry)から見た 利確(target)/損切(stop) と同じ上下率の壁を、過去の各日を
    擬似エントリーとして当て、どちらに先に当たったか・何営業日かかったかを集計する。
    返す: {win_rate, days_tp, days_sl, n}（%・営業日）。算出不可なら None。
    あくまで過去ボラからの目安（将来を保証しない）。
    """
    if df is None or entry <= 0 or target <= entry or stop <= 0 or stop >= entry:
        return None
    up = target / entry - 1.0       # 利確までの上昇率
    dn = 1.0 - stop / entry         # 損切までの下落率
    if up <= 0 or dn <= 0:
        return None
    try:
        hi = df["High"].to_numpy(dtype="float64")
        lo = df["Low"].to_numpy(dtype="float64")
        cl = df["Close"].to_numpy(dtype="float64")
    except Exception:
        return None
    n = len(cl)
    if n < 80:
        return None
    start = max(0, n - lookback)
    win_days, loss_days = [], []
    last = n - 1
    for i in range(start, last):
        e = cl[i]
        if e <= 0:
            continue
        tp = e * (1 + up)
        sl = e * (1 - dn)
        end = min(i + horizon, last)
        for j in range(i + 1, end + 1):
            if lo[j] <= sl:            # 同日に両方なら損切優先（保守的）
                loss_days.append(j - i)
                break
            if hi[j] >= tp:
                win_days.append(j - i)
                break
    wins, losses = len(win_days), len(loss_days)
    if wins + losses < 15:             # サンプル不足
        return None
    return {
        "win_rate": round(100 * wins / (wins + losses)),
        "days_tp": round(sum(win_days) / wins) if wins else None,
        "days_sl": round(sum(loss_days) / losses) if losses else None,
        "n": wins + losses,
    }
