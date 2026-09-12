# EchoMe 用户指南

> 面向当前 v1.8 发布基线及主线工作流，校准于 2026-09-12。具体工具以运行中的 capabilities 为准，完整边界见 [记忆模型](memory-model.md)。

---

## 目录

1. [安装](#1-安装)
2. [初始化](#2-初始化)
3. [添加记忆](#3-添加记忆)
4. [同步记忆到 AI CLI](#4-同步记忆到-ai-cli)
5. [项目级记忆管理](#5-项目级记忆管理)
6. [配置 MCP Server](#6-配置-mcp-server)
7. [在 Claude Code 中测试 MCP](#7-在-claude-code-中测试-mcp)
8. [更新与清理](#8-更新与清理)
9. [日常工作流](#9-日常工作流)
10. [常见问题](#10-常见问题)
11. [命令速查表](#11-命令速查表)

---

## 1. 安装

### 前提条件

- Python 3.11+
- 可访问的 EchoMe Hub 和登录凭据；自托管步骤见 [部署指南](deployment.md)

### 安装（推荐）

```bash
pip install --upgrade echome
```

CLI 和 MCP 已在同一个包中，无需额外安装 `[mcp]`。源码开发请在仓库根目录运行 `uv sync --locked --extra dev`，详见 [贡献指南](../CONTRIBUTING.md)。

### 验证安装

```bash
echome          # 显示欢迎界面 + 状态
echome --help   # 查看所有命令
```

> **注意**：`eme` 是 `echome` 的短别名，两者完全等价。

---

## 2. 初始化

```bash
echome init
```

初始化会询问 Hub URL 和 token；新配置的默认 URL 为 `https://echome.qzhqzh.com`，可替换为你的部署地址。登录与 token 获取可使用 `echome login` 或 Web Console 的 GitHub 登录入口。

初始化会保存 `~/.echome/config.yaml`，并创建预留的本地目录。记忆仍保存在 Hub，本地 vault 文件双向同步尚未实现。

提供连接参数：

```bash
echome init --hub-url https://hub.example.com --token YOUR_TOKEN
```

该调用仍会询问是否注册 MCP；需要跳过时增加 `--skip-mcp`。注册默认使用 core profile，Claude Code 采用 user scope，Codex 写入 `~/.codex/config.toml`。初始化显示的 Hub 连接成功不等于 MCP 已完成握手，需重启客户端并实际调用工具验证。

跳过 MCP 注册：

```bash
echome init --skip-mcp
```

---

## 3. 添加记忆

### 三种方式

```bash
# 方式 1：快速模式（全部用参数）
echome add "PR必须带工单号" \
  -c "所有 PR 标题必须以 [JIRA-XXX] 开头" \
  -t method --layer L0 -p 9 --tags "git,pr"

# 方式 2：半交互（给标题，其余交互）
echome add "开发环境用 docker-compose"

# 方式 3：全交互
echome add
```

### 参数说明

| 参数 | 说明 | 示例 |
|---|---|---|
| 第一个参数 | 标题 | `"PR必须带工单号"` |
| `-c` / `--content` | 详细内容 | `"标题以[JIRA-XXX]开头"` |
| `-t` / `--type` | 类型 | `method` / `stack` / `guardrail` / ... |
| `--layer` / `-l` | 层级 | `L0` / `L1` / `L2` |
| `-p` / `--priority` | 优先级(1-10) | `9` |
| `--tags` | 标签(逗号分隔) | `"git,pr,ticket"` |

### Layer 选择标准

| Layer | 静态写入位置 | 适合放什么 | 默认正文预算 |
|---|---|---|---|
| **L0** | 全局 Claude/Codex 配置 | 常驻规则、通用偏好 | 1500 tokens |
| **L1** | 指定项目的配置 | 项目规则，需同时设置 scope | 项目渲染合并 L0 + L1，共 3500 tokens |
| **L2** | 不写静态文件，MCP 按需查 | 详细背景、历史知识 | 由查询预算和返回条数控制 |

预算由 Hub 配置，超出时跳过条目；20/30 条不是当前渲染器执行的硬限制，也不会自动修改 layer。引导段和元数据会增加最终输出长度。Claude 使用 `CLAUDE.md`，Codex 使用 `AGENTS.md`。

### 记忆类型

| Type | 说明 | 示例 |
|---|---|---|
| `identity` | 身份背景 | 职责、背景 |
| `method` | 工作流规范 | PR 规范、review 要求 |
| `stack` | 技术偏好 | 用什么 linter、框架选型 |
| `guardrail` | 红线禁忌 | 禁止 force push |
| `reasoning` | 思考方法 | 判断原则、决策框架 |
| `template` | 可复用片段 | Docker 模板 |
| `decision` | 设计决策 | 为什么选 FastAPI |
| `context` | 领域知识 | 业务术语 |
| `style` | 对话偏好 | 中文回答、先结论后分析 |
| `project` | 项目上下文 | 项目目标、技术栈 |

### 记忆示例

以下为写法示例，按自己的实际规范调整后再保存。

```bash
# 工作流
echome add "PR必须带工单号" \
  -c "所有 PR 标题必须以 [JIRA-XXX] 工单号开头。如果 branch 名包含工单号（如 feat/JIRA-123-add-login），从 branch 提取；否则必须先问用户。" \
  -t method --layer L0 -p 9 --tags "git,pr,ticket"

# 技术偏好
echome add "Python 用 ruff 格式化" \
  -c "所有 Python 项目统一使用 ruff 做 lint 和格式化，不用 black/flake8/isort" \
  -t stack --layer L0 -p 7 --tags "python,lint"

# 约束红线
echome add "禁止 force push" \
  -c "不允许 git push --force 到 main/master。个人分支用 --force-with-lease" \
  -t guardrail --layer L0 -p 10 --tags "git,safety"

# 沟通偏好
echome add "中文回答，先结论后分析" \
  -c "回答用中文。先给结论，再展开分析。有疑问先反问确认。" \
  -t style --layer L0 -p 8 --tags "style"
```

### 查看记忆

```bash
echome list                    # 列出所有
echome list --type method    # 按类型
echome list --layer L0         # 按层级
echome list --status ai_review # AI 建议的待审核记忆
echome search "PR 规范"        # 搜索
```

---

## 4. 同步记忆到 AI CLI

### 全局同步（L0 → ~/.claude/CLAUDE.md）

```bash
echome sync
```

CLI 按检测结果选择 Claude/Codex；也可用 `--target claude` 或 `--target codex` 指定。以下是 Claude 全局文件的简化示例：

```markdown
你原有的内容（不动）

<!-- echome:begin -->
## EchoMe Context (auto-managed, do not edit this block)

### Workflow Rules
- **PR必须带工单号**: 所有 PR 标题必须以 [JIRA-XXX] 工单号开头...

### Technical Preferences
- **Python 用 ruff 格式化**: 所有 Python 项目统一使用 ruff...

### EchoMe Memory System (MANDATORY)
首次使用先调用 `echome_capabilities`。首条任务消息后调用 `echome_context`，传入任务和已知项目线索；命中规范时简短复述。后续按需查询，无命中就停止；涉及过时信息时检查来源，任务完成后按 completion contract 提交 outcome。
...
<!-- echome:end -->

你原有的内容（不动）
```

**关键点**：
- 默认只有全局 scope 的 L0 有效记忆（active + ai_review）会写入全局文件
- 只修改 `<!-- echome:begin -->` 和 `<!-- echome:end -->` 之间的内容
- marker 之外的原有内容**绝不触碰**
- 每次 sync 是**整体替换** marker 区（增删都干净，不会有残留）

### 查看同步状态

```bash
echome status
```

`echome status` 展示当前目录及全局/项目文件的注入状态。连接与运行环境排障使用 `echome doctor`；MCP 的真实能力和依赖健康通过客户端调用 `echome_capabilities`、`echome_runtime_health` 检查。

---

## 5. 项目级记忆管理

### 添加项目记忆

先在 Web Console 确认项目的 canonical ID。创建项目记忆时设置：

- `layer`：**L1**
- `scope.global`：`false`
- `scope.projects`：已存在的 canonical project ID

MCP 可调用 `echome_remember`，保留 `decision/method/guardrail` 等合适的类型，传已存在的 `project` 和 `suggested_layer="L1"`。所有类型均可绑定项目；active alias 会解析为 canonical ID，未知或歧义项目不会写入记忆。

当前 `echome add` 没有项目 scope 参数；仅设置 `--layer L1` 不会将记忆绑定到项目。

### 同步项目记忆到当前项目

```bash
cd ~/projects/EchoMe
echome sync --project qzhqzh/EchoMe
```

这会刷新全局 L0，并在当前目录的目标配置中写入全局 L0 + 匹配项目的 L1。以下为 Claude 的简化示例；Codex 对应 `AGENTS.md`：

```markdown
项目原有内容（不动）

<!-- echome:begin -->
## EchoMe Context (auto-managed, do not edit this block)

### Project Details
- **EchoMe 技术栈**: FastAPI + SQLAlchemy + Vue 3...
<!-- echome:end -->

项目原有内容（不动）
```

### 与全局的区别

| | 全局 (L0) | 项目 (L1) |
|---|---|---|
| 文件 | `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md` | `./CLAUDE.md` / `./AGENTS.md`（当前目录） |
| 可见范围 | 所有对话 | 只有在该项目目录下的对话 |
| 适合放 | 硬规矩、通用偏好 | 项目专属技术栈、架构约定 |

### 更新项目记忆

在 Web 页面修改 L1 记忆后，需要重新 sync：

```bash
cd ~/projects/EchoMe
echome sync --project qzhqzh/EchoMe
```

**sync 每次从 Hub 获取最新渲染结果，全量替换 marker 区**；是否选入仍受状态、scope、layer 和预算影响。项目 context 的 workspace 继承、路径选择尚未复用到静态 sync；带项目参数时的排除规则已经统一，不能用静态文件代替任务上下文查询。

### 移除项目记忆

```bash
echome eject --scope project    # 只清当前项目
echome eject --scope global     # 只清全局
echome eject --scope all        # 全部清除
```

---

## 6. 配置 MCP Server

### 自动配置（推荐）

`echome init` 会询问是否注册 MCP；已初始化后可单独注册：

```bash
echome mcp install
```

### MCP 注册后的配置文件

Claude Code 优先通过官方 CLI 注册为 user scope；直接写配置的回退路径是 `~/.claude.json`：

```json
{
  "mcpServers": {
    "echome": {
      "type": "stdio",
      "command": "echome",
      "args": ["mcp", "serve"],
      "env": {"ECHOME_MCP_PROFILE": "core"}
    }
  }
}
```

Codex 使用 `~/.codex/config.toml`：

```toml
[mcp_servers.echome]
command = "echome"
args = ["mcp", "serve"]
env = { ECHOME_MCP_PROFILE = "core" }
enabled = true
```

新安装默认 core；需要摘要检索、Project Knowledge 或 Sleep 等专业工具时显式设置 `ECHOME_MCP_PROFILE=full`。没有配置该变量的历史客户端继续使用 full。具体列表见 [MCP 规范](mcp-spec.md)。

### 验证入口与实际连接

```bash
echome mcp serve --help
```

这只能确认 CLI 命令存在。直接运行 `echome mcp serve` 会等待客户端发送 JSON-RPC 初始化请求；终端安静不代表失败，也不会主动打印可供人工阅读的握手信息。

配置或更新包后重启 Claude Code / Codex，再由客户端完成 MCP 初始化并调用 `echome_capabilities`、`echome_runtime_health`。包版本相同也可能加载不同能力，以实际返回值为准。

---

## 7. 在 Claude Code 中测试 MCP

重启 Claude Code 后，EchoMe MCP 自动注册为可用 tool。

### 测试场景

**场景 1：查询工作流规范**

```
你：我提 PR 有什么规范？
```

预期：Claude 使用 `echome_context` 获取相关规范；首次使用先做 capabilities 发现。没有相关记忆时应明确说明，不能编造规范。

**场景 2：AI 写入新规则或主动提出候选记忆**

```
你：以后所有 Python 项目都用 pytest，记住这个。
```

预期：Claude 调用 `🔧 Using tool: echome_remember`，保存为 ai_review 记忆。即使你没有明确说"记住"，当它观察到稳定偏好、项目决策或工作流约定时，也可以主动写入 ai_review。ai_review 会立即参与后续检索；你可以用 `echome review` 做事后清理或提升为 active。

**场景 3：强制触发**

```
你：请调用 echome_context，查询与“Git 提交规范”有关的记忆。
```

预期：Claude 直接调用 tool 并返回结果。

### 能直观看到 MCP 调用吗？

客户端通常会展示工具调用记录，具体 UI 文案随客户端版本变化。查看调用名、输入和输出即可，不应把某个固定图标或文本当成成功标准。

### 如果 MCP 没被调用

1. 确认 `echome mcp serve --help` 可用，并核对客户端 MCP 配置。
2. 重启客户端，查看其 MCP 初始化或连接错误。
3. 先实际调用 `echome_capabilities`，再调用 `echome_runtime_health` 检查 Hub 与依赖。
4. 确认目标 `CLAUDE.md` / `AGENTS.md` 含同步生成的 Memory System 引导。
5. core profile 使用 `echome_context`；`echome_search` 等专业工具需要 full。

---

## 8. 更新与清理

### 更新 EchoMe CLI

```bash
# 按安装方式更新；editable 开发安装只给出手动更新提示
echome update

# PyPI 安装也可直接升级
pip install --upgrade echome
```

源码开发安装按仓库分支策略更新代码后运行 `uv sync --locked --extra dev`。更新后重启 MCP 客户端，并重新同步引导：

```bash
echome sync
```

### 更新 Hub 服务

按 [部署指南](deployment.md) 完成配置、备份、迁移与服务验证。不要仅根据 CLI 包升级或源码版本号判断 Hub 已部署成功。

### 清理/重置

```bash
# 只清除全局 CLAUDE.md 中的 EchoMe 区块
echome clean --scope global

# 只清除当前项目的注入
echome clean --scope project

# 全部清除
echome clean

# 核弹级：清除所有 + 删除 Hub 上全部记忆（会二次确认）
echome clean --delete-hub-data
```

### eject vs clean

| 命令 | 作用 |
|---|---|
| `echome eject` | 只移除文件注入（不删 Hub 数据） |
| `echome clean` | 同上 + 可选 `--delete-hub-data` |

---

## 9. 日常工作流

### 日常使用（什么都不用做）

L0 已在 CLAUDE.md 里，MCP 按需自动查询。正常和 AI 对话即可。

### 添加新规范

```bash
echome add "新规则" -c "描述" -t method --layer L0
echome sync    # 刷新 CLAUDE.md
```

### AI 建议了新记忆

```bash
echome review              # 逐条审核
echome review --approve-all   # 全部通过
echome review --reject-all    # 全部拒绝
```

### 切换项目

```bash
cd ~/work/another-project
echome sync --project user/another-project
```

### 新机器/新环境恢复

```bash
pip install --upgrade echome
echome init --hub-url https://hub.example.com --token YOUR_TOKEN
echome sync
# 从 Hub 渲染全局 L0；项目 L1 另加 --project，L2 由 MCP 按需查询
```

### 记忆更新后的同步

| 你改了什么 | 需要做什么 |
|---|---|
| 在 Web 页面改了 L0 记忆 | 运行 `echome sync` |
| 在 Web 页面改了 L1 记忆 | 运行 `echome sync --project xxx` |
| 在 Web 页面改了 L2 记忆 | 不需要做任何事（MCP 实时从 Hub 查） |
| AI 通过 MCP 写了记忆 | MCP 可立即查询；若要更新 L0/L1 静态文件，仍需对应的 sync |
| 删除或归档了某条记忆 | 刷新受影响的全局/项目注入；项目使用 `echome sync --project ID` |

---

## 10. 常见问题

### Q: 添加了记忆但 CLAUDE.md 没变？

默认只有全局 scope、有效状态的 **L0** 会同步到全局文件，还受正文预算影响。检查：
```bash
echome list --layer L0
```
如果确实需要常驻规则，可调整为全局 L0 后运行 `echome sync`；详细知识保留 L2，由 MCP 按需查询。

### Q: MCP 配了但 Claude 不调用？

1. 确认 `~/.claude.json` 的 user-scope MCP 配置有效
2. **重启 Claude Code**
3. 确认 `~/.claude/CLAUDE.md` 有 MANDATORY 引导段
4. 用明确指令测试：`"请调用 echome_context 查询 Git 提交规范"`

### Q: `echome add "xxx"` 报错？

先用 `echome version`、`echome add --help` 和 `echome doctor` 检查版本、参数和连接。使用规范的记忆类型；需要升级时按第 8 节对应安装方式处理。

### Q: 怎么删除一条记忆？

- Web 页面操作（推荐）
- 或 API：`curl -X DELETE http://hub:20000/api/v1/memories/UUID -H "Authorization: Bearer TOKEN"`

### Q: 项目记忆怎么更新到本地？

在 Hub/Web 改了项目记忆后：
```bash
cd ~/your-project
echome sync --project your/project-id
```

### Q: sync 会覆盖 CLAUDE.md 的其他内容吗？

**不会。** 只修改 `<!-- echome:begin -->` 到 `<!-- echome:end -->` 之间的部分。marker 之外的内容原封不动。

### Q: L0 内容超过预算会怎样？

当前不按 20 条硬截断，而是在 Hub 的正文预算内按类型顺序和优先级选择记忆，跳过的条目会在 sync 时提示。不会自动改变 layer；可精简常驻规则，或自行把详细内容调整为 L2。

### Q: `echome` 命令被其他程序占了？

用别名 `eme`（完全相同的功能）：
```bash
eme sync
eme status
eme add "xxx"
```

---

## 11. 命令速查表

| 命令 | 作用 |
|---|---|
| `echome` | 显示欢迎界面 + 状态 |
| `echome init` | 初始化 + 连接 Hub + 注册 MCP |
| `echome add` | 添加记忆（交互/快速） |
| `echome list` | 列出记忆 |
| `echome search "xxx"` | 搜索记忆 |
| `echome sync` | 渲染全局 L0 到 Claude/Codex 配置 |
| `echome sync --project ID` | 刷新全局 L0，并渲染 L0 + 匹配项目的 L1 |
| `echome status` | 查看全局/项目文件的注入状态 |
| `echome doctor` | 检查安装、配置与连接 |
| `echome review` | 审核 AI 建议的记忆 |
| `echome update` | 更新到最新版 |
| `echome clean` | 清除注入（可选删 Hub 数据） |
| `echome eject` | 同 clean 但不删 Hub 数据 |
| `echome mcp install` | 注册 MCP 到 Claude/Codex |
| `echome mcp serve` | 启动由客户端连接的 MCP server |
| `echome push` / `echome pull` | 文件同步保留命令，当前未实现 |
| `echome detect` | 检测当前目录的 AI CLI |
| `echome --help` | 所有命令帮助 |
