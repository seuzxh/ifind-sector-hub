# -*- coding: utf-8 -*-

import unittest
from unittest import mock
from ifind_sector_hub.core.tokens import TokenStore
from ifind_sector_hub.integrations.ifind.client import IFindClient


def _resp(status=200, json_data=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = json_data if json_data is not None else {"errorcode": 0}
    r.raise_for_status.return_value = None
    return r


def make_client():
    return IFindClient(TokenStore(access_token="at1", refresh_token="rt1"))


class PostTests(unittest.TestCase):
    def test_post_ok(self):
        c = make_client()
        with mock.patch("ifind_sector_hub.integrations.ifind.client.requests.post", return_value=_resp()) as p:
            out = c._post("http://x/api", {"a": 1})
        self.assertEqual(out, {"errorcode": 0})
        p.assert_called_once()
        self.assertEqual(p.call_args.kwargs["headers"]["access_token"], "at1")

    def test_401_refresh_then_retry(self):
        c = make_client()
        # 第1次 401；刷新返回 new-at；第2次成功
        with mock.patch("ifind_sector_hub.integrations.ifind.client.requests.post",
                        side_effect=[_resp(status=401), _resp()]) as p, \
             mock.patch.object(c.tokens, "refresh_access_token", return_value="new-at") as rf:
            out = c._post("http://x/api", {})
        self.assertEqual(out, {"errorcode": 0})
        self.assertEqual(p.call_count, 2)
        rf.assert_called_once_with("at1")                      # 双检参数 = 旧 token
        self.assertEqual(p.call_args.kwargs["headers"]["access_token"], "new-at")  # 重试带新 token
        self.assertEqual(c.headers["access_token"], "new-at")  # client 自持 headers 已更新

    def test_retry_backoff_on_request_exception(self):
        import requests as real_requests
        c = make_client()
        exc = real_requests.exceptions.RequestException("boom")
        with mock.patch("ifind_sector_hub.integrations.ifind.client.requests.post", side_effect=[exc, exc, _resp()]) as p, \
             mock.patch("ifind_sector_hub.integrations.ifind.client.time.sleep") as sl:
            out = c._post("http://x/api", {})
        self.assertEqual(out, {"errorcode": 0})
        self.assertEqual(p.call_count, 3)          # max_retries=3
        self.assertEqual(sl.call_count, 2)
        sl.assert_any_call(1)                       # 2**1
        sl.assert_any_call(2)                       # 2**2

    def test_retry_exhausted_raises(self):
        import requests as real_requests
        c = make_client()
        exc = real_requests.exceptions.RequestException("boom")
        with mock.patch("ifind_sector_hub.integrations.ifind.client.requests.post", side_effect=exc), \
             mock.patch("ifind_sector_hub.integrations.ifind.client.time.sleep"):
            with self.assertRaises(real_requests.exceptions.RequestException):
                c._post("http://x/api", {})


class BatchTests(unittest.TestCase):
    def test_batch_get_realtime_quotation_splits_batches(self):
        c = make_client()
        codes = [f"8850{i:02d}.TI" for i in range(250)]  # 3 批（100/100/50）
        def fake_rt(batch, indicators=""):
            return {"errorcode": 0, "tables": [
                {"thscode": cc, "table": {"changeRatio": [1.0]}} for cc in batch]}
        with mock.patch.object(c, "get_realtime_quotation", side_effect=fake_rt):
            out = c.batch_get_realtime_quotation(codes, batch_size=100)
        self.assertEqual(len(out), 250)
        self.assertEqual(out["885000.TI"]["changeRatio"], 1.0)

    def test_batch_get_stock_concepts_parses_comma_separated(self):
        c = make_client()
        resp = {"errorcode": 0, "tables": [{
            "thscode": "600519.SH",
            "table": {
                "ths_the_ths_concept_index_stock": ["白酒,高端白酒"],
                "ths_the_ths_concept_index_code_stock": ["885555.TI,886666.TI"],
            }}]}
        with mock.patch.object(c, "get_stock_concepts", return_value=resp):
            out = c.batch_get_stock_concepts(["600519.SH"], "2026-09-17")
        self.assertEqual(out["600519.SH"], [
            {"concept_name": "白酒", "concept_code": "885555.TI"},
            {"concept_name": "高端白酒", "concept_code": "886666.TI"}])

    def test_batch_size_default_from_client_config(self):
        c = make_client()  # batch_size=100
        resp = {"errorcode": 0, "tables": []}
        codes = [f"60000{i}.SH" for i in range(150)]
        with mock.patch.object(c, "get_stock_concepts", return_value=resp) as g:
            c.batch_get_stock_concepts(codes, "2026-09-17")
        self.assertEqual(g.call_count, 2)  # 100 + 50


class SmartPickTests(unittest.TestCase):
    def test_smart_pick_boards_parses_table(self):
        c = make_client()
        resp = {"errorcode": 0, "tables": [{"table": {
            "指数代码": ["885001.TI", "885002.TI"],
            "指数简称": ["人工智能", "机器人"],
            "同花顺概念级别": ["概念", "概念"],
            "涨跌幅:xxx": [1.234, None],
        }}]}
        with mock.patch.object(c, "_post", return_value=resp):
            boards = c.smart_pick_boards("同花顺概念指数")
        self.assertEqual(boards[0], {"concept_code": "885001.TI", "concept_name": "人工智能",
                                     "category": "概念", "change_ratio": 1.23})
        self.assertIsNone(boards[1]["change_ratio"])

    def test_get_all_ths_boards_dedup_and_level(self):
        c = make_client()
        seen_queries = []
        def fake_sp(q):
            seen_queries.append(q)
            if q == "同花顺概念指数":
                return [{"concept_code": "885001.TI", "concept_name": "A", "category": "c", "change_ratio": None},
                        {"concept_code": "884001.TI", "concept_name": "B", "category": "c", "change_ratio": None}]
            return [{"concept_code": "884001.TI", "concept_name": "B2", "category": "c", "change_ratio": None}]
        with mock.patch.object(c, "smart_pick_boards", side_effect=fake_sp):
            boards = c.get_all_ths_boards()
        self.assertEqual(len(seen_queries), 3)
        self.assertEqual(len(boards), 2)  # 884001 去重
        # 去重保留首次出现：884001 首现于 concept 查询，level 不被后查覆盖
        self.assertEqual(boards[-1]["level"], "concept")

    def test_smart_pick_stocks_parses(self):
        c = make_client()
        resp = {"errorcode": 0, "tables": [{"table": {
            "股票代码": ["600519.SH"], "股票简称": ["贵州茅台"],
            "所属概念": ["白酒"], "涨跌幅:前复权[20260917]": [2.0]}}]}
        with mock.patch.object(c, "_post", return_value=resp):
            rows = c.smart_pick_stocks("白酒概念")
        self.assertEqual(rows, [{"stock_code": "600519.SH", "stock_name": "贵州茅台",
                                 "concepts": "白酒", "change_ratio": 2.0}])


if __name__ == "__main__":
    unittest.main()
