"""設定ロード: config.yaml + 環境変数（GitHub Secrets）。"""
from __future__ import annotations
import os
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    p = Path(path) if path else ROOT / "config.yaml"
    if not p.exists():
        p = ROOT / "config.example.yaml"
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 通知先などの機密情報は環境変数から
    cfg["secrets"] = {
        "line_token": os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
        "line_user_id": os.getenv("LINE_USER_ID", ""),
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": int(os.getenv("SMTP_PORT", "465")),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_pass": os.getenv("SMTP_PASS", ""),
        "mail_to": os.getenv("MAIL_TO", ""),
    }
    return cfg


def load_universe(cfg: dict) -> list[tuple[str, str]]:
    """(code, name) のリストを返す。"""
    rel = cfg.get("universe_file", "universe/nikkei_majors.csv")
    p = ROOT / rel
    out: list[tuple[str, str]] = []
    if not p.exists():
        return out
    import csv
    with open(p, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0].strip().lower() == "code":
                continue
            code = row[0].strip()
            name = row[1].strip() if len(row) > 1 else ""
            out.append((code, name))
    return out
