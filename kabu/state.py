"""実行状態（data/state.json）。GitHub Actions がコミットして次の実行へ引き継ぐ。

  alerts … 通知の重複防止 {"<code>:<種類>": "YYYY-MM-DD"}（同じ内容は1日1回）
  runs   … その日にもう済ませた処理 {"YYYY-MM-DD": {"noon": "11:41", "close": "16:02", "rank": "16:03"}}

古い記録は KEEP_DAYS を過ぎたら捨てる（ファイルが際限なく育たないように）。
"""
from __future__ import annotations
import json
from datetime import date, timedelta

from .config import ROOT
from . import market as M

PATH = ROOT / "data" / "state.json"
LEGACY = ROOT / "data" / "holdings_state.json"   # 旧：通知の重複防止だけを持っていたファイル
KEEP_DAYS = 45


def load() -> dict:
    st: dict = {}
    try:
        if PATH.exists():
            st = json.loads(PATH.read_text(encoding="utf-8")) or {}
        elif LEGACY.exists():
            st = {"alerts": json.loads(LEGACY.read_text(encoding="utf-8")) or {}}
    except Exception as e:  # noqa  壊れていても通知が止まらないよう空で続行
        print(f"[state] 読込失敗（空で続行）: {e}")
        st = {}
    st.setdefault("alerts", {})
    st.setdefault("runs", {})
    return st


def save(st: dict, today: date | None = None) -> None:
    today = today or M.now_jst().date()
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    st["alerts"] = {k: v for k, v in st.get("alerts", {}).items() if str(v) >= cutoff}
    st["runs"] = {k: v for k, v in st.get("runs", {}).items() if k >= cutoff}
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    if LEGACY.exists():
        LEGACY.unlink()   # 移行が済んだら旧ファイルは消す（コミットで削除される）


def already(st: dict, key: str, today: str) -> bool:
    """同じ通知を今日すでに出したか。"""
    return st.get("alerts", {}).get(key) == today


def mark(st: dict, key: str, today: str) -> None:
    st.setdefault("alerts", {})[key] = today


def run_done(st: dict, day: str, what: str) -> bool:
    return bool(st.get("runs", {}).get(day, {}).get(what))


def run_mark(st: dict, day: str, what: str, hhmm: str) -> None:
    st.setdefault("runs", {}).setdefault(day, {})[what] = hhmm
