# -*- coding: utf-8 -*-
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from ifind_sector_hub.storage import SectorStore

BOARDS = [
    {"concept_code": "885101.TI", "concept_name": "人工智能", "category": "概念"},
    {"concept_code": "885102.TI", "concept_name": "机器人", "category": "概念"},
]


class StorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SectorStore(os.path.join(self._tmp.name, "t.db"))

    def tearDown(self):
        self._tmp.cleanup()

    # ---- 快照语义（行为等价红线 #2）----
    def test_members_latest_snapshot_semantics(self):
        self.store.save_concept_members("885101.TI", [
            {"stock_code": "600519.SH", "stock_name": "贵州茅台"}], "20260901")
        self.store.save_concept_members("885101.TI", [
            {"stock_code": "600519.SH", "stock_name": "贵州茅台"},
            {"stock_code": "000001.SZ", "stock_name": "平安银行"}], "20260910")
        # 不传日期 → MAX(member_date) 快照（且历史不清理）
        got = self.store.get_concept_members("885101.TI")
        self.assertEqual(len(got), 2)
        got = self.store.get_concept_members("885101.TI", "20260901")
        self.assertEqual(len(got), 1)
        mmap = self.store.get_concept_members_map(["885101.TI"])
        self.assertEqual(len(mmap["885101.TI"]), 2)

    def test_stock_concepts_map_semantics(self):
        self.store.save_concept_dict([{"concept_code": "885101.TI", "short_name": "人工智能"}])
        self.store.save_stock_concept_map(
            {"600519.SH": [{"concept_name": "人工智能", "concept_code": "885101.TI"}]}, "2026-09-01")
        rows = self.store.get_stock_concepts("600519.SH")
        self.assertEqual(rows[0]["concept_code"], "885101.TI")
        self.assertEqual(rows[0]["weight"], 1.0)

    # ---- replace + 级联 + 迁移钩子（红线 #3：同事务）----
    def test_replace_cascade_and_migrate_hook(self):
        # 旧字典含 885101；替换后字典只有 885999 → 885101 成为 removed，级联清成分股
        self.store.save_concept_dict([{"concept_code": "885101.TI", "short_name": "人工智能"}])
        self.store.save_concept_members("885101.TI", [
            {"stock_code": "600519.SH", "stock_name": "x"}], "20260901")
        new_boards = [
            {"concept_code": "885999.TI", "concept_name": "人工智能", "category": "概念"},
        ]

        def hook(conn, removed_codes, old_name_map, new_name_map):
            # 模拟 monitor 的 watched 迁移：名称匹配新码后 UPDATE 关联表
            self.assertEqual(removed_codes, {"885101.TI"})
            self.assertEqual(old_name_map.get("885101.TI"), "人工智能")
            conn.execute("CREATE TABLE IF NOT EXISTS watched_concepts "
                         "(concept_code TEXT PRIMARY KEY, added_at TEXT NOT NULL)")
            conn.execute("INSERT OR REPLACE INTO watched_concepts VALUES ('885101.TI', 'now')")
            conn.execute("UPDATE watched_concepts SET concept_code='885999.TI' "
                         "WHERE concept_code='885101.TI'")
            return [("885101.TI", "885999.TI", "人工智能")], []

        result = self.store.replace_concept_dict(new_boards, migrate_hook=hook)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["migrated"], [("885101.TI", "885999.TI", "人工智能")])
        # 字典已替换
        self.assertEqual(self.store.get_all_concept_codes(), ["885999.TI"])
        # 级联清理：被移除旧码的成分股已删
        self.assertEqual(self.store.get_concept_members("885101.TI"), [])
        self.assertEqual(self.store.get_concept_name("885999.TI"), "人工智能")

    def test_replace_without_hook_keeps_unchanged_members(self):
        # 无钩子；885101 在新旧字典都在（BOARDS 含它）→ 不属 removed，成分股保留
        self.store.save_concept_dict([{"concept_code": "885101.TI", "short_name": "人工智能"}])
        self.store.save_concept_members("885101.TI", [
            {"stock_code": "600519.SH", "stock_name": "x"}], "20260901")
        result = self.store.replace_concept_dict(BOARDS)
        self.assertEqual(result["migrated"], [])
        self.assertEqual(result["dropped_watched"], [])
        self.assertNotEqual(self.store.get_concept_members("885101.TI"), [])

    # ---- 新增访问器 ----
    def test_new_accessors(self):
        self.store.save_concept_dict([{"concept_code": "885101.TI", "short_name": "人工智能"}])
        self.store.save_concept_members("885101.TI", [
            {"stock_code": "600519.SH", "stock_name": "贵州茅台"}], "20260901")
        self.store.save_concept_members("885102.TI", [
            {"stock_code": "000001.SZ", "stock_name": "平安银行"}], "20260905")
        self.assertEqual(self.store.get_concept_names(), {"885101.TI": "人工智能"})
        self.assertEqual(self.store.get_latest_member_date(), "20260905")
        # 最新快照（20260905）只有 000001；600519 只在旧快照 → 不在最新名称映射
        self.assertNotIn("600519.SH", self.store.get_latest_member_stock_names())
        self.assertIn("000001.SZ", self.store.get_latest_member_stock_names())
        # 全历史名称映射两者都有
        self.assertEqual(self.store.get_all_member_stock_names(),
                         {"600519.SH": "贵州茅台", "000001.SZ": "平安银行"})
        snap, mmap = self.store.get_latest_members_snapshot()
        self.assertEqual(snap, "20260905")
        self.assertEqual(mmap, {"885102.TI": [("000001.SZ", "平安银行")]})


class AShareFilterTests(unittest.TestCase):
    def test_get_all_member_stock_codes_filters_a_share(self):
        with tempfile.TemporaryDirectory() as d:
            store = SectorStore(os.path.join(d, "t.db"))
            store.save_concept_members("885101.TI", [
                {"stock_code": "600519.SH", "stock_name": "a"},
                {"stock_code": "AAPL.US", "stock_name": "b"}], "20260901")
            self.assertEqual(store.get_all_member_stock_codes(), ["600519.SH"])


if __name__ == "__main__":
    unittest.main()
