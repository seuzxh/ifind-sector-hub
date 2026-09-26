# AGENTS.md

<!-- 本文件由 project-bootstrap 生成于 2026-09-27。
     · 头部「项目概览 / 常用命令」由你维护，skill 仅在首次部署时预填
     · 带 agent-config 标记的区块由 skill 托管，更新时整体替换；
       自定义规则请写在标记之外的兄弟章节，不要写进标记内 -->

## 项目概览

- 项目名：ifind-sector-hub
- 类型：library（检测推断，请校正：api / web / library / monorepo / research / minimal）
- 语言与栈：Python ≥3.9 · requests · 标准库 sqlite3 · 可选 extra [service]（fastapi/pydantic）
- 一句话说明：ifind 板块/概念数据层公共组件——数据源客户端（token 生命周期/重试/分片）、三表快照存储、同步编排，自 monitor 抽离供多平台复用

## 常用命令

- 安装依赖：pip install -e .（可选服务层：pip install -e ".[service]"）
- 运行测试：python -m unittest discover -s tests
- 本地启动：无（库项目；可选 FastAPI router 由消费方 build_router(hub) 自行挂载）
- 代码检查：<lint_cmd>

<!-- agent-config:architecture v1.1 begin -->
## 架构与目录规范（强制遵守）

> 本规范适用于本项目所有代码生成、修改与重构任务，优先级高于默认习惯。
> 核心思想：目录树就是架构说明——先看目录，再写代码。

### 〇、任务开始前

- 涉及新建文件/模块的任务：动手前先用 2-3 行说明每个新文件将放在哪里（依据第四节决策表），再继续
- 发现存量代码违反本规范：本次任务内只修自己触碰的文件，不顺手大重构；大范围重构先提方案
- 用户指令与本规范冲突时：指出冲突点请用户决策，默认遵守本规范

### 一、五条铁律

1. **入口只装配**：`main.py` 只做配置加载、路由注册、应用启动，一行业务不写
2. **依赖单向**：表现层 → 业务层 → 数据层；反向、跨层、循环依赖一律禁止
3. **配置单一出口**：`core/config.py` 是唯一读 `.env` 的模块，其他模块只从 config 导入
4. **测试镜像源码**：`tests/` 目录结构与 `src/` 一一对应
5. **高内聚**：一个需求只改一个目录；若改动必然散落 3 个以上目录，停下向用户确认架构

### 二、目录结构（标准骨架）

后端（Python 模块化单体）：

```text
src/<app>/
├── main.py                # 入口：只装配
├── core/                  # 配置、日志、异常、安全
├── api/v1/                # 表现层：路由 + 参数校验
├── schemas/               # 请求/响应 DTO（与 ORM 解耦）
├── services/              # 业务层：规则与事务编排（核心资产）
├── repositories/          # 数据层：ORM + 查询（SQL 只出现在这）
├── integrations/          # 外部系统适配（行情源、iFinD、消息队列）
└── utils/                 # 真正通用的纯函数（保持小）
tests/                     # 镜像 src/
```

前端（React，按功能域组织）：

```text
web/src/
├── app/                   # 装配：路由表、Provider、布局
├── features/<域>/         # 域私有组件/api/types 都在该域目录内
├── components/            # 跨域通用组件（≥2 域使用才升级为通用）
├── lib/                   # axios 实例、通用 hooks、工具
└── styles/
```

前后端同仓（monorepo）：

```text
├── apps/api/              # 后端
├── apps/web/              # 前端
└── packages/shared/       # 前后端共享的类型契约、常量、枚举（单点维护）
```

### 三、依赖方向（红线）

允许的依赖（→ 表示"可以 import"）：

```text
api/v1 → services → repositories
services → integrations
api、services → schemas、utils、core
utils、core →（不依赖任何业务模块，是叶子）
app/ → features/ → components/、lib/
apps/* → packages/shared
```

禁止的依赖（出现即架构已坏，停止写码并报告，不许打补丁绕过）：

- `repositories` / `schemas` / `integrations` 反向 import `services` 或 `api`
- `integrations` import 业务模块（适配层不知道业务）
- `utils` import 任何业务层
- 任何模块 import `api`
- `features/<域A>` import `features/<域B>`（需要共享时下沉到 components/lib，或提出来）
- `apps/api` 与 `apps/web` 互相引用
- 任何形式的循环依赖

### 四、新代码放置决策表

| 要创建的内容 | 放置位置 | 准入/说明 |
|---|---|---|
| 新接口/路由 | `api/v1/<域>.py` | 只做参数校验与调用 service；不写业务、不写 SQL |
| 业务规则/流程编排 | `services/<域>.py` | 事务边界在这层 |
| SQL/ORM 查询 | `repositories/<域>.py` | SQL 只许出现在这 |
| 请求/响应模型 | `schemas/` | 禁止 ORM 模型直接当响应 |
| 外部系统封装 | `integrations/<系统>/` | 全仓唯一一份，禁止复制到业务目录 |
| 通用纯函数 | `utils/` | 无状态、无业务语义、≥2 处使用；否则放域内 |
| 前端新页面/功能 | `features/<域>/` | 域内组件/接口/类型不出域 |
| 跨域通用组件 | `components/` | ≥2 个域使用才放这 |
| 一次性验证脚本 | `scratch/`（gitignore） | 任务结束删除，禁止入库 |
| 数据文件/中间产物 | `data/`（gitignore） | 永不入 git |
| 多步流程/检查清单 | `.claude/skills/<name>/SKILL.md` | 不要塞进本文件 |
| 常驻事实类新规则 | `AGENTS.md`（走 PR） | 不要散落在代码注释里 |

### 五、版本与演进（git tag 管理法）

核心心智：**git 历史是博物馆，工作区是车间；版本号活在参数组、spec 文档和 tag 里，不活在文件名里**。

1. **结构性演进前先 tag**：删除或重构任何"曾经是生产口径"的代码前，先打 `<ver>-frozen` tag（如 `v3-frozen`、`prod-v43`）并推送——旧版本永远可 `git checkout <tag>` 复现，工作区留副本不增加任何可复现性，只增加混乱
2. **新版本 = 参数组 + 文档 + runner，不是新代码文件**：算法调优优先通过 config 的版本化参数组（如 `V41_*` / `V43_*`）实现；禁止为版本差异新建引擎文件（`v2.py`/`v5.py`/`xxx_new.py`）。引擎不带版本名，参数组带版本名
3. **三生命周期判定**：
   - 冻结的验证轨（预注册、评价期禁改参）：**不许动**，即使含有已退役标的
   - 已完成使命的实验（结论已冻结在 docs/ 或 docstring）：**tag 后删除** runner，删除须用户确认并在提交说明里注明 tag 名与结论文档链接
   - 现行生产：**去版本化重构后长住工作区**，入口 docstring 标明现行口径与 spec 链接
4. **死文件的真实代价**：死代码进 code graph 索引和 grep 结果，AI 可能用退役口径作答；每留一份旧文件，未来复制漂移的概率就多一分
5. **周期清理**：验证轨裁决结束后，清理对应冻结 runner 与退役参数组

### 六、禁止事项（反模式，出现即返工）

1. **utils/common 黑洞**：什么都往里塞。准入见决策表
2. **胖控制器**：业务写在路由里
3. **ORM 模型直接当响应**：内部结构泄漏，改表就炸接口
4. **平行实现**：复制已有函数微调改名。新增前必须先全仓搜索是否已有实现
5. **过早微服务**：默认模块化单体；拆服务是规模倒逼的结果
6. **临时残留**：debug 输出（print/console.log）、注释掉的旧代码、无 issue 的 TODO
7. **测试后补/自证**：修 bug 先写失败测试；不要在同一轮生成里同时写测试和实现再让测试迁就实现
8. **版本化文件名**：`xxx_v2.py`、`xxx_new.py`、`xxx_final.py`——版本语义应落在 tag/参数组/文档，见第五节

### 七、配置、数据与环境

- `.env` 不入 git；环境差异全部走环境变量，由 `core/config.py` 统一读取
- `data/`、`scratch/`、构建产物不入 git
- 密钥不硬编码；新依赖先征得用户同意

### 八、测试要求

- 新增行为必须有对应测试；bug 修复附带回归测试
- `tests/` 结构镜像 `src/`：找到被测文件就能找到测试
- 提交前测试套件全绿，并附运行输出作为证据

### 九、完成定义（每次任务收尾自查）

- [ ] 新文件位置符合决策表，依赖方向无反向/跨层
- [ ] 无临时脚本、调试输出、注释掉的旧代码残留
- [ ] 新增行为有测试；测试全绿（附输出）
- [ ] `scratch/` 已清理，`data/` 未入库
- [ ] 提交遵循 Conventional Commits，一次提交只做一件事

<!-- agent-config:architecture v1.1 end -->
<!-- agent-config:commit v1.1 begin -->
## Git Commit 规范（强制遵守）

### 〇、生成 commit 前自查（提交前三问）

1. **哪里坏了 / 缺什么？**（why——这是 body 的主要内容）
2. **最小正确改动是什么？**（what——决定暂存区该装什么）
3. **这个改动值得独立成 commit，还是该并入已有暂存？**（粒度——防碎片化）

**粒度规则**：
- 一次任务产生的 commit 数 ≤4；超过说明粒度错了，合并
- 一个 commit = 一个可独立理解的逻辑改动；"改实现 + 补测试"是**一个** commit，不拆
- 禁止"修个 typo 再来一个 commit"式尾巴提交——并入相关提交
- `wip:` 前缀只允许在个人分支；合入主干前必须 squash（PR 用 Squash and merge）

### 一、格式规范（Conventional Commits）

```text
<type>(<scope>): <中文描述，≤50 字，不加句号>          ← 首行，总长 ≤72 字符

[空行]
<body：解释 why 而非 what；每行 ≤72 字符；可省略但 feat/fix/refactor 强烈建议写]

[空行]
[footer：BREAKING CHANGE: <描述> | Refs: #issue | 关联 tag：v3-frozen]
```

规则要点：
- **type 英文小写，scope 英文小写，description 中文**（工具可解析 + 人易读写）
- type 与描述之间：英文半角冒号 + 一个空格，缺一不可（工具会报错）
- 描述用祈使句口吻、陈述事实：写"添加 X"不写"我添加了 X"、"修复了 Y"（自检句式："如果应用此提交，它将……"）
- 破坏性变更两种标记等价：`feat(api)!: ...` 或 footer 写 `BREAKING CHANGE: ...`（后者必须全大写）
- 同一改动涉及多类型时，取**最主要**的类型；宁可 body 里补充说明，不拆碎片提交

### 二、type 速查表

| type | 用途 | 示例 |
|---|---|---|
| `feat` | 新功能 | `feat(nlq): 添加链内排行查询` |
| `fix` | 修 bug（含实验结论修正） | `fix(minute): 修正 5min 重排的时区偏移` |
| `perf` | 性能优化（行为不变） | `perf(etl): 批量读取替代逐行查询` |
| `refactor` | 结构重构（行为不变） | `refactor: v3.py 拆分为 signals/engine` |
| `docs` | 文档、注释 | `docs: 冻结 v4.1 结论文档` |
| `test` | 测试（补测试、修测试） | `test: 补 signal_daily 幂等性测试` |
| `build` | 构建/依赖 | `build: requirements 增加 tenacity` |
| `ci` | CI 配置 | `ci: 增加 commitlint 校验工作流` |
| `chore` | 杂务（日志、配置清理） | `chore: 清理临时产物` |
| `revert` | 回滚（footer 注明被回滚的 hash） | `revert: 回滚动态半衰期（Refs: 676104e）` |
| `style` | 纯格式（不改语义） | `style: ruff format 全量格式化` |

scope 惯例：用模块名；跨模块省略 scope。

### 三、AI 专属规则（硬性）

1. **禁止任何 AI 署名**：不得添加 `Co-Authored-By: Claude`、`Generated with [...]` 等标识
2. **禁止黑盒动词**：`update code`、`fix stuff`、`修改了一些问题`、`wip`（个人分支除外）——描述必须具体到可检索
3. **message 依据事实生成**：以 `git diff --staged` 实际内容 + 测试输出为准，**不描述"打算做的"**
4. **生成后先展示再执行**：AI 生成 message 后展示给用户确认，不直接 commit（除非用户明确放行）
5. **提交前测试**：`feat`/`fix` 提交前测试套件必须全绿，message body 附测试结果摘要

### 四、研究型项目扩展规则

实验类项目的 commit 语义分层（与「版本与演进」节衔接）：

| 场景 | 写法 | 说明 |
|---|---|---|
| 实验调参试错 | **不进 git**（本地 runner / 个人分支 `wip:`） | 试错留在实验层，历史只记结论 |
| 参数组定稿 | `feat(config): 新增 V44_ANCHOR_POOL 参数组` | 参数组带版本号，进主干 |
| 实验结论冻结 | `docs: 冻结 v4.1 OOS 结论（样本外 −2.3%）` + **打 tag `v41-frozen`** | 结论与代码状态用 tag 绑定 |
| 数据快照更新 | `chore(data): 同步 2026-09 快照` | 大数据不入 git，快照靠缓存层 |
| 删除退役 runner | `chore: 移除 backtest_v3（tag v3-frozen 可复现）` | footer 或 body 注明 tag 名 |

<!-- agent-config:commit v1.1 end -->
