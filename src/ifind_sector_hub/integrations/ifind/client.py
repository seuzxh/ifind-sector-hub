# -*- coding: utf-8 -*-
"""
iFinD API 客户端封装（ifind-sector-hub 数据源层）。
支持 5 个核心接口 + smart_stock_picking 特色接口；token 生命周期交给 TokenStore。

接口清单：
  1. basic_data_service - 个股所属同花顺概念
  2. data_pool (p03473) - 概念板块成分股
  3. cmd_history_quotation - 历史行情日K
  4. high_frequency - 高频序列1min K
  5. basic_data_service - 概念基本信息（字典初始化）
"""

import time
import requests
from typing import List, Dict, Optional, Any

from ...core.tokens import TokenStore


class IFindClient:
    """iFinD API 客户端（配置注入，token 由 TokenStore 管理，headers 自持）。"""

    def __init__(self, tokens: TokenStore,
                 base_url_quant: str = "https://quantapi.51ifind.com/api/v1",
                 base_url_ft: str = "https://ft.10jqka.com.cn/api/v1",
                 timeout: int = 30,
                 max_retries: int = 3,
                 batch_size: int = 100):
        self.tokens = tokens
        self.base_url_quant = base_url_quant
        self.base_url_ft = base_url_ft
        self.timeout = timeout
        self.max_retries = max_retries
        self.batch_size = batch_size
        self.headers = {"Content-Type": "application/json", "access_token": tokens.access_token}

    def _post(self, url: str, payload: dict) -> dict:
        """带重试的 POST。HTTP 401 时经 TokenStore 刷新（双检锁）后重试本轮（仅一次，防死循环）。"""
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=self.headers, json=payload, timeout=self.timeout)
                if resp.status_code == 401:
                    self.headers["access_token"] = self.tokens.refresh_access_token(
                        self.headers["access_token"])
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise RuntimeError("iFinD API response is not a JSON object")
                errorcode = data.get("errorcode")
                if errorcode not in (0, None):
                    errmsg = data.get("errmsg") or data.get("message") or "unknown error"
                    raise RuntimeError(f"iFinD API error {errorcode}: {errmsg}")
                return data
            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
        return {}

    # ========== 接口1: 个股所属同花顺概念 ==========
    def get_stock_concepts(self, stock_codes: List[str], date: str) -> dict:
        """
        获取个股所属同花顺概念板块
        :param stock_codes: 股票代码列表，如 ["688001.SH", "600004.SH"]
        :param date: 查询日期，如 "2026-06-13"
        :return: API 原始响应
        """
        url = f"{self.base_url_quant}/basic_data_service"
        codes_str = ",".join(stock_codes)
        payload = {
            "codes": codes_str,
            "indipara": [
                {
                    "indicator": "ths_the_ths_concept_index_stock",
                    "indiparams": [date]
                },
                {
                    "indicator": "ths_the_ths_concept_index_code_stock",
                    "indiparams": [date]
                }
            ]
        }
        return self._post(url, payload)

    # ========== 接口2: 概念板块成分股 ==========
    def get_concept_members(self, concept_code: str, date: str) -> dict:
        """
        获取同花顺概念板块成分股（p03473）
        :param concept_code: 概念指数代码，如 "886102.TI"
        :param date: 查询日期，如 "20260613"
        :return: API 原始响应
        """
        url = f"{self.base_url_quant}/data_pool"
        payload = {
            "reportname": "p03473",
            "functionpara": {
                "iv_date": date,
                "iv_zsdm": concept_code
            },
            "outputpara": "p03473_f001,p03473_f002,p03473_f003"
        }
        return self._post(url, payload)

    # ========== 接口3: 历史行情日K ==========
    def get_history_quotation(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        indicators: str = "preClose,open,high,low,close,changeRatio",
        interval: str = "D",
        cps: Optional[str] = "6"
    ) -> dict:
        """
        获取历史行情日K线
        :param codes: 股票/指数代码列表
        :param start_date: 开始日期，如 "2026-06-01"
        :param end_date: 结束日期，如 "2026-06-13"
        :param indicators: 指标列表，逗号分隔
        :param interval: 周期，D=日 W=周 M=月
        :param cps: 复权方式，6=前复权(现金分红)
        :return: API 原始响应
        """
        url = f"{self.base_url_ft}/cmd_history_quotation"
        funcpara = {"Fill": "Previous", "Interval": interval}
        if cps is not None:
            funcpara["CPS"] = cps
        codes_str = ",".join(codes)
        payload = {
            "codes": codes_str,
            "indicators": indicators,
            "startdate": start_date,
            "enddate": end_date,
            "functionpara": funcpara
        }
        return self._post(url, payload)

    # ========== 接口4: 高频序列1min K ==========
    def get_high_frequency(
        self,
        codes: List[str],
        start_time: str,
        end_time: str,
        indicators: str = "open,high,low,close,changeRatio"
    ) -> dict:
        """
        获取高频序列（1min K线）
        :param codes: 股票/指数代码列表
        :param start_time: 开始时间，如 "2026-06-13 09:30:00"
        :param end_time: 结束时间，如 "2026-06-13 10:00:00"
        :param indicators: 指标列表
        :return: API 原始响应
        """
        url = f"{self.base_url_ft}/high_frequency"
        codes_str = ",".join(codes)
        payload = {
            "codes": codes_str,
            "indicators": indicators,
            "starttime": start_time,
            "endtime": end_time,
            "functionpara": {}
        }
        return self._post(url, payload)

    # ========== 接口6: 实时行情快照 ==========
    def get_realtime_quotation(
        self,
        codes: List[str],
        indicators: str = "changeRatio,open,latest,riseCount,fallCount,upLimitCount"
    ) -> dict:
        """
        获取实时行情快照（THS_RQ）。盘中返回实时值，收盘后返回当日收盘值。
        :param codes: 股票/指数代码列表
        :param indicators: 指标列表，逗号分隔。常用：
            latest(最新价) / changeRatio(涨跌幅%) / change(涨跌) / open / preClose /
            high / low / swing(振幅%) / amount(成交额) / volume(成交量) /
            riseCount(上涨家数) / fallCount(下跌家数) / upLimitCount(涨停家数) /
            tradeTime / tradeDate
        :return: API 原始响应（tables[].table 里每个指标是单值数组 [v]）
        """
        url = f"{self.base_url_quant}/real_time_quotation"
        codes_str = ",".join(codes)
        payload = {
            "codes": codes_str,
            "indicators": indicators,
        }
        return self._post(url, payload)

    def batch_get_realtime_quotation(
        self,
        codes: List[str],
        indicators: str = "changeRatio,open,latest,riseCount,fallCount,upLimitCount",
        batch_size: int = 100,
    ) -> Dict[str, Dict[str, float]]:
        """
        批量获取实时行情（自动分批），返回解析后的 {code: {indicator: value}}。
        :return: {code: {"changeRatio": float, "open": float, ...}}（无数据的代码不在结果中）
        """
        result: Dict[str, Dict[str, float]] = {}
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            resp = self.get_realtime_quotation(batch, indicators=indicators)
            if resp.get("errorcode") not in (0, None):
                continue
            for item in resp.get("tables", []):
                cc = item.get("thscode", "")
                tbl = item.get("table", {})
                row: Dict[str, float] = {}
                for k, v in tbl.items():
                    if isinstance(v, list) and v:
                        row[k] = v[0]
                    elif v is not None:
                        row[k] = v
                if row:
                    result[cc] = row
        return result

    # ========== 接口5: 概念基本信息（字典初始化） ==========
    def get_concept_basic_info(self, concept_codes: List[str]) -> dict:
        """
        获取同花顺概念指数基本信息
        :param concept_codes: 概念指数代码列表
        :return: API 原始响应
        """
        url = f"{self.base_url_quant}/basic_data_service"
        codes_str = ",".join(concept_codes)
        payload = {
            "codes": codes_str,
            "indipara": [
                {"indicator": "ths_index_short_name_index", "indiparams": []},
                {"indicator": "ths_index_full_name_index", "indiparams": []},
                {"indicator": "ths_index_code_index", "indiparams": []},
                {"indicator": "ths_main_sec_code_index", "indiparams": []},
                {"indicator": "ths_thscode_index", "indiparams": []}
            ]
        }
        return self._post(url, payload)

    # ========== 特色数据: 智能选股（板块全集发现/搜索） ==========
    # 文档：POST /api/v1/smart_stock_picking，searchtype=index 枚举指数，stock 查个股
    # 实测 2026-09：概念指数 390 / 二级行业 90 / 三级行业 230，共 710 个板块动态可枚举

    # searchstring → 板块分类的固定句式（枚举用）
    BOARD_CATEGORY_QUERIES = {
        "concept": "同花顺概念指数",        # 885xxx 概念板块
        "industry_l2": "同花顺二级行业指数",  # 881xxx 二级行业
        "industry_l3": "同花顺三级行业指数",  # 884xxx 三级行业
    }

    def smart_pick_boards(self, searchstring: str) -> List[Dict[str, Any]]:
        """
        智能选股接口枚举板块（searchtype=index）。
        :param searchstring: 如 "同花顺概念指数" / "同花顺二级行业指数" / "同花顺三级行业指数"，
                             也支持按名称搜索（如 "半导体"）
        :return: [{"concept_code", "concept_name", "category", "change_ratio"(可能缺)}, ...]
        """
        url = f"{self.base_url_quant}/smart_stock_picking"
        payload = {"searchstring": searchstring, "searchtype": "index"}
        resp = self._post(url, payload)
        tables = resp.get("tables", [])
        if not tables:
            return []
        tbl = tables[0].get("table", {})
        codes = tbl.get("指数代码", [])
        names = tbl.get("指数简称", [])
        # 分类/涨跌幅字段名因 query 而异，做兼容取值
        cat_key = next((k for k in tbl if "级别" in k or ("同花顺" in k and k != "指数代码")), None)
        chg_key = next((k for k in tbl if "涨跌幅" in k), None)
        cats = tbl.get(cat_key, []) if cat_key else []
        chgs = tbl.get(chg_key, []) if chg_key else []

        boards = []
        for i, code in enumerate(codes):
            chg = chgs[i] if chgs and i < len(chgs) else None
            try:
                chg = round(float(chg), 2) if chg is not None else None
            except (TypeError, ValueError):
                chg = None
            boards.append({
                "concept_code": code,
                "concept_name": names[i] if i < len(names) else "",
                "category": cats[i] if i < len(cats) else searchstring,
                "change_ratio": chg,
            })
        return boards

    def get_all_ths_boards(self, levels: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        动态枚举同花顺公共板块全集（概念 + 二级行业 + 三级行业）。
        用途：刷新板块字典 / 发现新板块 / 替代硬编码 SECTOR_POOL_CODES。
        :param levels: 要枚举的分类，默认全部 ["concept", "industry_l2", "industry_l3"]
        :return: [{"concept_code", "concept_name", "category", "change_ratio", "level"}, ...]
        """
        levels = levels or list(self.BOARD_CATEGORY_QUERIES.keys())
        seen = set()
        boards = []
        for level in levels:
            q = self.BOARD_CATEGORY_QUERIES.get(level)
            if not q:
                continue
            for b in self.smart_pick_boards(q):
                if b["concept_code"] in seen:
                    continue
                seen.add(b["concept_code"])
                b["level"] = level
                boards.append(b)
        return boards

    def search_board_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称搜单个板块（如 "半导体" → 881121.TI）。找不到返回 None。"""
        boards = self.smart_pick_boards(name)
        return boards[0] if boards else None

    def smart_pick_stocks(self, searchstring: str) -> List[Dict[str, Any]]:
        """
        智能选股接口查个股（searchtype=stock）。
        自然语言句式实测："机器人概念板块成分股" → 1227 只（带所属概念字段）。
        :return: [{"stock_code", "stock_name", "concepts"(所属概念,可能缺)}, ...]；空列表=无数据
        """
        url = f"{self.base_url_quant}/smart_stock_picking"
        payload = {"searchstring": searchstring, "searchtype": "stock"}
        resp = self._post(url, payload)
        if resp.get("errorcode") not in (0, None):
            return []
        tables = resp.get("tables", [])
        if not tables:
            return []
        tbl = tables[0].get("table", {})
        codes = tbl.get("股票代码", [])
        names = tbl.get("股票简称", [])
        concepts = tbl.get("所属概念", [])
        # 涨跌幅列名带日期后缀（如"涨跌幅:前复权[20260907]"），按前缀匹配
        chg_key = next((k for k in tbl if k.startswith("涨跌幅")), None)
        chgs = tbl.get(chg_key, []) if chg_key else []
        rows = []
        for i, code in enumerate(codes):
            chg = chgs[i] if chgs and i < len(chgs) else None
            rows.append({
                "stock_code": code,
                "stock_name": names[i] if i < len(names) else "",
                "concepts": concepts[i] if i < len(concepts) else "",
                "change_ratio": round(float(chg), 2) if chg is not None else None,
            })
        return rows

    # ========== 行情区间解析层（缓存读路径专用） ==========
    # 分片上限（实测 2026-10：分钟 30 天/5061 bars 通过，无跨度报错；片长见 docs/cache-design.html）
    DAILY_CHUNK_DAYS = 90
    MINUTE_CHUNK_DAYS = 30
    DAILY_INDICATORS = "preClose,open,high,low,close,volume,amount,changeRatio"
    MINUTE_INDICATORS = "open,high,low,close,volume,changeRatio"

    def fetch_daily_bars(self, code: str, start: str, end: str,
                         indicators: str = None, cps: Optional[str] = "1") -> List[Dict]:
        """
        区间拉取日频 bar（全指标一次拉全，读时投影）。缓存口径只存不复权：
        CPS="1"（实测：指数代码 CPS 不生效——None≡"1"≡"6" 同值，指数无分红；
        股票代码上 None≡"1"≠"6"）。自动按 DAILY_CHUNK_DAYS 分片。
        :return: [{"code", "time"(YYYY-MM-DD), <指标...>}]，按时间升序
        """
        bars: List[Dict] = []
        for cs, ce in _day_chunks(start, end, self.DAILY_CHUNK_DAYS):
            resp = self.get_history_quotation([code], cs, ce,
                                              indicators=indicators or self.DAILY_INDICATORS,
                                              cps=cps)
            bars.extend(_bars_from_tables(resp))
        return bars

    def fetch_minute_bars(self, code: str, start_day: str, end_day: str,
                          indicators: str = None) -> List[Dict]:
        """
        区间拉取 1min bar，按 MINUTE_CHUNK_DAYS 分片（单次跨度上限待实测校准）。
        :return: [{"code", "time"(YYYY-MM-DD HH:MM...), <指标...>}]，按时间升序
        """
        bars: List[Dict] = []
        for cs, ce in _day_chunks(start_day, end_day, self.MINUTE_CHUNK_DAYS):
            resp = self.get_high_frequency([code], f"{cs} 09:00:00", f"{ce} 16:00:00",
                                           indicators=indicators or self.MINUTE_INDICATORS)
            bars.extend(_bars_from_tables(resp))
        return bars

    # ========== 批量查询工具 ==========
    def batch_get_stock_concepts(
        self,
        all_stock_codes: List[str],
        date: str,
        batch_size: int = None
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        批量获取全市场个股所属概念（自动分批）
        :param all_stock_codes: 全市场股票代码列表
        :param date: 查询日期
        :param batch_size: 每批数量，默认取 client 配置 batch_size
        :return: {stock_code: [{concept_name, concept_code}, ...]}
        """
        batch_size = batch_size or self.batch_size
        result = {}

        for i in range(0, len(all_stock_codes), batch_size):
            batch = all_stock_codes[i:i + batch_size]
            resp = self.get_stock_concepts(batch, date)

            # 解析响应 - 每个股票一个 table 对象
            if "tables" in resp and len(resp["tables"]) > 0:
                for item in resp["tables"]:
                    stock_code = item.get("thscode", "")
                    table = item.get("table", {})
                    if not stock_code:
                        continue

                    concept_names = table.get("ths_the_ths_concept_index_stock", [])
                    concept_codes_list = table.get("ths_the_ths_concept_index_code_stock", [])
                    result[stock_code] = []

                    if concept_names and len(concept_names) > 0:
                        name_str = concept_names[0]
                        code_str = concept_codes_list[0] if concept_codes_list else ""

                        # 同花顺返回的是逗号分隔的字符串
                        names = [n.strip() for n in str(name_str).split(",") if n.strip()]
                        codes = [c.strip() for c in str(code_str).split(",") if c.strip()]

                        result[stock_code] = [
                            {"concept_name": n, "concept_code": c}
                            for n, c in zip(names, codes)
                        ]

        return result

    def batch_get_concept_basic_info(
        self,
        all_concept_codes: List[str],
        batch_size: int = 100
    ) -> List[Dict[str, str]]:
        """
        批量获取概念基本信息（自动分批）
        :param all_concept_codes: 概念代码列表
        :param batch_size: 每批数量
        :return: [{concept_code, short_name, full_name, index_code, main_code, thscode}, ...]
        """
        result = []

        for i in range(0, len(all_concept_codes), batch_size):
            batch = all_concept_codes[i:i + batch_size]
            resp = self.get_concept_basic_info(batch)

            # 解析响应 - 每个概念一个 table 对象
            if "tables" in resp and len(resp["tables"]) > 0:
                for item in resp["tables"]:
                    concept_code = item.get("thscode", "")
                    table = item.get("table", {})

                    short_names = table.get("ths_index_short_name_index", [])
                    full_names = table.get("ths_index_full_name_index", [])
                    index_codes = table.get("ths_index_code_index", [])
                    main_codes = table.get("ths_main_sec_code_index", [])
                    thscodes = table.get("ths_thscode_index", [])

                    result.append({
                        "concept_code": concept_code,
                        "short_name": short_names[0] if short_names else "",
                        "full_name": full_names[0] if full_names else "",
                        "index_code": index_codes[0] if index_codes else "",
                        "main_code": main_codes[0] if main_codes else "",
                        "thscode": thscodes[0] if thscodes else ""
                    })

        return result


def _day_chunks(start: str, end: str, chunk_days: int):
    """把 [start, end] 日期区间切成不超过 chunk_days 天的连续片。"""
    from datetime import date, timedelta
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    while s <= e:
        c = min(s + timedelta(days=chunk_days - 1), e)
        yield s.isoformat(), c.isoformat()
        s = c + timedelta(days=1)


def _bars_from_tables(resp: dict) -> List[Dict]:
    """
    解析历史/高频行情响应为 bar 列表。
    结构已由实测口径证实（ifind-concept-trend/Docs 接口验证清单）：列式数组，
    thscode/time 在项级外层，table{指标: [值,...]} 与 time 等长；分钟时间格式
    "YYYY-MM-DD HH:MM"。若实测发现差异只需调整本函数。
    """
    bars: List[Dict] = []
    for item in resp.get("tables", []):
        code = item.get("thscode", "")
        table = item.get("table", {})
        times = item.get("time") or table.get("time") or []
        keys = [k for k in table if k != "time"]
        for i, t in enumerate(times):
            bar = {"code": code, "time": t}
            for k in keys:
                vals = table[k]
                bar[k] = vals[i] if i < len(vals) else None
            bars.append(bar)
    return bars
