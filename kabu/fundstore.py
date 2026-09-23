"""J-Quants 財務データのキャッシュ（data/fund_cache.json）。

財務は四半期ごとにしか変わらず、無料枠のデータ自体も約12週間遅れなので、
毎回取り直す必要はない。ランキング・テンバガー・保有銘柄の全処理でこのキャッシュを共有し、
古い（max_age_days 超）か未取得の銘柄だけを取りに行く。

形式: {"<code>": {"fetched": "YYYY-MM-DD", "raw": {...} | null}, ...}
  raw=null は「取得したがデータ無し」。毎回取り直さないように記録しておく。
1銘柄1行で書き出すので、git の差分は取り直した銘柄の行だけになる。
"""
from __future__ import annotations
import json
import time
from datetime import date, datetime

from .config import ROOT
from . import market as M

PATH = ROOT / "data" / "fund_cache.json"
LEGACY = ROOT / "docs" / "tenbagger_cache.json"   # 旧：公開フォルダに置いていたテンバガー用キャッシュ


class FundStore:
    def __init__(self, path=PATH):
        self.path = path
        self.items: dict = {}
        self.dirty = False
        src = path if path.exists() else (LEGACY if LEGACY.exists() else None)
        if src is not None:
            try:
                self.items = json.loads(src.read_text(encoding="utf-8")) or {}
            except Exception as e:  # noqa
                print(f"[fund] キャッシュ読込失敗（空で続行）: {e}")
            if src == LEGACY:
                self.dirty = True   # 次の save で data/ へ移す

    def _today(self) -> date:
        return M.now_jst().date()

    def age_days(self, code: str) -> float | None:
        e = self.items.get(code)
        if not e or not e.get("fetched"):
            return None
        try:
            d0 = datetime.strptime(e["fetched"], "%Y-%m-%d").date()
        except ValueError:
            return None
        return (self._today() - d0).days

    def get(self, code: str):
        """キャッシュの生財務値（古くても返す）。未取得・データ無しは None。"""
        e = self.items.get(code)
        return e.get("raw") if e else None

    def outdated(self, code: str) -> bool:
        """解析項目が増える前に保存した値か（売上・株式数などが無い）。優先して取り直す。"""
        raw = self.get(code)
        return raw is not None and "shares" not in raw

    def is_fresh(self, code: str, max_age_days: int) -> bool:
        a = self.age_days(code)
        return a is not None and a < max_age_days and not self.outdated(code)

    def _priority(self, code: str):
        """取り直す順：未取得 → 旧形式 → 古い順。"""
        a = self.age_days(code)
        return (a is not None, not self.outdated(code), -(a or 0))

    def put(self, code: str, raw) -> None:
        self.items[code] = {"fetched": self._today().isoformat(), "raw": raw}
        self.dirty = True

    def ensure(self, codes, key, max_age_days: int, cap: int | None = None,
               deadline: float | None = None) -> dict:
        """codes の生財務値 {code: raw} を返す。古い/未取得は最大 cap 件だけ取り直す。

        取り直しに失敗した銘柄は古い値のまま使う（何も出ないよりまし）。
        deadline（time.monotonic() 基準）を過ぎたら取得を打ち切る。
        """
        from . import jquants as JQ
        codes = [c for c in dict.fromkeys(codes) if c]
        need = [c for c in codes if not self.is_fresh(c, max_age_days)]
        # 未取得を先に、次に古い順
        need.sort(key=self._priority)
        if cap is not None:
            need = need[:max(0, cap)]
        if key and need:
            n = len(need)
            for i, c in enumerate(need, 1):
                if deadline is not None and time.monotonic() > deadline:
                    print(f"[fund] 時間切れで打ち切り（{i - 1}/{n}）")
                    break
                raw = JQ.fetch_fundamentals(c, key)
                # 取れなかったら古い値を残したまま日付だけ更新（毎回同じ銘柄を叩き続けない）
                self.put(c, raw if raw is not None else self.get(c))
                if i % 10 == 0 or i == n:
                    print(f"[fund] 財務取得 {i}/{n}", flush=True)
        return {c: self.get(c) for c in codes if self.get(c) is not None}

    def stale_order(self, codes, max_age_days: int) -> list:
        """古い/未取得の銘柄を、優先して取り直すべき順に並べる（空き時間の補充用）。"""
        need = [c for c in dict.fromkeys(codes) if not self.is_fresh(c, max_age_days)]
        need.sort(key=self._priority)
        return need

    def save(self) -> None:
        if not self.dirty and self.path.exists():
            return
        self.path.parent.mkdir(exist_ok=True)
        body = ",\n".join(
            f"{json.dumps(c)}:{json.dumps(self.items[c], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            for c in sorted(self.items))
        self.path.write_text("{\n" + body + "\n}\n", encoding="utf-8")
        self.dirty = False
        if LEGACY.exists():
            LEGACY.unlink()
