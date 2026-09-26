# -*- coding: utf-8 -*-
"""ifind-sector-hub：ifind 板块/概念数据层公共组件。

用法：
    from ifind_sector_hub import SectorHub, HubConfig, FileTokenStore
    hub = SectorHub(HubConfig(db_path="data/sector_attribution.db",
                              access_token=..., refresh_token=...,
                              token_store=FileTokenStore("data/token.json")))
    hub.client.smart_pick_stocks("...")       # 数据源
    hub.store.get_concept_members_map([...])  # 三表快照读
    hub.sync.sync_concept_members([...], "20260917")
"""

from dataclasses import dataclass
from typing import Optional

from .core.codes import A_SHARE_CONCEPT_PREFIXES, A_SHARE_SUFFIXES, is_a_share_code, is_a_share_concept
from .core.tokens import FileTokenStore, TokenStore, resolve_tokens
from .integrations.ifind.client import IFindClient
from .repositories.storage import SectorStore
from .services.sync import SectorSync

__all__ = [
    "HubConfig", "SectorHub", "FileTokenStore", "TokenStore", "resolve_tokens",
    "IFindClient", "SectorStore", "SectorSync",
    "is_a_share_code", "is_a_share_concept", "A_SHARE_SUFFIXES", "A_SHARE_CONCEPT_PREFIXES",
]


@dataclass
class HubConfig:
    db_path: str
    # token：显式传入优先，未传走环境变量（token_store 提供时以其为准）
    access_token: str = ""
    refresh_token: str = ""
    token_store: Optional[TokenStore] = None
    base_url_quant: str = "https://quantapi.51ifind.com/api/v1"
    base_url_ft: str = "https://ft.10jqka.com.cn/api/v1"
    timeout: int = 30
    max_retries: int = 3
    batch_size: int = 100
    members_concurrency: int = 8
    members_progress_every: int = 100


class SectorHub:
    """门面：聚合 client / store / sync，共享同一 token 管理与库文件。"""

    def __init__(self, cfg: HubConfig):
        if cfg.token_store is not None:
            tokens = cfg.token_store
        else:
            at, rt = resolve_tokens(cfg.access_token, cfg.refresh_token)
            tokens = TokenStore(at, rt)
        self.cfg = cfg
        self.client = IFindClient(tokens, base_url_quant=cfg.base_url_quant,
                                  base_url_ft=cfg.base_url_ft, timeout=cfg.timeout,
                                  max_retries=cfg.max_retries, batch_size=cfg.batch_size)
        self.store = SectorStore(cfg.db_path)
        self.sync = SectorSync(self.client, self.store,
                               concurrency=cfg.members_concurrency,
                               progress_every=cfg.members_progress_every)
