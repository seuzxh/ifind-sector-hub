# ifind-sector-hub

ifind 板块/概念数据层公共组件：数据源客户端（token 生命周期/重试/分片）、板块与成分股权威快照、同步编排。从 monitor（ifind-sector-attribution）抽离，供多平台复用。

`concept_members` 是“同花顺概念板块 ↔ 成分股”关系的唯一权威来源：按概念正查和按股票反查都从它读取。`stock_concept_map` 仅保留接口 1 返回的标签与等权信息，不作为成分关系真相源。

## 安装

```bash
pip install -e /root/Projects/ifind-sector-hub
# 可选服务层：
pip install -e "/root/Projects/ifind-sector-hub[service]"
```

核心依赖仅 `requests`（标准库 sqlite3 存储测试均用 unittest）。

## 快速开始

```python
from ifind_sector_hub import SectorHub, HubConfig, FileTokenStore

hub = SectorHub(HubConfig(
    db_path="data/sector_attribution.db",          # 任意 SQLite 库文件
    access_token="...", refresh_token="...",       # 首次 bootstrap（或环境变量 IFIND_*）
    token_store=FileTokenStore("data/token.json"), # 可选：刷新/轮换跨进程落盘
))

hub.client.smart_pick_stocks("机器人概念板块成分股")  # 数据源（含 smart_pick_boards 枚举板块）
hub.store.get_concept_members_map(["885001.TI"])    # 概念 → 成分股
hub.store.get_stock_memberships("600519.SH")        # 成分股 → 概念，同一权威表反查
hub.sync.sync_concept_members_report(["885001.TI"], "20260918")  # 含失败码的同步报告
```

## 模块（0.2.0 起：src 布局 + 分层子包）

| 模块 | 分层 | 职责 |
|---|---|---|
| `core.codes` | 叶子 | A股代码/前缀过滤（`is_a_share_code` / `is_a_share_concept`） |
| `core.tokens` | 叶子 | `TokenStore`（内存）/ `FileTokenStore`（JSON+flock，轮换自动持久化） |
| `integrations.ifind.client` | 外部适配 | `IFindClient`：接口1-6/实时行情/smart_pick，401 自动刷新 |
| `repositories.storage` | 数据层 | `SectorStore`：三张领域表 + 快照元数据、全量替换写、权威双向查询、`replace_concept_dict`（级联清理+同事务迁移钩子） |
| `services.sync` | 业务编排 | `SectorSync`：字典/成分股并发/映射/全集补全/观察池刷新 |
| `api.service` | 表现层（可选） | FastAPI router（`build_router(hub)`，只读+刷新触发） |

依赖方向单向：`api → services → repositories/integrations → core`，由 `.importlinter` 强制（`lint-imports` 校验）。

**0.2.0 迁移说明**：包级公共 API 不变（`from ifind_sector_hub import SectorHub, HubConfig, ...`）；模块深路径已迁移（`codes→core.codes`、`tokens→core.tokens`、`client→integrations.ifind.client`、`storage→repositories.storage`、`sync→services.sync`、`service→api.service`），旧深路径已移除，请改用包级导入或新路径。

## 注意（沿用 monitor 原语义）

- **日期格式跨表不一致**：字典/映射表 `YYYY-MM-DD`，成分股表 `YYYYMMDD`。
- **完整快照语义**：同一主体、同一日期重跑会先替换旧集合；空集合也会发布为最新快照。历史日期仍保留。
- **失败不发布**：iFinD 业务错误或畸形响应不会覆盖上一份有效快照；`sync_concept_members_report` 返回失败数量与概念码。
- `replace_concept_dict(boards, migrate_hook)` 的钩子在同一事务/连接内执行，用于迁移消费方自己的关联表（如 monitor 的 watched 勾选）。

## 测试

```bash
pip install -e ".[dev]"                # 前置：可编辑安装（src 布局必需，dev 含 import-linter）
python -m unittest discover -s tests   # 51 tests
lint-imports                           # 分层契约校验
```
