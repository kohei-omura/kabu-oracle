"""設定ロード: config.yaml + 環境変数（GitHub Secrets）。"""
from __future__ import annotations
import os
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parent.parent   # リポジトリ直下


def _load_watchlist_txt() -> list[str] | None:
    """watchlist.txt（1行1コード、# はコメント）を読む。無ければ None。"""
    p = ROOT / "watchlist.txt"
    if not p.exists():
        return None
    codes: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        code = line.replace(",", " ").split()[0].strip()  # 先頭トークン=コード
        if code:
            codes.append(code)
    return codes


def load_config(path: str | None = None) -> dict:
    p = Path(path) if path else ROOT / "config.yaml"
    cfg: dict = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        print(f"[config] {p.name} が無いので既定値で動きます")

    # watchlist.txt があれば push 監視銘柄をそれで上書き（1行1コード・# はコメント）
    wl = _load_watchlist_txt()
    if wl is not None:
        cfg["watchlist"] = wl

    # 通知先などの機密情報は環境変数から
    cfg["secrets"] = {
        "line_token": os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
        "line_user_id": os.getenv("LINE_USER_ID", ""),
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": int((os.getenv("SMTP_PORT") or "").strip() or "465"),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_pass": os.getenv("SMTP_PASS", ""),
        "mail_to": os.getenv("MAIL_TO", ""),
    }
    return cfg


def load_universe(cfg: dict) -> list[tuple[str, str]]:
    """(code, name) のリストを返す。markets 設定で市場区分を絞り込む。"""
    rel = cfg.get("universe_file", "data/universe_all.csv")
    p = ROOT / rel
    out: list[tuple[str, str]] = []
    if not p.exists():
        return out
    markets = str(cfg.get("markets", "all")).lower().replace(" ", "")
    allow = None if markets in ("all", "") else set(markets.split(","))
    import csv
    with open(p, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0].strip().lower() == "code":
                continue
            code = row[0].strip()
            name = row[1].strip() if len(row) > 1 else ""
            mkt = row[2].strip().lower() if len(row) > 2 else ""
            if allow is not None and mkt not in allow:
                continue
            out.append((code, name))
    return out


def market_map(cfg: dict) -> dict[str, str]:
    """{code: market} を返す（表示用・絞り込みなし）。"""
    rel = cfg.get("universe_file", "data/universe_all.csv")
    p = ROOT / rel
    m: dict[str, str] = {}
    if not p.exists():
        return m
    import csv
    with open(p, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) > 2 and row[0].strip().lower() != "code":
                m[row[0].strip()] = row[2].strip().lower()
    return m


# 長期保有マーク（holdings.txt の行のどこかに書けば有効／大文字小文字は無視）
LONG_TOKENS = {"長期", "長期保有", "long", "longterm", "hold"}


def load_holdings() -> list[dict]:
    """holdings.txt を読む。各行 'code,買値[,利確,損切][,長期]'（# はコメント）。

    行のどこかに「長期」（long/hold でも可）があれば長期保有フラグを立てる。
    ダッシュボードの「長期保有」ボタンもこの印を付け外しする。
    """
    p = ROOT / "holdings.txt"
    out: list[dict] = []
    if not p.exists():
        return out

    def _num(parts, i):
        try:
            return float(parts[i])
        except (IndexError, ValueError):
            return None

    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.replace("，", ",").split(",")]
        # 長期マークは位置に依存させない（利確/損切の桁ズレを避けるため先に取り除く）
        is_long = any(x.lower() in LONG_TOKENS for x in parts)
        parts = [x for x in parts if x.lower() not in LONG_TOKENS]
        code = parts[0] if parts else ""
        if not code:
            continue
        out.append({"code": code, "buy": _num(parts, 1),
                    "target": _num(parts, 2), "stop": _num(parts, 3),
                    "long": is_long})
    return out
