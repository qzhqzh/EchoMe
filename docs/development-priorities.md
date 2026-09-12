# EchoMe 开发优先级与交付进度

> 2026-09-12 开发验收记录：本轮按优先级完成 9 项实现及验证，并将已确认的 GPU embedding、Docker 构建和记忆可信度策略改动纳入同批交付。合并、issue 和包发布状态以对应 GitHub 记录为准；服务部署须单独验证运行版本。

## 本轮开发顺序与结果

| 顺序 | 级别 | Issue | 本轮实现 | 验证证据 |
|---|---|---|---|---|
| 1 | P1 | [#86 MCP 初始化](https://github.com/qzhqzh/EchoMe/issues/86) | 确认当前执行沙箱的异步 stdio 限制；保留有效入口，新增安装 smoke 并接入 CI | 干净 wheel、非源码 cwd，CLI/module × core/full 四组 initialize、list、capabilities 全通过 |
| 2 | P1 | [#108 多仓库身份](https://github.com/qzhqzh/EchoMe/issues/108) | 从显式本机绝对目录采集该仓库 Git 信号；api/web 父项目仅作为待确认候选 | 真 Git fixture + PostgreSQL OKB 双路径/双 remote/alias；歧义不创建，未知项目不混入宿主目录 |
| 3 | P1 | [#109 项目排除](https://github.com/qzhqzh/EchoMe/issues/109) | Memory list/search/render/compiler 共用排除条件；全局静态文件省略带项目例外的规则 | 真实 JWT/REST/SQL 验证 canonical 与 legacy alias、允许项目、跨用户隔离 |
| 4 | P1 | [#110 向量写回](https://github.com/qzhqzh/EchoMe/issues/110) | 按 ID + 当前完整 embedding 文本做原子条件写回；跳过失活/被替代目标；sync 改正文清空旧向量 | 受控并发覆盖新内容、元数据变更、归档、deprecated、删除、替代 6 种情况；保留业务 updated_at |
| 5 | P1 | [#111 最终输出预算](https://github.com/qzhqzh/EchoMe/issues/111) | 可选 compact 投影、完整输出统计与同用户诊断；必要规则放不下时明确失败 | 4 路由 × 3 策略、低预算、中英文大正文、旧 Hub/缓存附加开销；run 区分编译选中与实际交付 IDs |
| 6 | P1 | [#112 生命周期回归](https://github.com/qzhqzh/EchoMe/issues/112) | 每用例随机 schema；新增真实认证/写入/检索/归档/feedback/outcome、并发、scope 与输出链路，接入 CI | 21 条数据库集成用例；空库 Alembic 001–018 升级成功；原有 31 条质量评估保留 |
| 7 | P2 | [#114 文档契约](https://github.com/qzhqzh/EchoMe/issues/114) | 当前指南 JSON、CLI 命令/参数、10 类型、MCP schema/调用、API 路由/请求、相对链接检查 | client/hub 两个门禁通过；错误命令、枚举、字段、required、链接会失败 |
| 8 | P2 | [#113 Type/Scope](https://github.com/qzhqzh/EchoMe/issues/113) | 10 类记忆都可绑定已有项目，active alias 归一为 canonical ID；全局默认与 ai_review 保持兼容 | 10 类型逐项测试；全局别名兼容；未知/歧义/未授权项目不写入、不创建 |
| 9 | P2 | [#87 DSH 接入](https://github.com/qzhqzh/EchoMe/issues/87) | 新增当前接入指南和可重复 bridge smoke；复用已有 AGENTS.md | 本机 DSH 0.1.1-rc.2 实际 MCP bridge core 10/full 32 工具、调用、文本/structuredContent、清理全部通过 |

## 验证范围

- CLI/MCP 全量：**75 passed**。
- Hub 全量：**249 passed、1 skipped**；最终增量（含新增第 21 条数据库用例）相关回归：**33 passed**。唯一跳过的是旧的外部数据库开关测试，本轮隔离数据库用例均实际执行。
- Root/Hub ruff、版本真相检查、client/hub 文档契约检查通过。
- PostgreSQL 使用专用 `echome_test` 临时容器和随机 schema，无生产数据访问；没有新增 migration。
- DSH 测的是已安装 bridge 的真实 stdio/工具边界，宿主注册表和生命周期为最小 fixture；未调用 LLM，也未宣称完成 DSH 全应用验收。
- 没有启动界面预览或部署服务；这是后端、MCP、文档与 CI 改动。

## 同批纳入的运行配置与发布修正

- Embedding 固定 Sentence Transformers 6.0.0、PyTorch 2.7.1 CUDA 11.8 并纳入 lockfile；模型改为预先下载、只读挂载，明确 GPU/FP16 和输入长度限制。模型下载依赖移到可选依赖组，Hub 和 embedding 镜像排除本机环境与测试文件，并按各自 lockfile 安装依赖，避免与 CI 漂移。启动前提见[部署指南](deployment.md)。
- `ai_review` 明确标为 provisional 并附警告，`pending` 标为 quarantined 并拒绝注入；正文安全检查先于 embedding 输入截断。
- 发布工作流同步 README、AGENTS、CLAUDE、MCP 规范及其他版本说明，验证干净 wheel 的 stdio 握手；发布开始时核对 main 未前移，避免发布未经确认的新提交。
- 包发布记录与 Hub 部署事实分开维护，避免仅发布 PyPI 就把运行服务标为新版本。

## 交付流程

1. 在短分支审阅、提交本轮实现与已授权的运行配置改动，保留未纳入本轮的历史分支工作。
2. 远端 CI 在干净 Python 3.11/pgvector 环境通过后合并，按同一顺序关闭对应 issue。
3. 由现有 Publish to PyPI 工作流统一提升版本、创建 GitHub Release 并发布 PyPI，再同步本地主线。
4. Hub 部署与现有客户端 MCP 进程更新另行执行；部署验收需复核 runtime health、scope、compact 与客户端连接。

`compact` 使用 UTF-8 字节作为单份 JSON 的保守 token 上界，不代表模型精确计费，也不包含重复注入两份 MCP 表示的开销。默认完整响应继续兼容。细节见 [MCP 规范](mcp-spec.md)、[开发验证](development-checks.md)和 [DSH 接入](dsh-integration.md)。
