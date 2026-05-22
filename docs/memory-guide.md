# EchoMe 记忆编写指南

> 好的记忆让 AI 更像你的同事，而不是一个陌生人。

## 记忆类型（Type）与优先级

EchoMe 的 9 种记忆类型按**渲染优先级**排列如下——优先级越高，在 token 有限时越不会被截断：

| 优先级 | Type | 含义 | 影响什么 |
|--------|------|------|----------|
| 1 (最高) | `persona` | 人格基线 | AI 的角色定位、语气、性格 |
| 2 | `constraint` | 红线与禁忌 | 绝对不能做的事 |
| 3 | `workflow` | 工作流程 | 解决问题的方法论和标准流程 |
| 4 | `tech` | 技术偏好 | 语言、框架、工具链选择 |
| 5 | `interaction` | 交互风格 | 输出格式、沟通方式、长度偏好 |
| 6 | `decision` | 决策记录 | 历史技术决策和原因 |
| 7 | `knowledge` | 领域知识 | 业务逻辑、架构上下文 |
| 8 | `snippet` | 代码模板 | 可复用的代码片段 |
| 9 (最低) | `project` | 项目背景 | 特定项目的介绍和约定 |

---

## 各类型写作指南

### persona — 定义"你是谁"

这是**最重要**的记忆类型。它定义了 AI 和你交互的基调。

**好的 persona 记忆**：
```
标题：交互基调
内容：
- 你是我的技术合伙人，不是客服
- 说话简洁直接，不要"当然可以！"这种客套
- 不确定的事情直接说"我不确定"，不要编
- 给建议时像资深同事讨论，不是给初学者教学
```

**Layer 建议**：L0（每次对话都加载）

---

### constraint — 定义"绝对不能做什么"

约束比指令更有效——告诉 AI "不要做什么" 比 "要做什么" 更容易被遵守。

**好的 constraint 记忆**：
```
标题：代码安全红线
内容：
- 永远不要删除数据库 migration 文件
- 不要用 git push --force 到 main/master
- 不要在代码中硬编码密码、token、API key
- 不要改已上线 API 的响应结构（向后兼容）
- 不要引入新依赖而不说明原因
```

**Layer 建议**：L0

---

### workflow — 定义"怎么做事"

方法论和流程。让 AI 像老手一样有章法。

**好的 workflow 记忆**：
```
标题：Bug 修复流程
内容：
1. 先复现问题，确认 steps to reproduce
2. 定位范围（哪个模块、哪个函数）
3. 用最小改动修复，不要顺手重构
4. 验证修复有效，且没有引入新问题
5. commit message 写清 root cause
```

```
标题：PR 规范
内容：
- commit 用 conventional commits 格式
- PR 标题不超过 70 字符
- 描述包含：改了什么、为什么改、怎么测的
- 一个 PR 只做一件事
```

**Layer 建议**：L0（通用流程）或 L1（项目专属流程）

---

### tech — 定义"用什么技术"

技术栈偏好，帮 AI 在有多种选择时做正确决策。

**好的 tech 记忆**：
```
标题：Python 技术栈
内容：
- Python 3.11+，类型注解必须
- Web 框架：FastAPI（不用 Flask/Django）
- ORM：SQLAlchemy 2.0 async
- Linter：ruff（不用 black/flake8/pylint）
- 包管理：uv（不用 pip/poetry）
- 测试：pytest
```

**Layer 建议**：L0（全局）或 L1（项目级别）

---

### interaction — 定义"怎么输出"

控制 AI 的输出格式和沟通方式。

**好的 interaction 记忆**：
```
标题：输出偏好
内容：
- 用中文交流，代码和变量名用英文
- 改代码前先说思路（1-2 句），再给代码
- 不要一次改超过 3 个文件，改多了分批
- 给选择题时列出选项让我决定，不要自己选
- 代码块标注语言和文件路径
```

**Layer 建议**：L0

---

### decision — 记录"为什么这样选"

决策记录，帮 AI 理解历史上下文，避免推翻已有决定。

**好的 decision 记忆**：
```
标题：选择 PostgreSQL 而不是 MySQL
内容：
2025-03 决定。原因：
- 需要 pgvector 做向量搜索
- JSONB 原生支持比 MySQL JSON 更好
- 团队更熟悉 PG
代价：部署比 MySQL 稍复杂，可接受
```

**Layer 建议**：L1 或 L2

---

### knowledge — 存储"领域知识"

业务逻辑、架构知识、不容易从代码中推断的上下文。

**好的 knowledge 记忆**：
```
标题：部署架构
内容：
- 生产环境：单台 GPU 服务器（Ubuntu 22.04）
- Docker Compose 部署所有服务
- 反向代理：Caddy（自动 HTTPS）
- 域名：echome.qzhqzh.com
- GitHub OAuth 回调：https://echome.qzhqzh.com/login
```

**Layer 建议**：L1（项目级）或 L2（大段文档）

---

### snippet — 可复用代码模板

**好的 snippet 记忆**：
```
标题：FastAPI 路由模板
内容：
\```python
@router.post("/{id}/action", response_model=ResponseSchema)
async def action_handler(
    id: uuid.UUID,
    body: RequestSchema,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> ResponseSchema:
    """Action description."""
    ...
\```
```

**Layer 建议**：L2（按需搜索）

---

### project — 项目自我介绍

当 AI 进入一个项目目录时需要知道的背景。

**好的 project 记忆**：
```
标题：EchoMe 项目概述
内容：
EchoMe 是一个跨 AI 的个人上下文同步层。
- Hub: FastAPI + PostgreSQL + pgvector
- CLI: typer + rich
- Web: Vue 3 + TypeScript + TailwindCSS
- 目标用户: 国内开发者
- 部署在: https://echome.qzhqzh.com
```

**Layer 建议**：L1（绑定到具体项目的 scope）

---

## Layer 选择指南

| Layer | 何时加载 | 适合放什么 |
|-------|----------|-----------|
| **L0** | 每次对话都加载 | persona, constraint, 核心 workflow, 全局 tech |
| **L1** | 进入特定项目时加载 | 项目规范、项目 tech stack、项目 workflow |
| **L2** | AI 按需搜索 | 大段知识、snippet、历史 decision |

**原则**：L0 精简（< 1500 tokens），放"定义你是谁"的内容。细节放 L2。

---

## 写记忆的 5 个原则

1. **具体 > 抽象**："用 ruff，不用 black" 比 "用好的 linter" 有效 10 倍
2. **约束 > 指令**："不要删 migration" 比 "小心处理数据库" 有效
3. **少即是多**：L0 不要超过 10 条，每条精炼到 1-3 行
4. **可验证**：好的记忆是 AI 可以据此做出明确行动的
5. **定期回顾**：过时的记忆比没有记忆更有害
