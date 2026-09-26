# -*- coding: utf-8 -*-
"""三表存储：ths_concept_dict / stock_concept_map / concept_members。

快照语义（行为等价红线）：表带日期快照列，读方法日期参数缺省取 MAX(date) 最新快照，
历史不清理，与同步日期解耦。schema 与 monitor database.py 原始定义逐字一致（同一库文件兼容）。
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

# 迁移钩子：同一事务/连接内被调用，返回 (migrated, dropped_watched)
MigrateHook = Callable[[sqlite3.Connection, set, Dict[str, str], Dict[str, str]], tuple]

_SECTOR_DDL = """
CREATE TABLE IF NOT EXISTS ths_concept_dict (
    concept_code  TEXT PRIMARY KEY,
    concept_name  TEXT NOT NULL,
    full_name     TEXT,
    index_code    TEXT,
    main_code     TEXT,
    thscode       TEXT,
    update_date   TEXT
);

CREATE TABLE IF NOT EXISTS stock_concept_map (
    stock_code    TEXT NOT NULL,
    concept_code  TEXT NOT NULL,
    map_date      TEXT NOT NULL,
    weight        REAL DEFAULT 1.0,
    PRIMARY KEY (stock_code, concept_code, map_date)
);
CREATE INDEX IF NOT EXISTS idx_scm_concept ON stock_concept_map(concept_code);

CREATE TABLE IF NOT EXISTS concept_members (
    concept_code  TEXT NOT NULL,
    stock_code    TEXT NOT NULL,
    stock_name    TEXT,
    member_date   TEXT NOT NULL,
    PRIMARY KEY (concept_code, stock_code, member_date)
);
CREATE INDEX IF NOT EXISTS idx_cm_concept ON concept_members(concept_code);
"""


class SectorStore:
    """三表读写；可指向任意 SQLite 库文件（monitor 沿用 sector_attribution.db）。"""

    def __init__(self, db_path: str, busy_timeout_ms: int = 5000):
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_tables()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=self.busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript(_SECTOR_DDL)

    # ========== 字典 ==========
    def save_concept_dict(self, concepts: List[Dict[str, str]], update_date: str = None):
        """保存概念板块字典"""
        update_date = update_date or datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            for c in concepts:
                conn.execute("""
                    INSERT OR REPLACE INTO ths_concept_dict
                    (concept_code, concept_name, full_name, index_code, main_code, thscode, update_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    c.get("concept_code"),
                    c.get("short_name", ""),
                    c.get("full_name", ""),
                    c.get("index_code", ""),
                    c.get("main_code", ""),
                    c.get("thscode", ""),
                    update_date
                ))

    def replace_concept_dict(self, boards: List[Dict[str, str]],
                             migrate_hook: Optional[MigrateHook] = None) -> Dict:
        """
        以枚举结果为准全量替换板块字典 + 级联清理 concept_members（同事务）。
        watched 等消费方关联表的迁移由 migrate_hook 在同一事务内完成（可空）。
        :param boards: [{"concept_code", "concept_name", "category", ...}]
        :return: {added, removed, total, migrated, dropped_watched}
        """
        update_date = datetime.now().strftime("%Y-%m-%d")
        new_codes = {b["concept_code"] for b in boards}
        new_name_map = {b["concept_code"]: b["concept_name"] for b in boards}
        migrated: list = []
        dropped_watched: list = []
        with self._connect() as conn:
            old_name_map = {r["concept_code"]: r["concept_name"]
                            for r in conn.execute("SELECT concept_code, concept_name FROM ths_concept_dict")}
            removed_codes = set(old_name_map) - new_codes
            added_codes = new_codes - set(old_name_map)

            if migrate_hook is not None:
                migrated, dropped_watched = migrate_hook(
                    conn, removed_codes, old_name_map, new_name_map)

            conn.execute("DELETE FROM ths_concept_dict")
            conn.executemany("""
                INSERT INTO ths_concept_dict
                (concept_code, concept_name, full_name, update_date)
                VALUES (?, ?, ?, ?)
            """, [
                (b["concept_code"], b["concept_name"],
                 b.get("category", "") or "", update_date)
                for b in boards
            ])

            dead_codes = sorted(removed_codes)
            if dead_codes:
                ph = ",".join("?" * len(dead_codes))
                conn.execute(f"DELETE FROM concept_members WHERE concept_code IN ({ph})", dead_codes)

        return {
            "added": len(added_codes),
            "removed": len(removed_codes),
            "total": len(new_codes),
            "migrated": migrated,
            "dropped_watched": dropped_watched,
        }

    def get_all_concept_codes(self) -> List[str]:
        """获取所有概念代码"""
        with self._connect() as conn:
            cursor = conn.execute("SELECT concept_code FROM ths_concept_dict")
            return [row["concept_code"] for row in cursor.fetchall()]

    # ========== 成分股/映射反查与名称 ==========
    def get_all_member_stock_codes(self) -> List[str]:
        """
        从成分股表反查全部 A 股股票代码（全市场股票池）。
        取最新一份快照，避免历史重复。只返回 A 股（沪深北），过滤海外代码。
        """
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT stock_code FROM concept_members
                WHERE member_date = (SELECT MAX(member_date) FROM concept_members)
                  AND (stock_code LIKE '%.SH' OR stock_code LIKE '%.SZ' OR stock_code LIKE '%.BJ')
            """)
            return [row["stock_code"] for row in cursor.fetchall()]

    def get_all_mapped_stock_codes(self) -> List[str]:
        """
        获取 stock_concept_map 中有概念映射的 A 股独立股票代码（取最新快照）。
        只返回 A 股（沪深北）。
        """
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT stock_code FROM stock_concept_map
                WHERE map_date = (SELECT MAX(map_date) FROM stock_concept_map)
                  AND (stock_code LIKE '%.SH' OR stock_code LIKE '%.SZ' OR stock_code LIKE '%.BJ')
            """)
            return [row["stock_code"] for row in cursor.fetchall()]

    def get_concept_name(self, concept_code: str) -> str:
        """获取概念名称"""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT concept_name FROM ths_concept_dict WHERE concept_code = ?",
                (concept_code,)
            )
            row = cursor.fetchone()
            return row["concept_name"] if row else concept_code

    # ========== 个股-概念映射操作 ==========
    def save_stock_concept_map(self, mappings: Dict[str, List[Dict[str, str]]], map_date: str):
        """
        保存个股-概念映射
        :param mappings: {stock_code: [{concept_name, concept_code}, ...]}
        :param map_date: 映射日期
        """
        with self._connect() as conn:
            for stock_code, concepts in mappings.items():
                # 等权分配
                weight = 1.0 / len(concepts) if concepts else 1.0
                for concept in concepts:
                    conn.execute("""
                        INSERT OR REPLACE INTO stock_concept_map
                        (stock_code, concept_code, map_date, weight)
                        VALUES (?, ?, ?, ?)
                    """, (stock_code, concept["concept_code"], map_date, weight))

    def get_stock_concepts(self, stock_code: str, map_date: str = None) -> List[Dict]:
        """
        获取某个股的概念映射
        :param map_date: 映射快照日期；不传则取最新一份（永久缓存语义）
        """
        with self._connect() as conn:
            if map_date is None:
                cursor = conn.execute("""
                    SELECT scm.concept_code, tcd.concept_name, scm.weight
                    FROM stock_concept_map scm
                    JOIN ths_concept_dict tcd ON scm.concept_code = tcd.concept_code
                    WHERE scm.stock_code = ? AND scm.map_date = (
                        SELECT MAX(map_date) FROM stock_concept_map WHERE stock_code = ?
                    )
                """, (stock_code, stock_code))
            else:
                cursor = conn.execute("""
                    SELECT scm.concept_code, tcd.concept_name, scm.weight
                    FROM stock_concept_map scm
                    JOIN ths_concept_dict tcd ON scm.concept_code = tcd.concept_code
                    WHERE scm.stock_code = ? AND scm.map_date = ?
                """, (stock_code, map_date))
            return [
                {"concept_code": row["concept_code"], "concept_name": row["concept_name"], "weight": row["weight"]}
                for row in cursor.fetchall()
            ]

    # ========== 概念成分股操作 ==========
    def save_concept_members(self, concept_code: str, members: List[Dict], member_date: str):
        """保存概念板块成分股"""
        with self._connect() as conn:
            for m in members:
                conn.execute("""
                    INSERT OR REPLACE INTO concept_members
                    (concept_code, stock_code, stock_name, member_date)
                    VALUES (?, ?, ?, ?)
                """, (concept_code, m.get("stock_code"), m.get("stock_name", ""), member_date))

    def get_concept_members(self, concept_code: str, member_date: str = None) -> List[Dict]:
        """
        获取概念板块成分股列表
        :param member_date: 成分股快照日期；不传则取最新一份（永久缓存语义）
        """
        with self._connect() as conn:
            if member_date is None:
                cursor = conn.execute("""
                    SELECT stock_code, stock_name FROM concept_members
                    WHERE concept_code = ? AND member_date = (
                        SELECT MAX(member_date) FROM concept_members WHERE concept_code = ?
                    )
                """, (concept_code, concept_code))
            else:
                cursor = conn.execute("""
                    SELECT stock_code, stock_name FROM concept_members
                    WHERE concept_code = ? AND member_date = ?
                """, (concept_code, member_date))
            return [
                {"stock_code": row["stock_code"], "stock_name": row["stock_name"]}
                for row in cursor.fetchall()
            ]

    def get_concept_members_map(self, concept_codes: List[str]) -> Dict[str, List[Dict]]:
        """批量读取各概念最新成分股快照，避免逐概念建立 SQLite 连接。"""
        if not concept_codes:
            return {}
        placeholders = ",".join("?" for _ in concept_codes)
        sql = f"""
            WITH latest AS (
                SELECT concept_code, MAX(member_date) AS member_date
                FROM concept_members
                WHERE concept_code IN ({placeholders})
                GROUP BY concept_code
            )
            SELECT cm.concept_code, cm.stock_code, cm.stock_name
            FROM concept_members cm
            JOIN latest l
              ON cm.concept_code = l.concept_code
             AND cm.member_date = l.member_date
            ORDER BY cm.concept_code, cm.stock_code
        """
        result: Dict[str, List[Dict]] = {}
        with self._connect() as conn:
            for row in conn.execute(sql, concept_codes):
                result.setdefault(row["concept_code"], []).append({
                    "stock_code": row["stock_code"],
                    "stock_name": row["stock_name"],
                })
        return result

    # ========== 消费方常用只读访问器（原 monitor 各处裸 SQL 的统一入口） ==========
    def get_concept_names(self) -> Dict[str, str]:
        """字典 code → name 全量映射（原 api_server/realtime_engine/sector_manage 裸 SQL）。"""
        with self._connect() as conn:
            return {r["concept_code"]: r["concept_name"]
                    for r in conn.execute("SELECT concept_code, concept_name FROM ths_concept_dict")}

    def get_latest_member_date(self) -> str:
        """成分股表最新快照日期，空表返回空串（原 kg_sources._latest_snapshot_date 裸 SQL）。"""
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(member_date) FROM concept_members").fetchone()
            return row[0] or ""

    def get_latest_member_stock_names(self) -> Dict[str, str]:
        """最新快照股票名映射，首个出现优先（原 realtime_engine/api_server/auction_engine 裸 SQL）。"""
        names: Dict[str, str] = {}
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT stock_code, stock_name FROM concept_members "
                "WHERE member_date = (SELECT MAX(member_date) FROM concept_members)"
            ):
                if row["stock_code"] not in names:
                    names[row["stock_code"]] = row["stock_name"]
        return names

    def get_all_member_stock_names(self) -> Dict[str, str]:
        """全历史股票名映射 MAX(stock_name)（原 theme_catalyst.build_market_historical 裸 SQL）。"""
        with self._connect() as conn:
            return {r[0]: r[1] for r in conn.execute(
                "SELECT stock_code, MAX(stock_name) FROM concept_members GROUP BY stock_code")}

    def get_latest_members_snapshot(self) -> Tuple[str, Dict[str, List[Tuple[str, str]]]]:
        """最新快照全体成分（原 theme_catalyst.theme_members_and_size 裸 SQL）。"""
        result: Dict[str, List[Tuple[str, str]]] = {}
        with self._connect() as conn:
            snap = conn.execute("SELECT MAX(member_date) FROM concept_members").fetchone()[0] or ""
            if not snap:
                return snap, result
            for row in conn.execute(
                "SELECT concept_code, stock_code, stock_name FROM concept_members WHERE member_date = ?",
                (snap,),
            ):
                result.setdefault(row["concept_code"], []).append(
                    (row["stock_code"], row["stock_name"]))
        return snap, result
