# -*- coding: utf-8 -*-
"""可选 FastAPI 服务层（只读 + 刷新触发；本期只交付不部署）。

依赖 optional extras：pip install "ifind-sector-hub[service]"。
未安装 fastapi 时 import 本模块报 ImportError，不影响库的核心使用。
"""

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel


def build_router(hub) -> APIRouter:
    """构建板块数据路由；挂到任一 FastAPI 应用即可对外供数。"""
    router = APIRouter()

    @router.get("/concepts")
    def list_concepts():
        names = hub.store.get_concept_names()
        concepts = [{"concept_code": c, "concept_name": n}
                    for c, n in sorted(names.items())]
        return {"count": len(concepts), "concepts": concepts}

    @router.get("/concepts/{concept_code}/members")
    def concept_members(concept_code: str, date: Optional[str] = None):
        members = hub.store.get_concept_members(concept_code, date)
        return {"concept_code": concept_code, "count": len(members), "members": members}

    @router.get("/stocks/{stock_code}/concepts")
    def stock_concepts(stock_code: str, date: Optional[str] = None):
        rows = hub.store.get_stock_concepts(stock_code, date)
        return {"stock_code": stock_code, "count": len(rows), "concepts": rows}

    class SyncMembersRequest(BaseModel):
        concept_codes: List[str]
        date: str

    @router.post("/sync/members")
    def sync_members(req: SyncMembersRequest):
        saved = hub.sync.sync_concept_members(req.concept_codes, req.date)
        return {"ok": True, "saved_records": saved}

    return router
