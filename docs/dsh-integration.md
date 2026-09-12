# DeepSeek Harness 接入 EchoMe

2026-09-12：按本机安装的 `@deepseek-ai/dsh` 和 `@deepseek-ai/dsh-mcp-client` **0.1.1-rc.2** 校验。本指南的兼容范围是该版本的 MCP bridge；不把一次握手等同于整个 DSH 应用或模型任务的验收。

## 配置

先在 EchoMe 环境执行 `echome login`，然后用 DSH 的 patch overlay 加载现有 MCP 插件。替换 Python 的绝对路径；在具体项目目录启动 DSH，并在 context 调用中传明确的项目路径或 canonical ID。

```yaml
- id: mcp-echome
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: echome
    transport: stdio
    command: /absolute/path/to/echome-venv/bin/python
    args: ['-m', 'echome_mcp']
    env:
      ECHOME_MCP_PROFILE: core
    toolCallTimeoutMs: 120000
    failOnStartupError: true
```

```bash
dsh --profile tui --patch /absolute/path/to/echome.patch.yml
```

初次接入用 `failOnStartupError: true`，连接失败会明确中止插件激活。`toolCallTimeoutMs` 只控制工具调用；本版初始化/发现超时由 MCP SDK 控制，调高这个值不能修复 stdio 初始化挂起。显式环境变量请沿用 DSH 的 `!!js process.env.NAME` 写法，不把 token 写进 YAML。

`core` 提供 10 个常用入口；要使用 summary、Project Knowledge、Sleep 等工具，可改为 `full`（当前 32 个）。工具在 DSH 中注册为 `mcp__echome__echome_context` 等名称，wire 上仍使用原始 EchoMe 工具名。无环境变量的历史配置继续使用 `full`。

## 规则文件

本版 `dsh-agent-instructions` 默认读取项目的 `AGENTS.md` 和 `CLAUDE.md`，对同目录内容相同的文件去重；用户级文件是 `$DSH_HOME/AGENTS.md`（默认 `~/.dsh/AGENTS.md`）。已有项目规则可直接复用，因此当前无需新增 DSH 专属 sync target。

`echome sync --target codex --project ...` 会同时更新 Codex 全局文件和项目 `AGENTS.md`；它不会写入 DSH 全局目录。只接入 DSH 时优先使用 MCP，并维护已有项目规则文件。不要把 Codex 全局同步命令当作 DSH 全局同步。

## 可重复检查

先执行通用安装握手，再检查已安装 DSH bridge：

```bash
python scripts/smoke_mcp_stdio.py --python /absolute/path/to/echome-venv/bin/python
node scripts/smoke_dsh_mcp.mjs /absolute/path/to/node_modules/@deepseek-ai/dsh /absolute/path/to/echome-venv/bin/python
```

检查覆盖真实 stdio 初始化、core/full 工具发现、DSH 命名、capabilities 调用、文本与 structuredContent、关闭后工具清理。测试只替换宿主注册表和生命周期，不调用 LLM 或生产 Hub。安装来源的实现和说明位于 DSH 包内 `node_modules/@deepseek-ai/dsh-mcp-client/{README.md,lib/index.js}` 与 `dsh-agent-instructions/README.md`；上游仓库为 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)。

若 stdio 只在特定执行沙箱超时，应在普通终端运行同一条 smoke 对照；本次已确认当前 Codex 执行沙箱的异步管道限制会造成这种差异。
