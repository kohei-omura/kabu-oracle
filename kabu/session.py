"""場中ランナー：取引日の場中だけ1つのジョブを動かし続け、決まった時刻に処理を回す。

GitHub Actions の cron は混雑時に大幅に遅れたり間引かれたりする（実測で「20分毎」が1日2回、
16:30 指定が 21〜23 時に実行）。そこで cron は「ランナーを起こすきっかけ」にだけ使い、
一度起きたら次の時刻表どおりに自分で処理する。

  9:05〜11:55 / 12:35〜15:55 の10分毎 … 株価更新・保有アラート・監視銘柄（データは約20分遅れ）
  11:56 頃（昼休み）                   … ダッシュボード再生成（前場の値動きを反映）
  15:56 頃（大引け後）                  … 最終チェック → ダッシュボード → ランキング通知（1日1通）→ 終了

・休場日（土日・祝日・年末年始）は何もせず終了
・その日の大引け処理が済んでいれば即終了（遅れて起きた cron が重複して通知しない）
・Actions の1ジョブ6時間制限の手前で、自分の後継ジョブを起動して引き継ぐ
・待ち時間には J-Quants の財務（無料枠の毎分5件以内）を少しずつ補充する
"""
from __future__ import annotations
import os
import subprocess
import time
from datetime import datetime

from . import market as M
from . import state as ST
from .config import ROOT, load_config, load_holdings, load_universe

AM_TICKS = (9 * 60 + 5, 11 * 60 + 55)     # 前場の最終値（11:30＋遅延20分）まで
PM_TICKS = (12 * 60 + 35, 15 * 60 + 55)   # 大引けの値（15:30＋遅延20分）まで
NOON_AT, NOON_END = 11 * 60 + 56, 12 * 60 + 35
CLOSE_AT = 15 * 60 + 56
PUSH_ALL = ("docs", "data")                                  # 節目（昼・大引け・引き継ぎ）
PUSH_TICK = ("docs/prices.json", "data/state.json", "data/holdings_state.json")  # 場中の毎回


def _log(msg: str) -> None:
    print(f"[{M.now_jst():%H:%M:%S}] {msg}", flush=True)


def _minutes(now: datetime) -> int:
    return now.hour * 60 + now.minute


def _in_ticks(m: int) -> bool:
    return AM_TICKS[0] <= m <= AM_TICKS[1] or PM_TICKS[0] <= m <= PM_TICKS[1]


def _events(tick: int) -> list[int]:
    ev = set()
    for a, b in (AM_TICKS, PM_TICKS):
        ev.update(range(a, b + 1, tick))
    ev.update((NOON_AT, CLOSE_AT))
    return sorted(ev)


def _next_event(m: int, tick: int) -> int | None:
    for e in _events(tick):
        if e > m:
            return e
    return None


# ---------------- git（Actions 上でだけコミット＆プッシュ） ----------------

def _on_actions() -> bool:
    return os.getenv("GITHUB_ACTIONS") == "true"


def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def git_sync() -> None:
    """最新の main を取り込む（長期保有ボタンや holdings.txt の編集をすぐ反映するため）。"""
    if _on_actions():
        r = _git("pull", "--rebase", "--autostash", "-q")
        if r.returncode != 0:
            _log(f"git pull 失敗: {r.stderr.strip()[:200]}")


def commit_push(msg: str, paths=PUSH_ALL) -> None:
    if not _on_actions():
        return
    for p in paths:                 # 無いパスがあっても他は追加できるよう1つずつ
        _git("add", "-A", "--", p)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return
    _git("commit", "-q", "-m", msg)
    for i in range(4):
        _git("pull", "--rebase", "--autostash", "-q")
        r = _git("push", "-q")
        if r.returncode == 0:
            return
        _log(f"push 失敗（{i + 1}回目）: {r.stderr.strip()[:200]}")
        time.sleep(2 * 2 ** i)


def handoff() -> bool:
    """6時間制限の手前で、同じワークフローを workflow_dispatch で起動して引き継ぐ。"""
    import requests
    repo, token = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_TOKEN")
    if not (repo and token):
        _log("引き継ぎ不可（Actions 外）")
        return False
    wf = os.getenv("KABU_WORKFLOW", "market.yml")
    ref = os.getenv("GITHUB_REF_NAME", "main")
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"ref": ref, "inputs": {"task": "session"}}, timeout=20)
        ok = r.status_code in (200, 204)
        _log(f"後継ジョブを起動: {'OK' if ok else r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:  # noqa
        _log(f"後継ジョブ起動に失敗: {e}")
        return False


# ---------------- 処理本体 ----------------

def tick(cfg: dict, st: dict) -> None:
    """株価更新・保有アラート・監視銘柄（軽い処理）。"""
    from . import report as REP
    from . import watch as W
    from . import notify as N
    REP.write_prices(cfg)
    REP.check_holdings(cfg, st)
    _, trig = W.check_watchlist(cfg)
    fresh = W.new_signals(trig, st, M.now_jst().date().isoformat())
    if fresh:
        msg = W.format_watch(fresh, M.now_jst().strftime("%Y-%m-%d %H:%M JST"))
        print(msg)
        N.notify_all(cfg, "【株オラクル】売買タイミング検知", msg)


def build(cfg: dict, st: dict, with_rank: bool) -> None:
    """全銘柄を1回だけ取得して、ダッシュボードと（大引け後は）ランキング通知を作る。"""
    from . import ranking as R
    from . import report as REP
    from . import notify as N
    from .fundstore import FundStore
    holds = load_holdings()
    extra = [h["code"] for h in holds] + [str(c) for c in (cfg.get("watchlist") or [])]
    scan = R.scan_universe(cfg, extra_codes=extra)
    store = FundStore()
    buys = REP.write_dashboard(cfg, scan=scan, store=store)
    REP.write_prices(cfg)
    day = M.now_jst().date().isoformat()
    if with_rank and not ST.run_done(st, day, "rank"):
        msg = R.format_ranking(buys, [], scan.total,
                               M.now_jst().strftime("%Y-%m-%d %H:%M JST"), scan.regime)
        print(msg)
        N.notify_all(cfg, "【株オラクル】本日のランキング", msg)
        ST.run_mark(st, day, "rank", M.now_jst().strftime("%H:%M"))


def backfill(cfg: dict, until: float) -> int:
    """待ち時間に J-Quants の財務を古い順に補充する（無料枠の間隔を守る）。取得件数を返す。"""
    fc = cfg.get("fundamentals") or {}
    if not fc.get("enabled", False) or not fc.get("background_fill", True):
        return 0
    from . import jquants as JQ
    from .fundstore import FundStore
    key = JQ.get_api_key()
    if not key or until - time.monotonic() < 30:
        return 0
    store = FundStore()
    codes = [c for c, _ in load_universe(
        {"universe_file": cfg.get("universe_file", "data/universe_all.csv"), "markets": "all"})]
    order = store.stale_order(codes, int(fc.get("background_days", 14)))
    if not order:
        return 0
    before = len(store.items)
    store.ensure(order, key, max_age_days=int(fc.get("background_days", 14)),
                 deadline=until - 20)
    got = sum(1 for c in order if store.is_fresh(c, int(fc.get("background_days", 14))))
    store.save()
    _log(f"財務を補充: {got}件（キャッシュ {before}→{len(store.items)}件）")
    return got


def run(max_minutes: float | None = None) -> str:
    """取引日の場中ループ。戻り値は終了理由（holiday / done / handoff / end / early）。"""
    t0 = time.monotonic()
    cfg = load_config()
    scfg = cfg.get("session") or {}
    max_minutes = max_minutes or float(scfg.get("max_minutes", 340))
    tick_min = int(scfg.get("tick_minutes", 10))
    deadline = t0 + max_minutes * 60

    git_sync()
    while True:
        now = M.now_jst()
        d, m = now.date(), _minutes(now)
        day = d.isoformat()
        if not M.is_trading_day(d):
            _log(f"休場日（{M.closed_reason(d)}）のため何もしません")
            return "holiday"
        st = ST.load()
        if ST.run_done(st, day, "close"):
            _log("本日の大引け処理は完了済み")
            return "done"
        if time.monotonic() >= deadline - 1:
            commit_push(f"session handoff {day} [skip ci]")
            handoff()
            return "handoff"

        cfg = load_config()          # 設定・ウォッチリストの変更を毎回反映
        did = []
        try:
            if _in_ticks(m):
                tick(cfg, st)
                did.append("tick")
            if NOON_AT <= m < NOON_END and not ST.run_done(st, day, "noon"):
                build(cfg, st, with_rank=False)
                ST.run_mark(st, day, "noon", M.now_jst().strftime("%H:%M"))
                did.append("noon")
            if m >= CLOSE_AT:
                if "tick" not in did:
                    tick(cfg, st)
                build(cfg, st, with_rank=True)
                ST.run_mark(st, day, "close", M.now_jst().strftime("%H:%M"))
                did.append("close")
        except Exception as e:  # noqa  1回の失敗でループ全体を止めない
            import traceback
            traceback.print_exc()
            _log(f"処理中にエラー（次の回で再試行）: {e}")
        ST.save(st)
        milestone = "noon" in did or "close" in did
        commit_push(f"market {day} {M.now_jst():%H:%M} {'+'.join(did) or 'idle'} [skip ci]",
                    PUSH_ALL if milestone else PUSH_TICK)
        if did:
            _log(f"完了: {', '.join(did)}")
        if "close" in did:
            return "end"

        # 次の予定時刻まで待つ（その間に財務を補充）
        nxt = _next_event(_minutes(M.now_jst()), tick_min)
        if nxt is None:
            nxt = CLOSE_AT
        target = M.now_jst().replace(hour=nxt // 60, minute=nxt % 60, second=5, microsecond=0)
        wait = max(5.0, (target - M.now_jst()).total_seconds())
        if wait > 3 * 3600:
            # 深夜などに起こされた場合は居座らない（8:17 からの cron が改めて起こす）
            _log(f"次の処理まで {wait / 3600:.1f} 時間あるので終了（朝の起動に任せる）")
            return "early"
        wake = min(time.monotonic() + wait, deadline)   # 6時間制限を越えて眠らない
        _log(f"次は {nxt // 60:02d}:{nxt % 60:02d}（{wait / 60:.0f}分後）")
        backfill(cfg, wake)
        rest = wake - time.monotonic()
        if rest > 0:
            time.sleep(rest)
        git_sync()
