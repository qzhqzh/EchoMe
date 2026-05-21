# EchoMe 记忆模型设计

## 1. 设计原则

- **结构化但人类友好**：每条记忆是一个 Markdown 文件 + YAML frontmatter
- **三轴正交**：Type（性质）× Scope（生效范围）× Layer（加载时机）
- **可控增长**：L0 有 token 上限，L2 无限扩展但按需检索
- **双向同步**：本地 vault ↔ Hub 数据库，格式互转无损

## 2. 三轴模型

### 2.1 轴一：Type（记忆性质）

| Type | 说明 | 典型内容 |
|---|---|---|
| `persona` | 身份与风格 | 我是谁、语言偏好、沟通风格 |
| `workflow` | 工作流规范 | PR 规范、issue 模板、review 要求 |
| `tech` | 技术偏好 | 常用技术栈、目录结构、工具链 |
| `constraint` | 红线禁忌 | 不允许的危险操作 |
| `snippet` | 可复用片段 | Docker 模板、CI 配置 |
| `decision` | 设计决策 / ADR | 为什么选 X 不选 Y |
| `knowledge` | 领域知识 | 业务术语、客户背景 |
| `interaction` | 对话偏好 | 回答格式、反问习惯 |
| `project` | 项目上下文 | 项目目标、当前阶段、架构 |

### 2.2 轴二：Scope（生效范围）

```yaml
scope:
  global: true                    # 跟人走，所有项目生效
  projects: []                    # 仅在指定项目中生效（project_id 列表）
  exclude_projects: []            # 在这些项目中不生效
```

**规则**：
- `global: true` 且 `projects` 为空 → 全局生效
- `global: false` 且 `projects` 非空 → 仅指定项目
- `exclude_projects` 优先级高于 global

### 2.3 轴三：Layer（加载时机）

| Layer | 含义 | 注入方式 | 数量控制 |
|---|---|---|---|
| `L0` | 每次对话必须生效 | 写入全局文件 (~/.claude/CLAUDE.md) | ≤ 20 条，总 ≤ 1500 tokens |
| `L1` | 进入特定项目才生效 | 写入项目级文件 | ≤ 30 条/项目，总 ≤ 2000 tokens |
| `L2` | 按需 MCP 检索 | 不写文件，AI 主动查 | 无限制 |

**Layer 降级规则**：
- 如果 L0 总 token 超限，按 priority 降序排列，溢出的自动降级为 L1
- L1 同理降级为 L2
- CLI `echome status` 会提示降级情况

## 3. 单条记忆结构

### 3.1 Markdown + Frontmatter 格式（本地 vault）

```markdown
---
id: workflow-pr-ticket
type: workflow
layer: L0
scope:
  global: true
  projects: []
  exclude_projects: []
priority: 9
tags: [git, pr, ticket, jira]
status: active
title: PR 必须带工单号
created_at: 2026-05-21T10:00:00Z
updated_at: 2026-05-21T10:00:00Z
source: manual
---

所有 PR 的标题必须以 `[JIRA-XXX]` 工单号开头。

规则：
- 如果当前 branch 名包含工单号（如 `feat/JIRA-123-add-login`），默认从 branch 提取
- 否则必须先问用户工单号，不要自己编造
- Hotfix PR 可以用 `[HOTFIX]` 前缀替代
```

### 3.2 数据库 Schema（Hub）

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(64) NOT NULL DEFAULT 'default',  -- 多租户预留
    
    -- 内容
    title           VARCHAR(256) NOT NULL,
    content         TEXT NOT NULL,
    
    -- 三轴
    type            VARCHAR(32) NOT NULL,       -- persona/workflow/tech/...
    layer           VARCHAR(4) NOT NULL,        -- L0/L1/L2
    scope_global    BOOLEAN NOT NULL DEFAULT TRUE,
    scope_projects  JSONB NOT NULL DEFAULT '[]',
    scope_exclude   JSONB NOT NULL DEFAULT '[]',
    
    -- 元数据
    priority        SMALLINT NOT NULL DEFAULT 5,  -- 1-10, 10 最高
    tags            JSONB NOT NULL DEFAULT '[]',
    status          VARCHAR(16) NOT NULL DEFAULT 'active',  -- active/pending/deprecated/archived
    source          VARCHAR(32) NOT NULL DEFAULT 'manual',  -- manual/ai_suggested/imported
    
    -- 向量
    embedding       vector(1536),               -- text-embedding-3-small 维度
    
    -- 时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 索引
    CONSTRAINT valid_type CHECK (type IN ('persona','workflow','tech','constraint','snippet','decision','knowledge','interaction','project')),
    CONSTRAINT valid_layer CHECK (layer IN ('L0','L1','L2')),
    CONSTRAINT valid_status CHECK (status IN ('active','pending','deprecated','archived')),
    CONSTRAINT valid_priority CHECK (priority BETWEEN 1 AND 10)
);

-- 索引
CREATE INDEX idx_memories_user_type ON memories(user_id, type);
CREATE INDEX idx_memories_user_layer ON memories(user_id, layer);
CREATE INDEX idx_memories_user_status ON memories(user_id, status);
CREATE INDEX idx_memories_tags ON memories USING GIN(tags);
CREATE INDEX idx_memories_scope_projects ON memories USING GIN(scope_projects);
CREATE INDEX idx_memories_embedding ON memories USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100);
```

### 3.3 项目表

```sql
CREATE TABLE projects (
    id              VARCHAR(128) PRIMARY KEY,    -- 如 "qzhqzh/EchoMe"
    user_id         VARCHAR(64) NOT NULL DEFAULT 'default',
    name            VARCHAR(256) NOT NULL,
    description     TEXT,
    git_remote      VARCHAR(512),               -- git remote URL，用于自动匹配
    path_patterns   JSONB NOT NULL DEFAULT '[]', -- 本地路径模式匹配
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3.4 同步日志表

```sql
CREATE TABLE sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(64) NOT NULL DEFAULT 'default',
    action          VARCHAR(16) NOT NULL,        -- push/pull/sync
    memories_affected JSONB NOT NULL DEFAULT '[]', -- [memory_id, ...]
    client_info     VARCHAR(256),                -- CLI version, OS
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## 4. 状态生命周期

```
            ┌─────────┐
            │ pending │ ← AI 写入（echome_remember）
            └────┬────┘
                 │ 用户确认 (echome review --approve)
                 ▼
            ┌─────────┐
  手动创建 →│ active  │← 正常使用状态
            └────┬────┘
                 │ 用户标记过时
                 ▼
          ┌────────────┐
          │ deprecated │ ← 不再注入，但保留查询
          └─────┬──────┘
                │ 用户确认删除
                ▼
           ┌──────────┐
           │ archived │ ← 软删除，可恢复
           └──────────┘
```

## 5. 本地 Vault 目录结构

```
~/.echome/
├── config.yaml              # Hub URL、token、默认设置
├── vault/
│   ├── persona/
│   │   └── profile.md
│   ├── workflow/
│   │   ├── pr-ticket.md
│   │   ├── review.md
│   │   └── commit-style.md
│   ├── tech/
│   │   ├── stack.md
│   │   └── boundaries.md
│   ├── constraint/
│   │   └── no-force-push.md
│   ├── project/
│   │   ├── echome.md
│   │   └── other-project.md
│   ├── knowledge/
│   ├── decision/
│   ├── snippet/
│   └── interaction/
├── pending/                 # AI 写入的待审核记忆
│   └── 2026-05-21-xxx.md
└── .state/
    ├── last_sync.json       # 上次同步时间戳
    └── projects.json        # 已注入的项目登记
```

## 6. 检索策略

### 6.1 MCP echome_search 流程

```
1. 接收 query 文本
2. 计算 query embedding
3. 混合检索：
   a. 向量相似度 top-20 (cosine similarity > 0.7)
   b. 全文关键词匹配 top-20
   c. tag 精确匹配
4. 合并去重，按 (similarity * 0.6 + priority * 0.3 + recency * 0.1) 排序
5. 过滤：status=active, scope 匹配当前项目
6. 返回 top-K (默认 K=5)
```

### 6.2 渲染策略（echome sync）

```
1. 拉取 Hub 中 user 的所有 active 记忆
2. 按 layer 分组：
   - L0: scope_global=true 的记忆
   - L1: scope_projects 包含当前 project_id 的记忆
3. 按 priority 降序排列
4. Token 计算（tiktoken），超限则截断（低优先级被降级）
5. 渲染到目标文件
```

## 7. Token 计算

使用 `tiktoken` (cl100k_base encoding) 计算每条记忆的 token 数：

```python
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(enc.encode(text))
```

配置参数（可在 config.yaml 中覆盖）：

```yaml
limits:
  l0_max_tokens: 1500
  l1_max_tokens: 2000
  l0_max_count: 20
  l1_max_count: 30
```

## 8. AI 写入记忆流程

当 AI 调用 `echome_remember` 时：

```
1. AI 提交 {title, content, type, tags, suggested_layer}
2. Hub 创建记忆，status=pending
3. 保存到本地 ~/.echome/pending/ 目录
4. 用户通过 `echome review` 查看待审核列表
5. 用户可以：
   - approve: 确认，状态变为 active
   - edit: 修改后确认
   - reject: 拒绝，状态变为 archived
   - defer: 暂不处理
```

## 9. 版本化与冲突

- 每条记忆有 `updated_at` 时间戳
- push/pull 使用 last-write-wins 策略（单租户，冲突概率极低）
- 本地 vault 本身可以用 git 管理（可选，非必须）
- Hub 保留所有修改历史（通过 sync_log + updated_at）

## 10. 扩展方向

- **团队共享**：type=`shared_workflow`，scope 扩展为 team level
- **自动学习**：对话分析 → 提取偏好 → pending 记忆
- **知识图谱**：记忆之间建立关联（related_ids 字段）
- **时间衰减**：长期未使用的记忆降低 priority
- **导入源**：从 Notion/Obsidian/已有 CLAUDE.md 批量导入
