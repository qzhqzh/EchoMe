# EchoMe 记忆模型

> 按 2026-09-12 当前源码校准。接口字段以 [Pydantic schema](../hub/app/schemas/memory.py)，存储结构以 [ORM models](../hub/app/models/memory.py) 和 [Alembic migrations](../hub/alembic/versions/) 为准。本文描述已实现的行为；早期文件式 vault 设计见历史路线图。

## 1. 设计原则与存储边界

- **三轴正交**：Type 表示记忆性质，Scope 表示适用范围，Layer 表示静态加载层级。
- **Hub 是权威存储**：记忆保存在 PostgreSQL，正文使用 Markdown；不是每条记忆对应一个可双向同步的本地文件。
- **按任务获取上下文**：`echome_context` 统一选择 personal、project、impact 或 temporal 路径；L0/L1 静态文件用于常驻规则和调用引导。
- **证据与整理可追溯**：Memory、Project Knowledge、Sleep 派生关系和反馈各有边界；不能把派生视图当作无来源的权威事实。
- **预算控制输出**：内容预算与完整输出预算分别计量。统一 context 可选 compact 投影约束最终 JSON；静态渲染报告含引导和 marker 的总量。

## 2. 三轴模型

### 2.1 Type：10 种规范类型

| Type | 说明 | 典型内容 |
|---|---|---|
| `identity` | 身份 | 职责、背景 |
| `guardrail` | 红线与约束 | 禁止危险操作、权限边界 |
| `reasoning` | 思考方法 | 判断原则、决策框架 |
| `method` | 工作方法 | 开发流程、验证步骤 |
| `stack` | 技术偏好 | 工具链、框架选择 |
| `style` | 沟通风格 | 回答语言、组织方式 |
| `decision` | 历史决策 | 为什么选择某个方案 |
| `context` | 背景知识 | 业务术语、领域背景 |
| `template` | 可复用模板 | 配置片段、文档模板 |
| `project` | 项目说明 | 项目目标、架构与约定 |

CLI 添加/编辑时兼容部分旧类型别名，但 REST/MCP 的写入和类型过滤应使用上表中的规范值。旧文档中的 `persona/workflow/tech/constraint/knowledge/interaction/snippet` 不应继续用于新接口示例。Project Knowledge 的 constraint 是独立实体，不是 MemoryType。

### 2.2 Scope：适用范围

```json
{
  "global": false,
  "projects": ["qzhqzh/EchoMe"],
  "exclude_projects": []
}
```

- 全局记忆通常使用 `global=true`、空 `projects`。
- 项目记忆通常使用 `global=false`，并把已存在的 canonical project ID 放入 `projects`。
- 项目 context 会解析 active aliases，并在选择候选记忆时应用 `exclude_projects`。
- Repository context 可继承父 workspace 记忆；workspace 仅在 `changed_paths` 命中时选择子 repository，不自动引入 sibling repository。
- **排除语义**：带项目参数的 Memory list/search、静态 `sync/render` 与 Context Compiler 均按 canonical ID 和 active aliases 执行 `exclude_projects`。全局静态文件无法表达项目例外，因此省略带排除项目的规则；这些规则仍可在适用项目的查询/渲染中使用。workspace 继承和 changed_paths 选择仍属于 Context Compiler，范围字段不代替用户认证。

项目身份、aliases 和 workspace composition 详见 [Project Knowledge](project-knowledge.md) 与 [API 规范](api-spec.md)。

### 2.3 Layer：静态加载层级

| Layer | 当前作用 | 静态注入 |
|---|---|---|
| `L0` | 跨项目的常驻规则 | 全局 Claude/Codex 配置中的 EchoMe 区块 |
| `L1` | 项目规则 | 显式指定项目后渲染到项目配置区块 |
| `L2` | 按任务检索的详细知识 | 默认不写静态文件，通过 MCP/Hub 查询 |

Layer 不等于检索权限，MCP 检索可以返回不同 layer 的有效记忆。`L1` 本身也不表示“只属于当前项目”，仍须正确设置 Scope。

三轴在 REST 和 MCP `remember` 中可分别设置：所有 10 种类型都可绑定已存在的项目，MCP 会将 active alias 解析为 canonical ID。CLI `add` 仍没有项目 scope 参数。

当前全局静态渲染的默认正文预算为 1500 tokens；项目渲染默认组合 L0 与 L1，预算为 1500 + 2000 tokens。超出预算时按渲染顺序跳过整个条目，并计入 `memories_truncated`；**不会把 L0 自动降为 L1，或把 L1 自动降为 L2**。配置中的 20/30 条数量值目前不是渲染器执行的硬限制。

## 3. 单条记忆与数据模型

### 3.1 REST 创建示例

```json
{
  "title": "项目验证约定",
  "content": "**先验证真实链路**。\n\n## How to apply\n- 根据改动风险选择针对性检查。\n- 记录可复现的验证结果。",
  "type": "method",
  "layer": "L1",
  "priority": 8,
  "tags": ["validation"],
  "status": "active",
  "scope": {
    "global": false,
    "projects": ["qzhqzh/EchoMe"],
    "exclude_projects": []
  },
  "source": "manual",
  "visibility": "private"
}
```

这是结构示例，项目 ID 应替换为已存在的 canonical project。新建时由服务端生成 UUID。默认值为 `layer=L2`、`priority=5`、`status=active`、`source=manual`、全局 scope 和 private visibility；MCP AI 写入另有 `ai_review` 默认流程。

### 3.2 存储字段

| 字段组 | 主要字段及用途 |
|---|---|
| 所有权与正文 | UUID `id`、`user_id`、`title`、Markdown `content` |
| 三轴与排序 | `type`、`layer`、`scope_global/projects/exclude`、`priority`、`tags` |
| 生命周期 | `status`、`source`、`is_core`、`sleep_state` |
| 来源与替代 | `derived_from`、`superseded_by`；市场 fork 另有 `forked_from` |
| 检索与使用 | BGE-M3 `vector(1024)`、`token_count`、`last_accessed_at`、`access_count` |
| 共享与时间 | `visibility`、`created_at`、`updated_at` |

`source` 当前为 `manual / ai_suggested / imported / sleep`。`visibility` 为 `private / public`。Memory 的来源字段不等于每次编辑都有完整 revision 历史；Project Knowledge 的 artifact/constraint 有独立版本模型。

不在此复制可直接执行的简化建表 SQL，避免遗漏后续约束、索引或关联迁移。数据库变更必须通过现有 Alembic 链管理。

### 3.3 项目与同步记录

- `projects` 保存 canonical ID、所属用户、`repository/workspace` 类型、Git remote 与路径模式。
- `project_aliases` 保存候选/生效的身份线索；`project_relations` 保存 workspace 与 repository 的 `contains` 关系及状态。
- `sync_log` 记录 Hub 同步操作、受影响的 Memory ID 和客户端信息；它不是本地文件同步协议或冲突解决器。

## 4. 状态生命周期

| 状态 | 默认读取行为 | 典型来源或操作 |
|---|---|---|
| `active` | 参与有效记忆检索与静态渲染 | 手动创建或审核通过 |
| `ai_review` | 立即参与有效记忆检索与静态渲染 | MCP AI 建议；等待事后审核 |
| `pending` | 不进入默认有效记忆集合 | 旧兼容或严格审核流程 |
| `deprecated` | 不进入默认有效记忆集合，可显式查询 | 标记过时 |
| `archived` | 不进入默认有效记忆集合，可显式查询 | 拒绝、软删除或 Sleep 整理来源 |

`echome review` 默认审核 `ai_review`；审核通过改为 `active`，拒绝改为 `archived`。默认有效状态集合是 `active + ai_review`，但 full profile 的摘要/按类型工具默认显式过滤 `active`，调用时应留意各自参数。

Memory Sleep 使用 proposal/validate/apply 流程保存派生和替代关系；核心记忆与候选保护规则见 [Memory Sleep](memory-sleep.md)。普通 DELETE 默认归档；REST 另有显式物理删除选项，因此不能把所有删除操作都描述成软删除。

## 5. 本地目录与同步边界

```text
~/.echome/
├── config.yaml       # Hub URL、token、default_layer、editor
├── vault/            # 初始化会创建 10 种类型目录；文件同步功能尚未实现
├── pending/          # 预留目录；AI 待审核记忆实际保存在 Hub
├── .state/           # 预留本地状态目录
└── cache/context/    # MCP 已知成功上下文的加密只读缓存
```

- `echome add/list/search/review` 访问 Hub，`echome sync` 将 Hub 的渲染结果更新到目标文件 marker 区块。
- 文件式 `echome push/pull` 是保留命令，当前以未实现错误退出；REST `/sync/push`、`/sync/pull` 已存在，不等于 CLI 的本地文件工作流已完成。
- Hub 不可达时，`echome_context` 仅可复用**完全相同请求键**的 last-known-good 缓存，默认最多保留 7 天并标记 degraded；不会扫描 vault 生成替代上下文。
- 缓存使用本机密钥加密，写操作没有离线队列，也不会因缓存命中而伪报写入成功。

## 6. 检索与渲染

### 6.1 Memory 检索

普通 Memory search 与 personal context 使用共享的有界混合召回：按用户及请求过滤候选，对 query 做向量与词法匹配；embedding 不可用时可降级为词法召回。当前混合权重为向量 0.7、词法 0.3，priority 与更新时间用于排序补充，不是旧设计的 0.6/0.3/0.1 公式。

词法路径支持英文 token、中文 n-gram 和词汇扩展。Memory search 默认返回 5 条，`top_k` 最大 20；`min_score` 默认 0.3。实际参数和退化语义见 [检索策略](memory-retrieval.md)。

项目 Context Compiler 则组合 Memory、Artifact、Constraint、Event 和 View，使用多路召回、图/时间证据与预算编译；不能用 Memory search 的单一评分公式解释所有项目上下文。

### 6.2 静态渲染

1. Hub 选择当前用户的 `active + ai_review` 记忆。
2. 全局默认选择全局 L0；带项目时默认组合全局 L0，以及全局或匹配该项目的 L1（可展开 active 历史 alias）。
3. 按类型顺序，再按类型内 priority 降序渲染；预算不足时跳过条目。
4. 附加 MCP 引导与 marker，返回最终正文、token 统计、选入和截断数量。
5. CLI 更新 Claude/Codex 全局文件；显式 `--project` 时也更新当前目录的项目文件。

`POST /sync/render` 的显式 `layer` 参数可覆盖默认层选择。静态渲染不等同于 `echome_context` 的任务检索；`echome sync --dry-run` 可查看将写入的内容。

## 7. Token 统计与配置

Hub 的 [token counter](../hub/app/services/token_counter.py) 优先使用已缓存的 `cl100k_base`；没有可用 tokenizer 缓存时使用字符长度估算，不为首次计数隐式下载。此统计用于预算，不代表所有模型的精确计费 token。

静态渲染预算配置位于 Hub：

```dotenv
ECHOME_L0_MAX_TOKENS=1500
ECHOME_L1_MAX_TOKENS=2000
```

CLI 的 `~/.echome/config.yaml` 当前没有 `limits` 配置项。修改 Hub 预算应遵循部署配置流程；最终响应仍会包含引导和元数据，不能只凭正文预算推断总长度。

## 8. AI 写入与反馈

1. 先判断是否为稳定、可复用的信息，并选择 10 种规范类型之一。
2. 通用记忆不传 `project`；项目相关记忆保留合适的类型（如 decision/method/guardrail），传已存在的 canonical project，通常建议 `L1`。`type=project` 仍必须提供项目，remember 不静默创建项目。
3. `echome_remember` 接收 `title/content/type/tags/suggested_layer/project`，默认在 Hub 创建 `source=ai_suggested`、`status=ai_review` 的记忆。
4. Hub 做内容安全校验；新记忆立即可被后续有效记忆检索使用。L0/L1 静态文件仍需重新 sync。
5. 发现记忆有用、错误、过时或冲突时，用 `echome_memory_feedback` 记录结果；涉及历史决策时先用 `echome_memory_explain` 核对来源和替代关系。
6. 已记录的 Context Run 按 completion contract 通过 `echome_context_outcome` 追加结果；无信号不能推断为失败。

## 9. 版本、整理与尚未实现的能力

- Memory 保留更新时间、状态、Sleep 来源和替代关系；不要假设普通编辑自动生成完整历史版本。
- Sleep 通过新增派生记忆和归档来源表达整理结果；Reflect 通过验证来源生成派生 `knowledge_view`，不会自动改写权威记忆。
- Context Policy 默认 shadow，返回评估与干预 trace；readiness 不授予自动 enforce 权限。
- Markdown/Git 文件投影、可靠的本地双向回写、团队 scope 等需单独设计和验收，不能把不存在的 `shared_workflow` 类型或离线同步当作现有接口。
- 图关系、时态评估、项目知识版本、Memory Sleep 与反馈已经实现，不再列作尚未启动的远期设想。当前边界和待办入口见 [路线图](roadmap.md)。
