"""エントリーポイント。

使い方:
  python main.py session           # 場中ランナー（Actions の market.yml が使う。休場日は即終了）
  python main.py rank              # ユニバースの買い候補 Top-N を通知
  python main.py report            # docs/ のダッシュボードを生成
  python main.py close             # ダッシュボード生成＋ランキング通知（株価の取得は1回）
  python main.py prices            # docs/prices.json の株価だけ更新
  python main.py holdings          # 保有銘柄の利確/損切ライン到達を通知
  python main.py watch             # 監視銘柄のタイミングを検知（同じサインは1日1回）
  python main.py watch --status    # 監視銘柄の現況を必ず通知（手動確認用）
  python main.py analyze 7203      # 単一銘柄を即時分析（コンソール表示）
  python main.py jqdiag 7203       # J-Quants が返す項目名を確認（値は表示しない）
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta

from kabu.config import load_config
from kabu import ranking as R
from kabu import watch as W
from kabu import notify as N
from kabu import data as D
from kabu import signals as S
from kabu import report as REP
from kabu import state as ST

JST = timezone(timedelta(hours=9))


def _now() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")


def cmd_rank(cfg):
    scan = R.scan_universe(cfg)
    buys, sells, total = R.build_rankings(cfg, scan=scan)
    msg = R.format_ranking(buys, sells, total, _now(), scan.regime)
    print(msg)
    N.notify_all(cfg, "【株オラクル】本日のランキング", msg)


def cmd_close(cfg):
    from kabu import session
    st = ST.load()
    session.build(cfg, st, with_rank=True)
    ST.save(st)


def cmd_watch(cfg, status: bool):
    results, triggered = W.check_watchlist(cfg)
    if status:
        msg = W.format_watch_status(results, _now())
        print(msg)
        N.notify_all(cfg, "【株オラクル】監視銘柄の現況", msg)
        return
    st = ST.load()
    fresh = W.new_signals(triggered, st, datetime.now(JST).date().isoformat())
    ST.save(st)
    if fresh:
        msg = W.format_watch(fresh, _now())
        print(msg)
        N.notify_all(cfg, "【株オラクル】売買タイミング検知", msg)
    else:
        print(f"[{_now()}] 新しいタイミングなし。通知しません。")


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
    print(f"売買代金（20日平均）¥{a.turnover:,.0f}")
    print("ファクター:", a.factors)
    print("根拠:", " / ".join(a.reasons))


def cmd_jqdiag(code: str):
    from kabu import jquants as JQ
    key = JQ.get_api_key()
    if key:
        JQ.schema_report(code, key)


def main():
    p = argparse.ArgumentParser(description="株オラクル CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("rank", "report", "close", "prices", "holdings"):
        sub.add_parser(name)
    ps = sub.add_parser("session")
    ps.add_argument("--max-minutes", type=float, default=None,
                    help="この分数で引き継ぎ（動作確認用。既定は config の session.max_minutes）")
    pw = sub.add_parser("watch")
    pw.add_argument("--status", action="store_true")
    pa = sub.add_parser("analyze")
    pa.add_argument("code")
    pj = sub.add_parser("jqdiag")
    pj.add_argument("code", nargs="?", default="7203")
    p.add_argument("--config", default=None)
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.cmd == "session":
        from kabu import session
        print("終了:", session.run(args.max_minutes))
    elif args.cmd == "rank":
        cmd_rank(cfg)
    elif args.cmd == "report":
        REP.write_dashboard(cfg)
    elif args.cmd == "close":
        cmd_close(cfg)
    elif args.cmd == "prices":
        REP.write_prices(cfg)
    elif args.cmd == "holdings":
        REP.check_holdings(cfg)
    elif args.cmd == "watch":
        cmd_watch(cfg, args.status)
    elif args.cmd == "analyze":
        cmd_analyze(cfg, args.code)
    elif args.cmd == "jqdiag":
        cmd_jqdiag(args.code)


if __name__ == "__main__":
    main()
