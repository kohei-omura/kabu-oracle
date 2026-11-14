"""場中ランナーの時刻計画（深夜に起こされた回を朝まで生かす）のテスト。外部通信なし。"""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from kabu import session as SS

JST = timezone(timedelta(hours=9))


def jst(*a):
    return datetime(*a, tzinfo=JST)


class NextOpenTest(unittest.TestCase):
    def test_trading_day_before_open(self):
        self.assertEqual(SS.next_open(jst(2026, 11, 12, 0, 57)), jst(2026, 11, 12, 9, 5, 5))

    def test_after_close_goes_to_next_day(self):
        self.assertEqual(SS.next_open(jst(2026, 11, 12, 23, 54), close_done=True),
                         jst(2026, 11, 13, 9, 5, 5))

    def test_friday_night_goes_to_monday(self):
        self.assertEqual(SS.next_open(jst(2026, 11, 13, 23, 54), close_done=True),
                         jst(2026, 11, 16, 9, 5, 5))

    def test_skips_holiday(self):
        # 2026/11/23（月）は勤労感謝の日
        self.assertEqual(SS.next_open(jst(2026, 11, 22, 23, 30)), jst(2026, 11, 24, 9, 5, 5))


class OvernightOkTest(unittest.TestCase):
    def test_night_wake_waits(self):
        now = jst(2026, 11, 12, 23, 54)
        self.assertTrue(SS.overnight_ok(now, SS.next_open(now, True), 10))

    def test_weekend_does_not_wait(self):
        now = jst(2026, 11, 13, 23, 54)
        self.assertFalse(SS.overnight_ok(now, SS.next_open(now, True), 10))

    def test_sunday_night_waits_for_monday(self):
        now = jst(2026, 11, 15, 23, 30)
        self.assertTrue(SS.overnight_ok(now, SS.next_open(now), 10))


class FakeClock:
    def __init__(self, start):
        self.t0, self.mono = start, 0.0

    def now(self):
        return self.t0 + timedelta(seconds=self.mono)

    def monotonic(self):
        return self.mono

    def sleep(self, sec):
        self.mono += max(0.0, sec)


class RunLoopTest(unittest.TestCase):
    """偽の時計で run() を回し、深夜→引き継ぎ→朝の tick までの流れを確かめる。"""

    def _run(self, start, state, max_minutes=340):
        clk = FakeClock(start)
        calls = []
        fake_time = SimpleNamespace(monotonic=clk.monotonic, sleep=clk.sleep)
        cfg = {"session": {"tick_minutes": 10, "max_minutes": max_minutes, "overnight_hours": 10}}
        with mock.patch.object(SS, "time", fake_time), \
                mock.patch.object(SS.M, "now_jst", clk.now), \
                mock.patch.object(SS, "load_config", return_value=cfg), \
                mock.patch.object(SS, "_on_actions", return_value=True), \
                mock.patch.object(SS, "git_sync"), \
                mock.patch.object(SS, "backfill", return_value=0), \
                mock.patch.object(SS, "commit_push"), \
                mock.patch.object(SS, "sync_holdings", return_value=False), \
                mock.patch.object(SS, "handoff", side_effect=lambda: calls.append(("handoff", clk.now()))), \
                mock.patch.object(SS, "tick", side_effect=lambda c, s: calls.append(("tick", clk.now()))), \
                mock.patch.object(SS, "build", side_effect=lambda c, s, with_rank: calls.append(("build", clk.now()))), \
                mock.patch.object(SS.ST, "load", side_effect=lambda: state), \
                mock.patch.object(SS.ST, "save"):
            res = SS.run()
        return res, calls, clk

    def test_night_after_close_waits_then_hands_off(self):
        st = {"runs": {"2026-11-12": {"close": "15:59"}}, "alerts": {}, "levels": {}}
        res, calls, clk = self._run(jst(2026, 11, 12, 23, 54), st)
        self.assertEqual(res, "handoff")
        self.assertEqual([c[0] for c in calls], ["handoff"])
        self.assertEqual(calls[0][1], jst(2026, 11, 13, 5, 34))   # 340分後に引き継ぎ

    def test_successor_starts_ticking_at_open(self):
        st = {"runs": {}, "alerts": {}, "levels": {}}
        res, calls, clk = self._run(jst(2026, 11, 13, 5, 34), st)
        ticks = [t for k, t in calls if k == "tick"]
        self.assertTrue(ticks)
        self.assertEqual(ticks[0].strftime("%H:%M"), "09:05")      # 前場の最初から動く

    def test_friday_night_exits(self):
        st = {"runs": {"2026-11-13": {"close": "15:59"}}, "alerts": {}, "levels": {}}
        res, calls, _ = self._run(jst(2026, 11, 13, 23, 54), st)
        self.assertEqual(res, "done")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
