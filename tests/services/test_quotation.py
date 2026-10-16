# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import date

from ifind_sector_hub.repositories.quotation import QuotationRepository
from ifind_sector_hub.services.quotation import CALENDAR_SOURCE_CODE, QuotationService


class _StubClient:
    """返回固定日线序列的桩 client（不打网络）。"""

    def __init__(self, dates):
        self._dates = dates
        self.calls = []

    def fetch_daily_bars(self, code, start, end):
        self.calls.append((code, start, end))
        return [{"code": code, "time": d} for d in self._dates
                if start <= d <= end]


class QuotationServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = QuotationRepository(os.path.join(self._tmp.name, "q.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_calendar(self):
        stub = _StubClient(["2026-01-05", "2026-01-06", "2026-01-09"])
        svc = QuotationService(stub, self.repo)
        total = svc.seed_calendar()
        self.assertEqual(total, 3)
        self.assertEqual(stub.calls[0][0], CALENDAR_SOURCE_CODE)  # 用上证指数做日历源
        self.assertEqual(self.repo.get_trading_dates("2026-01-01", "2026-01-31"),
                         ["2026-01-05", "2026-01-06", "2026-01-09"])
        # 幂等重播
        self.assertEqual(svc.seed_calendar(), 3)

    def test_lookback_start_about_five_years(self):
        svc = QuotationService(_StubClient([]), self.repo, lookback_years=5)
        start = date.fromisoformat(svc.lookback_start())
        delta = (date.today() - start).days
        self.assertGreater(delta, 365 * 5)      # 至少回看 5 年
        self.assertLess(delta, 365 * 5 + 60)    # 余量不超过 60 天


if __name__ == "__main__":
    unittest.main()
