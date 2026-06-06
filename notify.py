"""通知: LINE Messaging API（push）とメール（SMTP）。

LINE Notify は 2025/3/31 終了のため、後継の Messaging API を使用する。
事前に LINE Developers でチャネルを作成し、
  - チャネルアクセストークン（long-lived） -> LINE_CHANNEL_ACCESS_TOKEN
  - 自分の userId                          -> LINE_USER_ID
を取得し、公式アカウントを「友だち追加」しておくこと。
"""
from __future__ import annotations
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formatdate
import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send_line(token: str, user_id: str, text: str) -> bool:
    if not token or not user_id:
        print("[LINE] token/user_id 未設定のためスキップ")
        return False
    # LINE の1メッセージ上限は5000文字
    text = text[:4900]
    try:
        res = requests.post(
            LINE_PUSH_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=15,
        )
        if res.status_code == 200:
            return True
        print(f"[LINE] 失敗 {res.status_code}: {res.text[:300]}")
        return False
    except Exception as e:
        print(f"[LINE] 例外: {e}")
        return False


def send_email(host: str, port: int, user: str, password: str,
               to_addr: str, subject: str, body: str) -> bool:
    if not (host and user and password and to_addr):
        print("[MAIL] SMTP 未設定のためスキップ")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            s.login(user, password)
            s.sendmail(user, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[MAIL] 例外: {e}")
        return False


def notify_all(cfg: dict, subject: str, text: str) -> None:
    sec = cfg.get("secrets", {})
    ok_line = send_line(sec.get("line_token"), sec.get("line_user_id"), text)
    ok_mail = send_email(
        sec.get("smtp_host"), sec.get("smtp_port"), sec.get("smtp_user"),
        sec.get("smtp_pass"), sec.get("mail_to"), subject, text,
    )
    print(f"通知結果: LINE={'OK' if ok_line else '-'} / MAIL={'OK' if ok_mail else '-'}")
