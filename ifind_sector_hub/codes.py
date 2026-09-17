# -*- coding: utf-8 -*-
"""A股市场过滤（数据域有效性约束：本组件只服务沪深北 A 股板块/概念数据）。"""

# A股个股代码后缀（沪深北交易所）
A_SHARE_SUFFIXES = (".SH", ".SZ", ".BJ")

# 有效 A股概念前缀白名单（700/881/883/884/885/886 = A股行业与概念；861/864/865/871/875 为海外）
A_SHARE_CONCEPT_PREFIXES = ("700", "881", "883", "884", "885", "886")


def is_a_share_code(code: str) -> bool:
    """判断个股代码是否为 A股（沪深北交易所）"""
    return code is not None and code.endswith(A_SHARE_SUFFIXES)


def is_a_share_concept(concept_code: str) -> bool:
    """判断概念代码是否为 A股相关概念（按编码前缀白名单，海外行业指数返回 False）。"""
    return concept_code is not None and concept_code[:3] in A_SHARE_CONCEPT_PREFIXES
