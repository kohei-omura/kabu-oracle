"""東証の営業日・取引時間。

- 休場日: 土日・祝日（jpholiday）・年末年始（12/31〜1/3）
- 取引時間: 前場 9:00〜11:30 / 後場 12:30〜15:30（2024/11/5 以降の大引け）
- yfinance の株価は約20分遅れなので、「データ上の時刻」は DATA_DELAY だけ前にずらして扱う
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta, timezone

try:
    import jpholiday
except Exception:  # noqa  ライブラリが無くても土日と年末年始だけは判定する
    jpholiday = None

JST = timezone(timedelta(hours=9))
AM_OPEN, AM_CLOSE = time(9, 0), time(11, 30)
PM_OPEN, PM_CLOSE = time(12, 30), time(15, 30)
SESSION_MINUTES = 150 + 180
DATA_DELAY = timedelta(minutes=20)


def now_jst() -> datetime:
    return datetime.now(JST)


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    if (d.month, d.day) in ((12, 31), (1, 1), (1, 2), (1, 3)):
        return False
    if jpholiday is not None and jpholiday.is_holiday(d):
        return False
    return True


def closed_reason(d: date) -> str:
    """休場の理由（営業日なら空文字）。ログ表示用。"""
    if d.weekday() >= 5:
        return "土日"
    if (d.month, d.day) in ((12, 31), (1, 1), (1, 2), (1, 3)):
        return "年末年始"
    if jpholiday is not None:
        name = jpholiday.is_holiday_name(d)
        if name:
            return name
    return ""


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def session_progress(at: datetime) -> float:
    """その日の取引時間のうち何割が経過したか（0.0〜1.0）。休場日・寄り前は0、大引け後は1。"""
    if not is_trading_day(at.date()):
        return 0.0
    m = at.hour * 60 + at.minute
    if m < _minutes(AM_OPEN):
        return 0.0
    if m <= _minutes(AM_CLOSE):
        done = m - _minutes(AM_OPEN)
    elif m < _minutes(PM_OPEN):
        done = 150
    elif m <= _minutes(PM_CLOSE):
        done = 150 + (m - _minutes(PM_OPEN))
    else:
        return 1.0
    return done / SESSION_MINUTES


def partial_bar_progress(last_bar_day: date, now: datetime | None = None) -> float:
    """日足の最終行が「形成途中の当日足」なら、その完成度（0〜1）を返す。確定足なら 1.0。

    場中に取った日足の最終行は当日の途中経過で、出来高が1日分に満たない。
    データ遅延を考慮した時刻で判定する。
    """
    now = now or now_jst()
    data_time = now - DATA_DELAY
    if last_bar_day != data_time.date():
        return 1.0
    return session_progress(data_time) or 1.0
