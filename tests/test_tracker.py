"""買い候補の実績トラッカーの採点テスト（合成の日足・外部通信なし）。"""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from kabu import tracker as TR


def bars(rows, start="2026-11-02"):
    idx = pd.bdate_range(start=start, periods=len(rows))
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)


def pick(**kw):
    r = {"d": "2026-11-02", "c": "1111", "n": "テスト", "rk": 1,
         "lim": 100.0, "tgt": 110.0, "stp": 95.0, "s": "open"}
    r.update(kw)
    return r


class EvaluateTest(unittest.TestCase):
    def test_no_fill_when_low_above_limit(self):
        df = bars([(100, 101, 99, 100), (102, 104, 101, 103)])
        r = TR.evaluate_one(pick(), df, "2026-11-30")
        self.assertEqual(r["s"], "nofill")

    def test_win_after_fill(self):
        df = bars([(100, 101, 99, 100), (101, 102, 99.5, 101), (103, 111, 102, 109)])
        r = TR.evaluate_one(pick(), df, "2026-11-30")
        self.assertEqual((r["s"], r["px"], r["x"]), ("win", 100.0, 110.0))
        self.assertAlmostEqual(r["ret"], 10.0)

    def test_fill_at_open_below_limit(self):
        df = bars([(100, 101, 99, 100), (98, 99, 97, 98), (99, 111, 98, 110)])
        r = TR.evaluate_one(pick(), df, "2026-11-30")
        self.assertEqual(r["px"], 98.0)

    def test_same_day_both_counts_as_loss(self):
        df = bars([(100, 101, 99, 100), (100, 112, 94, 100)])
        r = TR.evaluate_one(pick(), df, "2026-11-30")
        self.assertEqual((r["s"], r["x"]), ("loss", 95.0))

    def test_gap_down_exits_at_open(self):
        df = bars([(100, 101, 99, 100), (100, 101, 99.5, 100), (90, 92, 89, 91)])
        r = TR.evaluate_one(pick(), df, "2026-11-30")
        self.assertEqual((r["s"], r["x"]), ("loss", 90.0))

    def test_time_stop(self):
        rows = [(100, 101, 99, 100)] + [(100, 101, 99.5, 100.5)] * 25
        r = TR.evaluate_one(pick(), bars(rows), "2026-12-31")
        self.assertEqual(r["s"], "time")
        self.assertEqual(r["xd"], bars(rows).index[20].date().isoformat())

    def test_ignores_todays_partial_bar(self):
        df = bars([(100, 101, 99, 100), (100, 120, 99, 118)])
        today = df.index[1].date().isoformat()      # 当日の途中足は使わない
        r = TR.evaluate_one(pick(), df, today)
        self.assertEqual(r["s"], "open")

    def test_held_continues_next_day(self):
        df = bars([(100, 101, 99, 100), (100, 101, 99.5, 100)])
        r = TR.evaluate_one(pick(), df, "2026-11-30")
        self.assertEqual(r["s"], "held")
        df2 = bars([(100, 101, 99, 100), (100, 101, 99.5, 100), (101, 110.5, 100, 110)])
        r = TR.evaluate_one(r, df2, "2026-11-30")
        self.assertEqual(r["s"], "win")


class SummaryTest(unittest.TestCase):
    def test_wilson_bounds(self):
        lo, hi = TR.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)

    def test_summary_counts(self):
        recs = [pick(s="win", ret=10.0), pick(c="2", s="loss", ret=-5.0),
                pick(c="3", s="nofill"), pick(c="4", s="open")]
        s = TR.summary(recs)
        self.assertEqual((s["n"], s["wins"], s["open"], s["fill"]), (2, 1, 1, 67))
        self.assertEqual(s["avg"], 2.5)

    def test_record_dedupes_and_roundtrip(self):
        buys = [{"code": "1111", "name": "A", "price": 100, "target": 110, "stop": 95,
                 "ez": {"dip": 99}}, {"code": "2222", "name": "B", "price": 50,
                                       "target": None, "stop": 45}]
        recs = []
        self.assertEqual(TR.record(recs, "2026-11-02", buys), 1)
        self.assertEqual(TR.record(recs, "2026-11-02", buys), 0)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "picks.json"
            TR.save(recs, pd.Timestamp("2026-11-02").date(), p)
            self.assertEqual(TR.load(p)[0]["lim"], 99.0)


if __name__ == "__main__":
    unittest.main()
