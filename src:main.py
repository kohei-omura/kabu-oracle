"""エントリーポイント。

使い方:
  python -m src.main rank              # ユニバースの買い/売り Top-N を通知
  python -m src.main watch             # 監視銘柄のタイミングを検知（出た時だけ通知）
  python -m src.main watch --status    # 監視銘柄の現況を必ず通知（手動確認用）
  python -m src.main analyze 7203      # 単一銘柄を即時分析（コンソール表示）
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta

from .config import load_config
from . import ranking as R
from . import watch as W
from . import notify as N
from . import data as D
from . import signals as S
from . import report as REP

JST = timezone(timedelta(hours=9))


def _now() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")


def cmd_rank(cfg):
    buys, sells, total = R.build_rankings(cfg)
    msg = R.format_ranking(buys, sells, total, _now())
    print(msg)
    N.notify_all(cfg, "【株オラクル】本日のランキング", msg)


def cmd_watch(cfg, status: bool):
    results, triggered = W.check_watchlist(cfg)
    if status:
        msg = W.format_watch_status(results, _now())
        print(msg)
        N.notify_all(cfg, "【株オラクル】監視銘柄の現況", msg)
        return
    if triggered:
        msg = W.format_watch(triggered, _now())
        print(msg)
        N.notify_all(cfg, "【株オラクル】売買タイミング検知", msg)
    else:
        print(f"[{_now()}] タイミング該当なし。通知しません。")


def cmd_analyze(cfg, code: str):
    df = D.fetch_one(code)
    a = S.analyze(df, code, cfg=cfg)
    if a.error:
        print(f"{code}: {a.error}")
        return
    print(f"=== {a.code} {a.name} ===")
    print(f"現在値 ¥{a.price:,.0f} / スコア {a.score:+.0f} / シグナル {a.signal} "
          f"(確信度 {a.confidence}%)")
    if a.entry:
        print(f"取得¥{a.entry:,.0f} 利確¥{a.target:,.0f} 損切¥{a.stop:,.0f} RR {a.rr}")
    print("ファクター:", a.factors)
    print("根拠:", " / ".join(a.reasons))


def main():
    p = argparse.ArgumentParser(description="株オラクル CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rank")
    sub.add_parser("report")
    pw = sub.add_parser("watch")
    pw.add_argument("--status", action="store_true")
    pa = sub.add_parser("analyze")
    pa.add_argument("code")
    p.add_argument("--config", default=None)
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.cmd == "rank":
        cmd_rank(cfg)
    elif args.cmd == "report":
        REP.write_dashboard(cfg)
    elif args.cmd == "watch":
        cmd_watch(cfg, args.status)
    elif args.cmd == "analyze":
        cmd_analyze(cfg, args.code)


if __name__ == "__main__":
    main()
