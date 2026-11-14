"""買い候補の実績トラッカー（data/picks.json）。

毎日の大引け後のランキング（買い候補TOP10）を記録し、その後の日足で「本当にどうなったか」を採点する。
売買ルールはランキングの表示どおり:
  ・約定   … 翌営業日の安値が 🎯指値 以下なら約定（始値が指値より下なら始値で約定）。届かなければ「不成立」
  ・決済   … 約定した日から、損切に触れたら損切・利確に触れたら利確（同じ日に両方なら損切＝保守的に）
  ・時間切れ … HOLD_DAYS 営業日たっても決まらなければ、その日の終値で手じまい
採点に使うのは確定した日足だけ（当日の途中足は使わない）。結果は手数料・税を含まない。
"""
from __future__ import annotations
import json
import math
from datetime import date, timedelta

from .config import ROOT

PATH = ROOT / "data" / "picks.json"
HOLD_DAYS = 20          # 時間切れまでの営業日数
KEEP_DAYS = 180         # これより古い記録は捨てる
DONE = ("win", "loss", "time")


def load(path=PATH) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception as e:  # noqa  壊れていても本処理は止めない
        print(f"[picks] 読込失敗（空で続行）: {e}")
        return []


def save(recs: list[dict], today: date, path=PATH) -> None:
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    recs = [r for r in recs if r["d"] >= cutoff]
    recs.sort(key=lambda r: (r["d"], r["c"]))
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(recs, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")


def _g(a, k):
    return a.get(k) if isinstance(a, dict) else getattr(a, k, None)


def record(recs: list[dict], day: str, buys) -> int:
    """その日の買い候補を追加する（同じ日・同じ銘柄は1件）。追加した件数を返す。"""
    have = {(r["d"], r["c"]) for r in recs}
    n = 0
    for rank, a in enumerate(buys, 1):
        code, tgt, stp = _g(a, "code"), _g(a, "target"), _g(a, "stop")
        ez = _g(a, "ez") or {}
        lim = ez.get("dip") or _g(a, "price")
        if not (code and tgt and stp and lim) or (day, code) in have:
            continue
        recs.append({"d": day, "c": str(code), "n": _g(a, "name") or "", "rk": rank,
                     "lim": float(lim), "tgt": float(tgt), "stp": float(stp), "s": "open"})
        have.add((day, code))
        n += 1
    return n


def _bars_after(df, day: str, before: str):
    """day より後・before より前（確定した日足）の行。"""
    idx = [i for i, t in enumerate(df.index) if day < t.date().isoformat() < before]
    return df.iloc[idx] if idx else df.iloc[0:0]


def evaluate_one(r: dict, df, today: str) -> dict:
    """1件を採点して r を更新する（決まっていれば何もしない）。"""
    if r.get("s") in DONE or r.get("s") == "nofill" or df is None or len(df) == 0:
        return r
    bars = _bars_after(df, r["d"], today)
    if len(bars) == 0:
        return r
    first = bars.iloc[0]
    if r.get("s") == "open":
        lo, op = float(first["Low"]), float(first["Open"])
        if not lo <= r["lim"]:
            r.update(s="nofill", fd=bars.index[0].date().isoformat())
            return r
        r.update(s="held", fd=bars.index[0].date().isoformat(),
                 px=round(min(op, r["lim"]), 2))
    entry = r["px"]
    held = [b for b in bars.itertuples() if b.Index.date().isoformat() >= r["fd"]]
    for i, b in enumerate(held, 1):
        lo, hi, op, cl = float(b.Low), float(b.High), float(b.Open), float(b.Close)
        if lo <= r["stp"]:
            ex = min(op, r["stp"]) if i > 1 else r["stp"]        # 窓を開けて下げたら始値
            return _close(r, "loss", ex, b.Index, entry)
        if hi >= r["tgt"]:
            ex = max(op, r["tgt"]) if i > 1 else r["tgt"]
            return _close(r, "win", ex, b.Index, entry)
        if i >= HOLD_DAYS:
            return _close(r, "time", cl, b.Index, entry)
    return r


def _close(r, s, ex, ts, entry):
    r.update(s=s, xd=ts.date().isoformat(), x=round(float(ex), 2),
             ret=round((float(ex) / entry - 1) * 100, 2))
    return r


def evaluate(recs: list[dict], frames: dict, today: str) -> int:
    """未決の記録をまとめて採点。決まった件数を返す。"""
    n = 0
    for r in recs:
        before = r.get("s")
        evaluate_one(r, frames.get(r["c"]), today)
        if r.get("s") != before and r.get("s") in DONE + ("nofill",):
            n += 1
    return n


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """勝率の95%信頼区間（Wilson）。"""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def summary(recs: list[dict]) -> dict:
    """成績のまとめ（手数料・税は含まない）。"""
    done = [r for r in recs if r.get("s") in DONE]
    fills = [r for r in recs if r.get("s") in DONE + ("held",)]
    tried = fills + [r for r in recs if r.get("s") == "nofill"]
    rets = [r["ret"] for r in done]
    n = len(done)
    wins = sum(1 for r in done if r["ret"] > 0)
    out = {"n": n, "wins": wins, "open": sum(1 for r in recs if r.get("s") in ("open", "held")),
           "fill": round(len(fills) / len(tried) * 100) if tried else None,
           "tried": len(tried), "since": min((r["d"] for r in recs), default=None)}
    if n:
        lo, hi = wilson(wins, n)
        mean = sum(rets) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1)) if n > 1 else 0.0
        half = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
        out.update(win=round(wins / n * 100), win_lo=round(lo * 100), win_hi=round(hi * 100),
                   avg=round(mean, 2), avg_lo=round(mean - half, 2), avg_hi=round(mean + half, 2),
                   tp=sum(1 for r in done if r["s"] == "win"),
                   sl=sum(1 for r in done if r["s"] == "loss"),
                   to=sum(1 for r in done if r["s"] == "time"))
    return out


def update(buys, frames: dict, day: str, path=PATH, add: bool = True) -> dict:
    """今日の候補を記録し（add=True＝大引け後だけ）、過去の候補を採点して保存。まとめを返す。"""
    recs = load(path)
    if not recs and not add:
        return summary(recs)
    added = record(recs, day, buys) if add else 0
    decided = evaluate(recs, frames, day)
    save(recs, date.fromisoformat(day), path)
    s = summary(recs)
    print(f"[picks] 追加 {added}件・決着 {decided}件 → 決着済み {s['n']}件・未決 {s['open']}件")
    return s
