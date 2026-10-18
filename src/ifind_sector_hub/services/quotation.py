# -*- coding: utf-8 -*-
"""行情读服务（P0：交易日历播种；read-through 读路径与后台补全 P1 交付，见 docs/cache-design.html）。"""

from datetime import date, timedelta

DEFAULT_LOOKBACK_YEARS = 5
# 日历默认播种范围（固定数据，单次接口即可全程覆盖；实测上限可回溯至 1990-12-19 A股开市日）
CALENDAR_START = "2020-01-01"
CALENDAR_END = "2028-12-31"


class QuotationService:
    """懒加载行情服务的编排层（client + quotation_repo）。"""

    def __init__(self, client, repo, lookback_years: int = DEFAULT_LOOKBACK_YEARS):
        self.client = client
        self.repo = repo
        self.lookback_years = lookback_years

    def seed_calendar(self, start: str = CALENDAR_START, end: str = CALENDAR_END) -> int:
        """
        经 get_trade_dates 专用接口播种交易日历（权威固定数据），返回日历总天数（幂等）。
        默认 2020-2028 全覆盖（实测单次 2182 个交易日）；未来日历接口直接给出。
        """
        dates = self.client.get_trade_dates(start, end)
        return self.repo.seed_calendar(dates)

    def lookback_start(self) -> str:
        """懒加载回溯下界（today − N 年，多留 30 天余量避免边界日丢失）。"""
        return (date.today() - timedelta(days=365 * self.lookback_years + 30)).isoformat()
