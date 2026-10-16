# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from ifind_sector_hub.repositories.quotation import (
    COVERAGE_COMPLETE, COVERAGE_EMPTY, QuotationRepository)


def _bars_daily(code, dates):
    return [{"code": code, "time": d, "open": 1.0, "high": 2.0, "low": 0.5,
             "close": 1.5, "volume": 100, "amount": 200.0,
             "changeRatio": 0.5, "preClose": 1.4} for d in dates]


class QuotationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = QuotationRepository(os.path.join(self._tmp.name, "q.db"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_daily_upsert_and_read_idempotent(self):
        bars = _bars_daily("885001.TI", ["2026-01-05", "2026-01-06"])
        self.assertEqual(self.repo.upsert_daily_bars(bars), 2)
        self.repo.upsert_daily_bars(bars)  # 幂等重跑
        rows = self.repo.read_daily_bars("885001.TI", "2026-01-01", "2026-01-31")
        self.assertEqual([r["trade_date"] for r in rows], ["2026-01-05", "2026-01-06"])
        self.assertEqual(rows[0]["change_ratio"], 0.5)  # changeRatio → change_ratio 归一化
        self.assertEqual(self.repo.read_daily_bars("999999.TI", "2026-01-01", "2026-12-31"), [])

    def test_minute_upsert_and_read(self):
        bars = [{"code": "885001.TI", "time": "2026-01-05 09:31", "open": 1.0,
                 "high": 1.2, "low": 0.9, "close": 1.1, "volume": 10, "changeRatio": 0.1}]
        self.repo.upsert_minute_bars(bars)
        rows = self.repo.read_minute_bars("885001.TI", "2026-01-05", "2026-01-06")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bar_time"], "2026-01-05 09:31")

    def test_coverage_upsert_and_get(self):
        self.repo.upsert_coverage("885001.TI", "1d", ["2026-01-05"], COVERAGE_COMPLETE)
        self.repo.upsert_coverage("885001.TI", "1d", ["2026-01-06"], COVERAGE_EMPTY)
        cov = self.repo.get_coverage("885001.TI", "1d", "2026-01-01", "2026-01-31")
        # complete 与 empty 都算"已确认"；缺失日（如 01-07）无行
        self.assertEqual(cov, {"2026-01-05": "complete", "2026-01-06": "empty"})

    def test_calendar_seed_and_query(self):
        total = self.repo.seed_calendar(["2026-01-05", "2026-01-06", "2026-01-09"])
        self.assertEqual(total, 3)
        self.repo.seed_calendar(["2026-01-06"])  # 幂等
        self.assertEqual(self.repo.calendar_bounds(), ("2026-01-05", "2026-01-09"))
        self.assertEqual(self.repo.get_trading_dates("2026-01-06", "2026-01-08"),
                         ["2026-01-06"])  # 区间内仅交易日，周末自然缺席

    def test_enqueue_fill_dedup_and_lifecycle(self):
        tid = self.repo.enqueue_fill("885001.TI", "1d", "2026-01-05", "2026-03-31")
        self.assertIsNotNone(tid)
        # 与 pending 任务区间重叠 → 不重复投递
        self.assertIsNone(self.repo.enqueue_fill("885001.TI", "1d", "2026-02-01", "2026-02-28"))
        # 不同 code 不受影响
        self.assertIsNotNone(self.repo.enqueue_fill("881121.TI", "1d", "2026-02-01", "2026-02-28"))

        tasks = self.repo.claim_pending_tasks(limit=10)
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t["status"] == "pending" for t in tasks))  # 返回快照为领取前状态
        self.assertEqual([t["status"] for t in self.repo.list_tasks(status="running")],
                         ["running", "running"])
        self.repo.finish_task(tasks[0]["task_id"], "done")
        self.repo.finish_task(tasks[1]["task_id"], "failed", error="boom")
        done = {t["task_id"]: t for t in self.repo.list_tasks()}
        self.assertEqual(done[tasks[0]["task_id"]]["status"], "done")
        self.assertEqual(done[tasks[1]["task_id"]]["last_error"], "boom")
        self.assertEqual(done[tasks[1]["task_id"]]["attempts"], 1)
        # 全部终态后可重新投递
        self.assertIsNotNone(self.repo.enqueue_fill("885001.TI", "1d", "2026-01-05", "2026-03-31"))


if __name__ == "__main__":
    unittest.main()
