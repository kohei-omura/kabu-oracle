"""J-Quants V2 から財務情報を取得する（テク×ファンダ複合ランキング用）。

V2はAPIキー方式。GitHub Secrets に JQUANTS_API_KEY を登録し、x-api-key ヘッダーで送る。
無料枠は「毎分5リクエスト」「過去2年・約12週間遅延」。
リクエスト間隔はこのモジュールで一元管理する（呼び出し側がどこから何回呼んでも超えない）。
APIキー未設定／失敗時は None/{} を返し、テクニカルのみにフォールバックする。
"""
from __future__ import annotations
import os
import time
import requests

BASE = "https://api.jquants.com/v2"
MIN_INTERVAL = 13.0      # 秒。無料枠=毎分5件 → 12秒＋余裕
_KEY = None
_TRIED = False
_last_call = 0.0


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


def _throttle(interval: float) -> None:
    """前回のリクエストから interval 秒あくまで待つ。"""
    global _last_call
    wait = _last_call + interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _f(v):
    try:
        s = str(v).strip()
        return float(s) if s not in ("", "-", "－") else None
    except (TypeError, ValueError):
        return None


def fetch_summary(code, key, interval: float = MIN_INTERVAL):
    """1銘柄の財務サマリー一覧（開示番号の昇順）。失敗時 []。429は60秒待って1回だけ再試行。"""
    out = []
    headers = {"x-api-key": key}
    params = {"code": code}
    for _ in range(6):  # pagination 安全弁
        r = None
        for attempt in range(2):
            _throttle(interval)
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
            if r is not None:
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

    内部キー（ranking._metrics / report._tb_score と共通）:
      eps_fore, eps_fy, bps, equity, equity_ratio,
      profit_fore, profit_fy, prev_profit_fy, div_fore, div_result,
      sales_fy, prev_sales_fy, op_fy   （売上・営業利益は項目があるときだけ）

    ・本決算(FY)の開示では「今期予想」の欄が空で、翌期予想(NxF*)の欄に入ることがある。
      その場合は翌期予想を「現在の予想」として採用する（古い期の予想を使い続けない）。
    ・同じ決算期の訂正開示は後から出たものを採用し、前期比が同じ期どうしの比較にならないようにする。
    """
    if not data:
        return None
    d = {"eps_fore": None, "eps_fy": None, "bps": None, "equity": None,
         "equity_ratio": None, "profit_fore": None, "profit_fy": None,
         "prev_profit_fy": None, "div_fore": None, "div_result": None,
         "sales_fy": None, "prev_sales_fy": None, "op_fy": None}
    fy = {}   # 決算期末(無ければ連番) -> {"np":, "sales":, "op":, "eps":}
    for i, s in enumerate(data):  # 開示番号の昇順
        def g(k):
            return _f(s.get(k))
        is_fy = s.get("CurPerType") == "FY"
        # 予想：本決算の開示なら翌期予想を優先（無ければ通常の予想欄）
        fe = (g("NxFEPS") if is_fy else None)
        fe = fe if fe is not None else g("FEPS")
        fn = (g("NxFNP") if is_fy else None)
        fn = fn if fn is not None else g("FNP")
        fdv = (g("NxFDivAnn") if is_fy else None)
        fdv = fdv if fdv is not None else g("FDivAnn")
        if fe is not None: d["eps_fore"] = fe
        if fn is not None: d["profit_fore"] = fn
        if fdv is not None: d["div_fore"] = fdv
        if g("BPS") is not None: d["bps"] = g("BPS")
        if g("Eq") is not None: d["equity"] = g("Eq")
        if g("EqAR") is not None: d["equity_ratio"] = g("EqAR")
        if g("DivAnn") is not None: d["div_result"] = g("DivAnn")
        if is_fy:
            key = s.get("CurFYEn") or s.get("CurPerEn") or f"#{i}"
            rec = fy.setdefault(key, {})
            for name, fld in (("np", "NP"), ("sales", "Sales"), ("op", "OP"), ("eps", "EPS")):
                v = g(fld)
                if v is not None:
                    rec[name] = v          # 同じ期の訂正は後勝ち
    periods = [fy[k] for k in sorted(fy)]
    nps = [p["np"] for p in periods if "np" in p]
    if nps:
        d["profit_fy"] = nps[-1]
        if len(nps) >= 2:
            d["prev_profit_fy"] = nps[-2]
    sales = [p["sales"] for p in periods if "sales" in p]
    if sales:
        d["sales_fy"] = sales[-1]
        if len(sales) >= 2:
            d["prev_sales_fy"] = sales[-2]
    if periods and "op" in periods[-1]:
        d["op_fy"] = periods[-1]["op"]
    eps = [p["eps"] for p in periods if "eps" in p]
    if eps:
        d["eps_fy"] = eps[-1]
    if all(v is None for v in d.values()):
        return None
    return d


def fetch_fundamentals(code, key, interval: float = MIN_INTERVAL):
    """1銘柄の生財務値（latest_fundamentals の形）。取得失敗・データ無しは None。"""
    return latest_fundamentals(fetch_summary(code, key, interval))


def fundamentals_for(codes, key, sleep=MIN_INTERVAL):
    """複数銘柄の生財務値 {code: dict}。間隔は _throttle が守る。"""
    if not key:
        return {}
    res = {}
    n = len(codes)
    for i, c in enumerate(codes, 1):
        f = fetch_fundamentals(c, key, sleep)
        if f:
            res[c] = f
        if i % 5 == 0 or i == n:
            print(f"[JQ] 財務取得 {i}/{n}", flush=True)
    return res


def schema_report(code, key) -> None:
    """API が返す項目名を確認する（値は出さない＝公開ログに財務データを残さない）。"""
    data = fetch_summary(code, key)
    print(f"[JQ診断] {code}: {len(data)} 件")
    if not data:
        return
    names = sorted({k for s in data for k in s})
    print("[JQ診断] 項目名:", ", ".join(names))
    by_type: dict = {}
    for s in data:
        t = s.get("CurPerType") or "?"
        filled = by_type.setdefault(t, {})
        for k, v in s.items():
            if _f(v) is not None or (isinstance(v, str) and v.strip() not in ("", "-")):
                filled[k] = filled.get(k, 0) + 1
    for t, filled in by_type.items():
        cnt = sum(1 for s in data if (s.get("CurPerType") or "?") == t)
        keys = [k for k in filled if k.startswith(("F", "Nx", "Sales", "OP", "NP", "EPS", "Cur", "Sh"))]
        print(f"[JQ診断] {t} x{cnt}: 値のある項目 → {', '.join(sorted(keys))}")
    print("[JQ診断] 解析結果の項目:",
          sorted(k for k, v in (latest_fundamentals(data) or {}).items() if v is not None))
