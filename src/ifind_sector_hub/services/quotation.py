# -*- coding: utf-8 -*-
"""行情读服务（P0：交易日历播种；read-through 读路径与后台补全 P1 交付，见 docs/cache-design.html）。"""

from datetime import date, timedelta

# 交易日历源：上证指数——历史长、永续存在，其日线时间轴即 A 股交易日历
CALENDAR_SOURCE_CODE = "000001.SH"
DEFAULT_LOOKBACK_YEARS = 5


class QuotationService:
    """懒加载行情服务的编排层（client + quotation_repo）。"""

    def __init__(self, client, repo, lookback_years: int = DEFAULT_LOOKBACK_YEARS):
        self.client = client
        self.repo = repo
        self.lookback_years = lookback_years

    def seed_calendar(self, years: int = None) -> int:
        """拉宽基指数近 N 年日线播种交易日历，返回日历总天数（幂等）。"""
        years = years or self.lookback_years
        start = (date.today() - timedelta(days=365 * years + 30)).isoformat()
        bars = self.client.fetch_daily_bars(CALENDAR_SOURCE_CODE, start, date.today().isoformat())
        return self.repo.seed_calendar(b["time"] for b in bars)

    def lookback_start(self) -> str:
        """懒加载回溯下界（today − N 年，多留 30 天余量避免边界日丢失）。"""
        return (date.today() - timedelta(days=365 * self.lookback_years + 30)).isoformat()
