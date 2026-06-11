"""J-Quants V2 から財務情報を取得する（テク×ファンダ複合ランキング用）。

V2はAPIキー方式（V1のメール/パスワード=トークン方式は廃止）。
GitHub Secrets に JQUANTS_API_KEY を登録し、x-api-key ヘッダーで送る。
無料枠は「毎分5リクエスト」「過去2年・約12週間遅延」。
そのため呼び出し側はテクニカル上位の少数銘柄だけに絞り、十分な間隔をあけて取得する。
APIキー未設定／失敗時は None/{} を返し、テクニカルのみにフォールバックする。
"""
from __future__ import annotations
import os
import time
import requests

BASE = "https://api.jquants.com/v2"
_KEY = None
_TRIED = False


def get_api_key():
    """APIキーを取得（環境変数 JQUANTS_API_KEY）。無ければ None。"""
    global _KEY, _TRIED
    if _TRIED:
        return _KEY
    _TRIED = True
    _KEY = (os.getenv("JQUANTS_API_KEY") or "").strip() or None
    if not _KEY:
        print("[JQ] JQUANTS_API_KEY 未設定 → テクニカルのみで継続")
    return _KEY


def _f(v):
    try:
        s = str(v).strip()
        return float(s) if s not in ("", "-", "－") else None
    except (TypeError, ValueError):
        return None


def fetch_summary(code, key):
    """1銘柄の財務サマリー一覧（開示番号の昇順）。失敗時 []。429はやや待って再試行。"""
    out = []
    headers = {"x-api-key": key}
    params = {"code": code}
    for _ in range(6):  # pagination 安全弁
        r = None
        for attempt in range(2):
            try:
                r = requests.get(BASE + "/fins/summary", headers=headers,
                                 params=params, timeout=25)
            except Exception as e:  # noqa
                print(f"[JQ] summary {code} 例外: {e}")
                return out
            if r.status_code == 429 and attempt == 0:
                print("[JQ] レート制限(429) 60秒待機して再試行")
                time.sleep(60)
                continue
            break
        if r is None or r.status_code != 200:
            if r is not None and r.status_code != 200:
                print(f"[JQ] summary {code} -> {r.status_code} {r.text[:100]}")
            break
        j = r.json()
        out.extend(j.get("data", []))
        nxt = j.get("pagination_key")
        if not nxt:
            break
        params["pagination_key"] = nxt
    return out


def latest_fundamentals(data):
    """財務サマリー一覧（V2の短縮項目名）から最新の生財務値を取り出す。

    内部キー（ranking._metrics と共通）:
      eps_fore, eps_fy, bps, equity, equity_ratio,
      profit_fore, profit_fy, prev_profit_fy, div_fore, div_result
    """
    if not data:
        return None
    d = {"eps_fore": None, "eps_fy": None, "bps": None, "equity": None,
         "equity_ratio": None, "profit_fore": None, "profit_fy": None,
         "prev_profit_fy": None, "div_fore": None, "div_result": None}
    fy_profits = []
    for s in data:  # 開示番号の昇順
        def g(k):
            return _f(s.get(k))
        if g("FEPS") is not None: d["eps_fore"] = g("FEPS")        # 予想EPS(期末)
        if g("BPS") is not None: d["bps"] = g("BPS")               # 一株純資産
        if g("Eq") is not None: d["equity"] = g("Eq")             # 純資産
        if g("EqAR") is not None: d["equity_ratio"] = g("EqAR")   # 自己資本比率(0..1)
        if g("FNP") is not None: d["profit_fore"] = g("FNP")      # 予想純利益(期末)
        if g("FDivAnn") is not None: d["div_fore"] = g("FDivAnn") # 予想配当(合計)
        if g("DivAnn") is not None: d["div_result"] = g("DivAnn") # 配当実績(合計)
        if s.get("CurPerType") == "FY":
            if g("EPS") is not None: d["eps_fy"] = g("EPS")
            p = g("NP")
            if p is not None:
                fy_profits.append(p)
    if fy_profits:
        d["profit_fy"] = fy_profits[-1]
        if len(fy_profits) >= 2:
            d["prev_profit_fy"] = fy_profits[-2]
    if all(v is None for v in d.values()):
        return None
    return d


def fundamentals_for(codes, key, sleep=13.0):
    """複数銘柄の生財務値 {code: dict}。無料枠の毎分5件制限に合わせ既定13秒間隔。"""
    if not key:
        return {}
    res = {}
    n = len(codes)
    for i, c in enumerate(codes, 1):
        data = fetch_summary(c, key)
        f = latest_fundamentals(data)
        if f:
            res[c] = f
        if i % 5 == 0 or i == n:
            print(f"[JQ] 財務取得 {i}/{n}")
        if i < n:
            time.sleep(sleep)
    return res
