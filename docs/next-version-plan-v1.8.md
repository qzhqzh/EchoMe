# EchoMe v1.8 候选计划：可信记忆闭环

状态日期：2026-08-26。

本计划针对一个反复出现的问题：单次修正文档、记忆或检索规则后，系统仍可能因为旧状态、缺失反馈或弱评估门槛再次给出同类错误。v1.8 不引入新的主存储，也不自动改写权威记忆；重点是把正确性变成可执行协议和持续门禁。

## 目标

1. 当前版本、数据库 revision 和 MCP 能力契约只能从仓库事实推导，CI 阻止文档漂移。
2. 记忆质量不再只看 Recall，而是覆盖状态变化、工作流、环境陷阱和错误前提。
3. 强客户端 AI 可以生成高质量 mental model，但每条结论必须引用证据，来源变化后不得写入。
4. Context 使用结果形成 append-only 闭环；没有信号时明确记录 `no_signal`，不打扰用户评分。
5. Hub 成为敏感信息最终信任边界，客户端遗漏过滤时仍不能写入或发送到 embedding 服务。

## 已实现

### 项目真相门禁

- `scripts/check_project_truth.py` 从 `pyproject.toml`、Alembic 图和 capabilities 源码推导当前事实。
- CI 同时检查包版本、单一 Alembic head、权威文档和已知过时说法。
- 发布 workflow 更新稳定版本文档并在提交前重新验证。

### Context 完成契约

- recorded、non-shadow Context Run 返回 `echome.context-completion.v1`。
- 客户端在任务结束时通过幂等 `echome_context_outcome` 追加结果。
- 缓存降级结果不要求回执；Web Retrieval Logs 展示 outcome 和 policy effect。
- MCP 的严格成功 schema 接受统一 `echome.error.v1`，服务端错误不会再被结构化输出校验吞掉。

### Memory Quality Eval v2

- 固定数据集从 26 条升级为 31 条，覆盖五类能力：static state recall、dynamic state tracking、workflow knowledge、environment gotchas 和 premise awareness。
- 总门禁同时检查 Recall、case success、evidence precision、stale answer、conflict、abstention、constraint adherence、impact、preflight 和 sensitive path leak。
- “Recall 满分但未报告过时前提”会明确失败。
- Web Eval 展示五类能力的独立成功率；任一能力的 case success 低于门槛时，即使总体指标通过也会阻断 snapshot。

### Evidence-backed Reflect

- `echome_reflect_prepare`：只读返回项目上下文、相关事件、当前派生视图、允许引用的来源 ID 和服务端来源指纹。
- `echome_reflect_submit`：要求每条 claim 引用 prepared memory、constraint、artifact 或 event，并携带幂等键。
- Hub 在提交时重新计算来源版本与状态；任何来源变化、跨项目引用或 prepared 集合外引用均返回冲突，不写数据库。
- prepare 会比对实际返回正文的来源 token 与最终 watermark，避免正文和指纹来自不同快照。
- 派生正文由 Hub 从已验证 claims 渲染；producer 由服务端标记，客户端不能夹带无证据正文或伪装为 system。
- 通过后只新增 `knowledge_view`，可选 supersede 旧视图；Memory、Constraint、Artifact 和 Event 不被改写。
- 新派生视图保存逐来源版本 token，Context Compiler 可识别四类来源变化并回源。

### 服务端敏感信息防线

- Hub 对 Memory CRUD/sync、Sleep proposal、artifact、constraint、evidence、event、feedback、outcome、project metadata 和 knowledge view 等写路径执行高置信度扫描。
- `.env`、私钥材料、Bearer/JWT、常见 provider token、凭据赋值和 URL credential 被拒绝；模板占位符允许通过。
- 错误只返回 finding 类型和行号，不回显疑似 secret。
- 敏感形态的检索任务仍可使用本地 lexical 路径，但不会发送到 embedding 服务，也不会创建 Context Run。
- embedding 客户端自身执行最后一道扫描；历史 artifact/constraint 重建遇到敏感项时只跳过并报告，不删除或改写原数据。

### MCP 能力发现

- capabilities 契约升级为 `echome.capabilities.v6`。
- full profile 明确说明 Reflect 的 prepare/submit 时机、证据要求和来源不变式。
- core profile 继续保持 8 个高频工具，避免默认工具面膨胀。

## 数据安全与兼容性

- 本轮不新增 Alembic migration，生产 schema 仍为 `017`。
- 不删除、覆盖或批量修改现有 Memory、Artifact、Constraint、Event、edge 或 view。
- 既有 REST v1 客户端仍可创建 derived view，并按 artifact ID watermark 兼容读取、标记为低保障契约；新客户端应走 Reflect，使用严格的逐来源版本 token。
- REST v1、Memory Sleep v1/v2、旧 MCP 文本输出和历史 full profile 保持兼容。
- Reflect、自动化和 Context Policy 均不获得静默修改权；Context Policy 继续保持 shadow。

## 当前验收

- Root CLI/MCP：`32 passed`。
- Hub：`186 passed, 1 skipped`。
- Root 与 Hub Ruff：通过。
- Web：TypeScript 检查和 Vite production build 通过。
- Project truth：`version=1.7.1, alembic_head=017, capabilities=echome.capabilities.v6`。

## 发布前剩余步骤

1. 在当前生产数据上运行只读 runtime health、project context、preflight 和 Reflect prepare smoke。
2. 运行一条新的 Project Quality snapshot，确认五能力真实结果；snapshot 只追加评估记录。
3. 检查敏感内容防线对真实 artifact index 的误报，不上传被拒绝内容。
4. 独立审查 diff 后再执行 commit、push、PR、merge、版本升级和部署；这些仍是独立动作。
5. 发布后重启 MCP，确认 capabilities v6 和两个 Reflect 工具在 full profile 可见。

## 暂不加入

- 不引入 Neo4j、另一套向量数据库或新的 Memory 主模型。
- 不让服务端低能力模型替代客户端 AI 做强制归纳。
- 不根据“长期未访问”自动判断记忆过时。
- 不自动 apply Sleep、constraint revalidation、Reflect 或 Context Policy enforce。
