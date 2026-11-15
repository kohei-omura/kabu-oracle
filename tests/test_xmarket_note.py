"""ランキング通知に添える「株×FX地合い」（report.xmarket_note）のテスト。ネットワーク不要。
FX Navi・Carry Navi・GLOBE ORACLE のファイルが読めなくても通知は従来どおり、読めた時だけ2行足す。"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kabu import report as REP
from kabu import xmarket as XM

JST = timezone(timedelta(hours=9))


def now(fmt):
    return datetime.now(JST).strftime(fmt)


class XmarketNoteTest(unittest.TestCase):
    def setUp(self):
        self.docs = Path(tempfile.mkdtemp())
        p = mock.patch.object(REP, "DOCS", self.docs)
        p.start()
        self.addCleanup(p.stop)

    def _data(self, label="上昇基調"):
        (self.docs / "data.json").write_text(json.dumps(
            {"generated": now("%Y.%m.%d %H:%M"), "regime": {"label": label, "chg20": 4.0, "chg1": 0.5, "price": 61000}},
            ensure_ascii=False), encoding="utf-8")

    def test_empty_when_fx_apps_unreadable(self):
        self._data()
        with mock.patch.object(XM, "_get_json", return_value=None):
            self.assertEqual(REP.xmarket_note(), "")

    def test_empty_when_fetch_raises(self):
        self._data()
        with mock.patch.object(XM, "_get_json", side_effect=ConnectionError("down")):
            self.assertEqual(REP.xmarket_note(), "")

    def test_two_lines_with_fx_data(self):
        self._data("上昇基調")
        seen = []

        def fake(url):
            seen.append(url)
            if "FX-Signal-Notifier" in url:
                return {"generated_at": now("%Y-%m-%d %H:%M JST"), "pairs": [
                    {"symbol": s, "bid": 150.0, "mtf": {"1hour": 1, "4hour": 1}} for s in ("USD_JPY", "EUR_JPY")]}
            return None
        with mock.patch.object(XM, "_get_json", side_effect=fake):
            t = REP.xmarket_note()
        self.assertTrue(t.startswith("\n\n🌐 株×FX地合い: ☀ リスクオン（株:強い／円:円安）"), t)
        self.assertIn("輸出株", t)
        self.assertFalse(any("kabu-oracle" in u for u in seen))    # 自分の分は取りに行かない


if __name__ == "__main__":
    unittest.main()
