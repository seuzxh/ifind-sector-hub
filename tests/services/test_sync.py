# -*- coding: utf-8 -*-
import os

import unittest
from unittest import mock
from ifind_sector_hub.services.sync import SectorSync
from ifind_sector_hub.integrations.ifind.client import IFindClient
from ifind_sector_hub.core.tokens import TokenStore
from ifind_sector_hub.repositories.storage import SectorStore
import tempfile


def make_sync(tmpdir):
    client = IFindClient(TokenStore(access_token="at", refresh_token="rt"))
    store = SectorStore(os.path.join(tmpdir, "s.db"))
    return SectorSync(client, store), client, store


class SyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sync, self.client, self.store = make_sync(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_members_resp(self, codes):
        """接口2 假响应：每个概念 2 只成分股；指定一个概念抛异常模拟失败。"""
        def resp_of(cc, date):
            if cc == "885BAD.TI":
                raise RuntimeError("api error")
            return {"tables": [{"table": {
                "p03473_f002": ["600519.SH", "000001.SZ"],
                "p03473_f003": ["贵州茅台", "平安银行"]}}]}
        return resp_of

    def test_sync_concept_members_failure_does_not_interrupt(self):
        codes = ["885001.TI", "885BAD.TI", "885002.TI"]
        with mock.patch.object(self.client, "get_concept_members",
                               side_effect=self._fake_members_resp(codes)):
            saved = self.sync.sync_concept_members(codes, "20260917")
        self.assertEqual(saved, 4)  # 2 个成功概念 × 2 股；失败概念不中断
        self.assertEqual(len(self.store.get_concept_members("885001.TI")), 2)
        self.assertEqual(self.store.get_concept_members("885BAD.TI"), [])

    def test_sync_concept_members_stock_filter(self):
        with mock.patch.object(self.client, "get_concept_members",
                               side_effect=lambda cc, d: {"tables": [{"table": {
                                   "p03473_f002": ["600519.SH", "AAPL.US"],
                                   "p03473_f003": ["a", "b"]}}]}):
            saved = self.sync.sync_concept_members(
                ["885001.TI"], "20260917",
                stock_filter=lambda sc: sc.endswith((".SH", ".SZ", ".BJ")))
        self.assertEqual(saved, 1)

    def test_init_concept_dict_filters_overseas(self):
        fake = [{"concept_code": c, "short_name": c[:6], "full_name": "", "index_code": "",
                 "main_code": "", "thscode": ""} for c in ["885001.TI", "861001.TI"]]
        # mock 按请求码集回数（真实接口只为请求的码返回数据）
        with mock.patch.object(
                self.client, "batch_get_concept_basic_info",
                side_effect=lambda codes, batch_size=100: [e for e in fake if e["concept_code"] in codes]) as b:
            got = self.sync.init_concept_dict(["885001.TI", "861001.TI"])
        # 海外码 861 不打接口、不入字典
        b.assert_called_once_with(["885001.TI"], batch_size=100)
        self.assertEqual(self.store.get_all_concept_codes(), ["885001.TI"])
        self.assertEqual([g["concept_code"] for g in got], ["885001.TI"])

    def test_init_concept_universe_collects_and_backfills(self):
        # 全市场 2 只股票；接口1 返回一个新概念 885777 + 一个海外概念 861777
        self.store.save_concept_dict([{"concept_code": "884001.TI", "short_name": "旧"}])
        self.store.save_concept_members("884001.TI", [
            {"stock_code": "600519.SH", "stock_name": "a"},
            {"stock_code": "000001.SZ", "stock_name": "b"}], "20260901")
        iface1 = {"600519.SH": [{"concept_name": "新概念", "concept_code": "885777.TI"},
                                {"concept_name": "海外", "concept_code": "861777.TI"}],
                  "000001.SZ": []}
        dict_info = [{"concept_code": "885777.TI", "short_name": "新概念"}]
        members_resp = {"tables": [{"table": {
            "p03473_f002": ["600519.SH"], "p03473_f003": ["a"]}}]}
        with mock.patch.object(self.client, "batch_get_stock_concepts", return_value=iface1), \
             mock.patch.object(self.client, "batch_get_concept_basic_info", return_value=dict_info), \
             mock.patch.object(self.client, "get_concept_members", return_value=members_resp):
            added = self.sync.init_concept_universe("2026-09-17")
        self.assertEqual(added, 1)  # 仅 885777 新增
        self.assertIn("885777.TI", self.store.get_all_concept_codes())
        self.assertNotIn("861777.TI", self.store.get_all_concept_codes())
        # 全市场映射已入库（海外概念被过滤）
        rows = self.store.get_stock_concepts("600519.SH")
        self.assertEqual([r["concept_code"] for r in rows], ["885777.TI"])

    def test_init_concept_universe_skip(self):
        with mock.patch.object(self.client, "batch_get_stock_concepts") as b:
            self.assertEqual(self.sync.init_concept_universe(skip=True), 0)
            b.assert_not_called()

    def test_refresh_dict_and_members_shape(self):
        fake_dict = [{"concept_code": "885001.TI", "short_name": "x"}]
        members_resp = {"tables": [{"table": {
            "p03473_f002": ["600519.SH"], "p03473_f003": ["a"]}}]}
        with mock.patch.object(self.client, "batch_get_concept_basic_info", return_value=fake_dict), \
             mock.patch.object(self.client, "get_concept_members", return_value=members_resp):
            out = self.sync.refresh_dict_and_members(["885001.TI"], "20260917")
        self.assertEqual(out, {"dict_count": 1, "member_concepts": 1,
                               "saved_records": 1, "member_date": "20260917"})


if __name__ == "__main__":
    unittest.main()
