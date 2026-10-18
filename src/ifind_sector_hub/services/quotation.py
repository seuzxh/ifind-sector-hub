# -*- coding: utf-8 -*-
"""行情读服务（P0：交易日历播种；read-through 读路径与后台补全 P1 交付，见 docs/cache-design.html）。"""

from datetime import date, timedelta

DEFAULT_LOOKBACK_YEARS = 5
# 日历向未来多取的天数：未来日历为固定数据，接口直接给出，缓存后今日后的缺口计算即可用
CALENDAR_FUTURE_DAYS = 400


class QuotationService:
    """懒加载行情服务的编排层（client + quotation_repo）。"""

    def __init__(self, client, repo, lookback_years: int = DEFAULT_LOOKBACK_YEARS):
        self.client = client
        self.repo = repo
        self.lookback_years = lookback_years

    def seed_calendar(self, years: int = None) -> int:
        """
        经 get_trade_dates 专用接口播种交易日历（权威固定数据），返回日历总天数（幂等）。
        范围：回溯下界 ~ 今日 + 400 天（未来日历接口直接给出）。
        """
        years = years or self.lookback_years
        start = (date.today() - timedelta(days=365 * years + 30)).isoformat()
        end = (date.today() + timedelta(days=CALENDAR_FUTURE_DAYS)).isoformat()
        dates = self.client.get_trade_dates(start, end)
        return self.repo.seed_calendar(dates)

    def lookback_start(self) -> str:
        """懒加载回溯下界（today − N 年，多留 30 天余量避免边界日丢失）。"""
        return (date.today() - timedelta(days=365 * self.lookback_years + 30)).isoformat()
