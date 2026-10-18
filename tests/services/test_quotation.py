# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import date

from ifind_sector_hub.repositories.quotation import QuotationRepository
from ifind_sector_hub.services.quotation import CALENDAR_END, CALENDAR_START, QuotationService


class _StubClient:
    """返回固定日历的桩 client（不打网络）。"""

    def __init__(self, dates):
        self._dates = dates
        self.calls = []

    def get_trade_dates(self, start, end, marketcode="212001"):
        self.calls.append((start, end, marketcode))
        return [d for d in self._dates if start <= d <= end]


class QuotationServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = QuotationRepository(os.path.join(self._tmp.name, "q.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_calendar_default_full_range(self):
        stub = _StubClient(["2020-01-02", "2026-01-05", "2028-12-29"])
        svc = QuotationService(stub, self.repo)
        total = svc.seed_calendar()
        self.assertEqual(total, 3)
        # 默认播种范围 2020-01-01 ~ 2028-12-31 全覆盖（单次接口）
        self.assertEqual(stub.calls[0][:2], (CALENDAR_START, CALENDAR_END))
        self.assertEqual(stub.calls[0][2], "212001")  # A股市场码
        self.assertEqual(self.repo.calendar_bounds(), ("2020-01-02", "2028-12-29"))
        # 幂等重播
        self.assertEqual(svc.seed_calendar(), 3)

    def test_seed_calendar_custom_range(self):
        stub = _StubClient(["2026-01-05"])
        svc = QuotationService(stub, self.repo)
        svc.seed_calendar(start="2026-01-01", end="2026-01-31")
        self.assertEqual(stub.calls[0][:2], ("2026-01-01", "2026-01-31"))

    def test_lookback_start_about_five_years(self):
        svc = QuotationService(_StubClient([]), self.repo, lookback_years=5)
        start = date.fromisoformat(svc.lookback_start())
        delta = (date.today() - start).days
        self.assertGreater(delta, 365 * 5)      # 至少回看 5 年
        self.assertLess(delta, 365 * 5 + 60)    # 余量不超过 60 天


if __name__ == "__main__":
    unittest.main()
