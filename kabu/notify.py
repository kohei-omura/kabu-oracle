"""通知: LINE Messaging API（push）とメール（SMTP）。

LINE Notify は 2025/3/31 終了のため、後継の Messaging API を使用する。
事前に LINE Developers でチャネルを作成し、
  - チャネルアクセストークン（long-lived） -> LINE_CHANNEL_ACCESS_TOKEN
  - 自分の userId                          -> LINE_USER_ID
を取得し、公式アカウントを「友だち追加」しておくこと。
"""
from __future__ import annotations
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formatdate
import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


LINE_MAX_CHARS = 4900     # 1メッセージの上限は5000文字（余裕を見て）
LINE_MAX_MSGS = 5         # 1回のpushで送れるのは5メッセージまで
LINE_LIMIT_NOTE = ("※LINE は今月の無料通数（月200通・同じ公式アカウントを使う全ボットの合計）の上限に"
                   "達したため、メールのみでお知らせしています。上限は毎月1日に戻ります。")
last_line_error = ""      # 直近の LINE 送信失敗の理由（"limit" など）


def split_text(text: str, limit: int = LINE_MAX_CHARS) -> list[str]:
    """長文を行の切れ目で limit 文字以下に分ける（途中で切り捨てない）。"""
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:            # 1行が長すぎる場合だけ行の途中で分ける
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(line[:limit]); line = line[limit:]
        cand = f"{cur}\n{line}" if cur else line
        if len(cand) > limit:
            chunks.append(cur); cur = line
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks or [""]


def send_line(token: str, user_id: str, text: str) -> bool:
    global last_line_error
    last_line_error = ""
    if not token or not user_id:
        print("[LINE] token/user_id 未設定のためスキップ")
        return False
    parts = split_text(text)
    if len(parts) > LINE_MAX_MSGS:          # それでも収まらない分は最後に注記して省略
        parts = parts[:LINE_MAX_MSGS]
        parts[-1] = parts[-1][:LINE_MAX_CHARS - 20] + "\n…（続きは画面で）"
    try:
        res = requests.post(
            LINE_PUSH_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json={"to": user_id,
                  "messages": [{"type": "text", "text": t} for t in parts]},
            timeout=15,
        )
        if res.status_code == 200:
            return True
        print(f"[LINE] 失敗 {res.status_code}: {res.text[:300]}")
        if res.status_code == 429 and "monthly limit" in res.text:
            last_line_error = "limit"
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
        port = int(port or 465)
        if port == 465:                       # SSL（Gmail の既定）
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, password)
                s.sendmail(user, [to_addr], msg.as_string())
        else:                                 # 587 など：STARTTLS
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, password)
                s.sendmail(user, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[MAIL] 例外: {e}")
        return False


def notify_all(cfg: dict, subject: str, text: str) -> None:
    if os.getenv("KABU_DRY_RUN", "").lower() in ("1", "true", "yes"):
        print(f"[DRY RUN] 通知は送らず表示のみ: {subject}（{len(text)}文字）")
        return
    sec = cfg.get("secrets", {})
    ok_line = send_line(sec.get("line_token"), sec.get("line_user_id"), text)
    body = text
    if not ok_line and last_line_error == "limit":
        body = f"{LINE_LIMIT_NOTE}\n\n{text}"   # LINE が届かない理由をメールで伝える
    ok_mail = send_email(
        sec.get("smtp_host"), sec.get("smtp_port"), sec.get("smtp_user"),
        sec.get("smtp_pass"), sec.get("mail_to"), subject, body,
    )
    print(f"通知結果: LINE={'OK' if ok_line else '-'} / MAIL={'OK' if ok_mail else '-'}")
