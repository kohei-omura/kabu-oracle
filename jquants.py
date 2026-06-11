"""J-Quants 無料枠から財務情報を取得する（テク×ファンダ複合ランキング用）。

無料枠は「過去2年・約12週間遅延」。四半期ごとの決算サマリー(/fins/statements)を使う。
認証は GitHub Secrets から：
  ・JQUANTS_REFRESH_TOKEN（推奨）  もしくは
  ・JQUANTS_MAIL + JQUANTS_PASS
どれも無い／失敗した場合は None を返し、呼び出し側はテクニカルのみにフォールバックする。
"""
from __future__ import annotations
import os
import time
import requests

BASE = "https://api.jquants.com/v1"
_TOKEN: str | None = None
_TRIED = False


def _post(path: str, **kw) -> dict | None:
    try:
        r = requests.post(BASE + path, timeout=20, **kw)
        if r.status_code == 200:
            return r.json()
        print(f"[JQ] {path} -> {r.status_code} {r.text[:120]}")
    except Exception as e:  # noqa
        print(f"[JQ] {path} 例外: {e}")
    return None


def get_id_token() -> str | None:
    """IDトークンを取得（1回だけ試行してキャッシュ）。失敗時は None。"""
    global _TOKEN, _TRIED
    if _TRIED:
        return _TOKEN
    _TRIED = True

    direct = (os.getenv("JQUANTS_ID_TOKEN") or "").strip()
    if direct:
        _TOKEN = direct
        return _TOKEN

    refresh = (os.getenv("JQUANTS_REFRESH_TOKEN") or "").strip()
    if not refresh:
        mail = (os.getenv("JQUANTS_MAIL") or "").strip()
        pw = (os.getenv("JQUANTS_PASS") or "").strip()
        if mail and pw:
            j = _post("/token/auth_user", json={"mailaddress": mail, "password": pw})
            refresh = (j or {}).get("refreshToken", "")
        if not refresh:
            print("[JQ] 認証情報なし／取得失敗 → テクニカルのみで継続")
            return None

    j = _post("/token/auth_refresh", params={"refreshtoken": refresh})
    _TOKEN = (j or {}).get("idToken")
    if not _TOKEN:
        print("[JQ] IDトークン取得失敗 → テクニカルのみで継続")
    return _TOKEN


def _f(v) -> float | None:
    try:
        s = str(v).strip()
        return float(s) if s not in ("", "-", "－") else None
    except (TypeError, ValueError):
        return None


def fetch_statements(code: str, token: str) -> list:
    """1銘柄の決算サマリー一覧（開示番号の昇順）。失敗時 []。"""
    out: list = []
    headers = {"Authorization": f"Bearer {token}"}
    params = {"code": code}
    for _ in range(5):  # pagination 安全弁
        try:
            r = requests.get(BASE + "/fins/statements", headers=headers,
                             params=params, timeout=20)
        except Exception as e:  # noqa
            print(f"[JQ] statements {code} 例外: {e}")
            break
        if r.status_code != 200:
            if r.status_code == 401:
                print("[JQ] トークン期限切れ/無効")
            break
        j = r.json()
        out.extend(j.get("statements", []))
        key = j.get("pagination_key")
        if not key:
            break
        params["pagination_key"] = key
    return out


def latest_fundamentals(statements: list) -> dict | None:
    """決算一覧から最新の生財務値を取り出す（項目ごとに直近の非空値を採用）。

    返す: {eps_fore, eps_fy, bps, equity, equity_ratio,
           profit_fore, profit_fy, prev_profit_fy, div_fore, div_result}
    すべて float または None。1つも取れなければ None。
    """
    if not statements:
        return None
    d: dict = {"eps_fore": None, "eps_fy": None, "bps": None, "equity": None,
               "equity_ratio": None, "profit_fore": None, "profit_fy": None,
               "prev_profit_fy": None, "div_fore": None, "div_result": None}
    fy_profits: list = []  # (DisclosureNumber, Profit) の FY 実績
    for s in statements:  # 昇順
        def g(k):
            return _f(s.get(k))
        if g("ForecastEarningsPerShare") is not None: d["eps_fore"] = g("ForecastEarningsPerShare")
        if g("BookValuePerShare") is not None: d["bps"] = g("BookValuePerShare")
        if g("Equity") is not None: d["equity"] = g("Equity")
        if g("EquityToAssetRatio") is not None: d["equity_ratio"] = g("EquityToAssetRatio")
        if g("ForecastProfit") is not None: d["profit_fore"] = g("ForecastProfit")
        if g("ForecastDividendPerShareAnnual") is not None: d["div_fore"] = g("ForecastDividendPerShareAnnual")
        if g("ResultDividendPerShareAnnual") is not None: d["div_result"] = g("ResultDividendPerShareAnnual")
        if s.get("TypeOfCurrentPeriod") == "FY":
            if g("EarningsPerShare") is not None: d["eps_fy"] = g("EarningsPerShare")
            p = g("Profit")
            if p is not None:
                fy_profits.append(p)
    if fy_profits:
        d["profit_fy"] = fy_profits[-1]
        if len(fy_profits) >= 2:
            d["prev_profit_fy"] = fy_profits[-2]
    if all(v is None for v in d.values()):
        return None
    return d


def fundamentals_for(codes: list[str], token: str, sleep: float = 0.25) -> dict:
    """複数銘柄の生財務値 {code: dict}。token なしなら {}。"""
    if not token:
        return {}
    res: dict = {}
    for c in codes:
        st = fetch_statements(c, token)
        f = latest_fundamentals(st)
        if f:
            res[c] = f
        time.sleep(sleep)
    return res
