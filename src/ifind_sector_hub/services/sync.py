# -*- coding: utf-8 -*-
"""板块数据同步编排：字典 / 成分股 / 个股-概念映射。

并发内核与日志行为自 monitor sync_pipeline.py 原样迁移（线程池逐概念拉接口2，
失败概念不中断，进度计数带锁）。
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Dict, List, Optional

from ..core.codes import is_a_share_code, is_a_share_concept


class SectorSync:
    def __init__(self, client, store,
                 concurrency: int = 8, progress_every: int = 100):
        self.client = client
        self.store = store
        self.concurrency = concurrency
        self.progress_every = progress_every

    # ---------- 单概念成分股（线程池 worker） ----------
    def _fetch_one_concept_members(self, concept_code: str, member_date: str,
                                   stock_filter: Optional[Callable[[str], bool]] = None):
        """
        拉取单个概念的成分股。
        :return: (concept_code, members) 成功；(concept_code, None) 失败
        """
        try:
            resp = self.client.get_concept_members(concept_code, member_date)
            if not isinstance(resp, dict):
                raise ValueError("响应不是对象")
            tables = resp.get("tables")
            if not isinstance(tables, list) or not tables:
                raise ValueError("响应缺少 tables")
            table = tables[0].get("table") if isinstance(tables[0], dict) else None
            if not isinstance(table, dict):
                raise ValueError("响应缺少 table")
            stock_codes = table.get("p03473_f002")
            stock_names = table.get("p03473_f003")
            if not isinstance(stock_codes, list) or not isinstance(stock_names, list):
                raise ValueError("成分股字段不是列表")
            if len(stock_codes) != len(stock_names):
                raise ValueError("成分股代码与名称数量不一致")
            members = []
            seen_codes = set()
            for sc, stock_name in zip(stock_codes, stock_names):
                if not isinstance(sc, str) or not sc.strip():
                    raise ValueError("成分股代码为空或类型错误")
                if sc in seen_codes:
                    raise ValueError(f"成分股代码重复: {sc}")
                if not isinstance(stock_name, str):
                    raise ValueError(f"成分股名称类型错误: {sc}")
                seen_codes.add(sc)
                if stock_filter is not None and not stock_filter(sc):
                    continue
                members.append({
                    "stock_code": sc,
                    "stock_name": stock_name,
                })
            return (concept_code, members)
        except Exception as e:
            print(f"[WARN] 获取 {concept_code} 成分股失败: {e}")
            return (concept_code, None)

    # ---------- 并发内核（原 _fetch_concept_members_batch） ----------
    def sync_concept_members(self, concept_codes: List[str], member_date: str,
                             stock_filter: Optional[Callable[[str], bool]] = None) -> int:
        """并发拉取给定概念列表的成分股并入库，返回入库条数（失败概念不中断）。"""
        report = self.sync_concept_members_report(
            concept_codes, member_date, stock_filter=stock_filter)
        return report["saved_records"]

    def sync_concept_members_report(
            self, concept_codes: List[str], member_date: str,
            stock_filter: Optional[Callable[[str], bool]] = None) -> Dict:
        """同步成分股并返回逐批次结果；失败概念不会覆盖上一份快照。"""
        total = len(concept_codes)
        done_count = saved_records = success_count = 0
        counter_lock = threading.Lock()
        failed_codes = []

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_to_code = {
                executor.submit(self._fetch_one_concept_members, cc, member_date, stock_filter): cc
                for cc in concept_codes
            }
            for future in as_completed(future_to_code):
                code, members = future.result()
                if members is None:
                    failed_codes.append(code)
                else:
                    self.store.save_concept_members(code, members, member_date)
                    success_count += 1
                    saved_records += len(members)
                with counter_lock:
                    done_count += 1
                    if done_count % self.progress_every == 0 or done_count == total:
                        print(f"[UNIVERSE] 成分股进度 {done_count}/{total}"
                              f"（成功 {success_count}，失败 {len(failed_codes)}，已入库 {saved_records} 条）")

        print(f"[UNIVERSE] 已保存共 {saved_records} 条成分股记录"
              f"（{total} 个概念中成功 {success_count} 个，失败 {len(failed_codes)} 个）")
        if failed_codes:
            preview = ", ".join(failed_codes[:20])
            more = "" if len(failed_codes) <= 20 else f" ...（共 {len(failed_codes)} 个）"
            print(f"[UNIVERSE] 失败概念码: {preview}{more}")
        failed_codes.sort()
        return {
            "ok": not failed_codes,
            "member_date": member_date,
            "requested_concepts": total,
            "successful_concepts": success_count,
            "failed_concepts": len(failed_codes),
            "failed_codes": failed_codes,
            "saved_records": saved_records,
        }

    # ---------- 字典 ----------
    def init_concept_dict(self, concept_codes: List[str]) -> List[Dict]:
        """初始化/刷新板块字典（接口5，永久缓存；内部过滤海外概念）。"""
        print("[INIT] 开始初始化概念板块字典...")
        a_share_codes = [c for c in concept_codes if is_a_share_concept(c)]
        skipped = len(concept_codes) - len(a_share_codes)
        if skipped:
            print(f"[INIT] 过滤 {skipped} 个海外行业指数概念，仅保留 A股概念 {len(a_share_codes)} 个")
        concepts = self.client.batch_get_concept_basic_info(a_share_codes, batch_size=100)
        self.store.save_concept_dict(concepts)
        print(f"[INIT] 已保存 {len(concepts)} 个概念板块到字典")
        return concepts

    # ---------- 个股-概念映射 ----------
    def sync_stock_concept_map(self, stock_codes: List[str], map_date: str = None) -> Dict:
        map_date = map_date or datetime.now().strftime("%Y-%m-%d")
        print(f"[INIT] 开始初始化个股-概念映射，日期={map_date}...")
        mappings = self.client.batch_get_stock_concepts(stock_codes, map_date)
        self.store.save_stock_concept_map(mappings, map_date)
        print(f"[INIT] 已保存 {len(mappings)} 只个股的概念映射")
        return mappings

    # ---------- 概念全集补全（原 init_concept_universe） ----------
    def init_concept_universe(self, map_date: str = None, skip: bool = False,
                              batch_size: int = 100,
                              existing_codes: Optional[set] = None) -> int:
        """
        扫全市场股票收集实际在用概念码（885/886 等），补全字典与成分股。
        :param skip: 调用方要求跳过（原"板块池启用仅 884"开关）
        :param existing_codes: 调用方口径的"已参与"码集；缺省用字典全集
        :return: 新增概念码数量
        """
        if skip:
            print("[UNIVERSE] 板块池已启用（仅 884），跳过 885/886 概念扫描")
            return 0
        print("=" * 60)
        print("  补全概念板块全集（扫描全市场股票）")
        print("=" * 60)
        map_date = map_date or datetime.now().strftime("%Y-%m-%d")

        all_stocks = self.store.get_all_member_stock_codes()
        print(f"[UNIVERSE] 全市场股票 {len(all_stocks)} 只")

        collected: Dict[str, str] = {}
        all_mappings: Dict[str, list] = {}
        for i in range(0, len(all_stocks), batch_size):
            batch = all_stocks[i:i + batch_size]
            mappings = self.client.batch_get_stock_concepts(batch, map_date)
            for stock_code, concepts in mappings.items():
                a_concepts = [c for c in concepts if is_a_share_concept(c.get("concept_code", ""))]
                if a_concepts:
                    all_mappings[stock_code] = a_concepts
                    for c in a_concepts:
                        cc = c.get("concept_code")
                        if cc and cc not in collected:
                            collected[cc] = c.get("concept_name", "")
            if (i // batch_size) % 5 == 0:
                print(f"[UNIVERSE] 扫描进度 {min(i + batch_size, len(all_stocks))}/{len(all_stocks)}"
                      f"，已收集 A股概念码 {len(collected)}，映射 {len(all_mappings)} 只")
        print(f"[UNIVERSE] 扫描完成，共收集 A股概念码 {len(collected)} 个，映射 {len(all_mappings)} 只股票")

        self.store.save_stock_concept_map(all_mappings, map_date)
        print(f"[UNIVERSE] 已更新 stock_concept_map：{len(all_mappings)} 只股票")

        if existing_codes is None:
            existing_codes = set(self.store.get_all_concept_codes())
        new_codes = [cc for cc in collected
                     if cc not in existing_codes and is_a_share_concept(cc)]
        print(f"[UNIVERSE] 其中字典里已有的: {len(collected) - len(new_codes)}，需新增: {len(new_codes)}")
        if not new_codes:
            print("[UNIVERSE] 无需补充，概念字典已覆盖")
            return 0

        print(f"[UNIVERSE] 调用接口5 补全 {len(new_codes)} 个概念的字典信息...")
        concepts_info = self.client.batch_get_concept_basic_info(new_codes, batch_size=100)
        self.store.save_concept_dict(concepts_info)
        print(f"[UNIVERSE] 字典已补全 {len(concepts_info)} 个概念")

        print(f"[UNIVERSE] 调用接口2 补全 {len(new_codes)} 个概念的成分股...")
        today_compact = datetime.now().strftime("%Y%m%d")
        self.sync_concept_members(new_codes, today_compact, stock_filter=is_a_share_code)

        print("=" * 60)
        print("  概念板块全集补全完成")
        print("=" * 60)
        return len(new_codes)

    # ---------- 观察池刷新（原 refresh_observe_members 的数据侧） ----------
    def refresh_dict_and_members(self, concept_codes: List[str], member_date: str = None) -> Dict:
        """对给定码集刷字典（接口5）+ 成分股（接口2 并发），返回统计。"""
        member_date = member_date or datetime.now().strftime("%Y%m%d")
        print(f"[REFRESH] 开始刷新观察池板块信息，日期={member_date}...")
        a_share_codes = [c for c in concept_codes if is_a_share_concept(c)]
        concepts = self.client.batch_get_concept_basic_info(a_share_codes, batch_size=100)
        self.store.save_concept_dict(concepts)
        print(f"[REFRESH] 字典已刷新 {len(concepts)} 个概念")
        saved = self.sync_concept_members(concept_codes, member_date, stock_filter=is_a_share_code)
        print(f"[REFRESH] 完成：{len(concept_codes)} 个概念，{saved} 条成分股记录")
        return {"dict_count": len(concepts), "member_concepts": len(concept_codes),
                "saved_records": saved, "member_date": member_date}
