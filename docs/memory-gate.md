# Memory Gate：读取与写入建议试点

## 当前实现

`echome gate decide` 是独立的 shadow 判断入口，支持本地规则、Kev、Laya。
它只返回建议，不检索 Hub、不创建记忆、不执行建议，也没有安装任何客户端自动 Hook。
因此，仅部署判断服务或运行此命令，并不会提高客户端的 EchoMe 调用覆盖率。

这个 Gate 判断“当前任务是否需要交互”；Hub 的 Context Policy 判断“检索出的内容是否适合提供”。两者各自保留，不互相替代。

## 输入与输出

通过标准输入或 `--input request.json` 提供 JSON：

```json
{
  "schema_version": "echome.memory-gate.v1",
  "phase": "read",
  "text": "给记忆服务设计一个兼容当前部署的接入方案。",
  "project_hint": "EchoMe",
  "context_available": false,
  "explicit_action": "auto"
}
```

- `phase`：`read` 或 `write`。输入应为短任务描述或待评估的用户陈述，不能把整个对话或记忆库塞进去。正文最多 4,000 字符，JSON 输入最多 64 KiB；服务还有独立 token 限制，过长会降级。
- `explicit_action`：`auto`、`read`、`remember`、`skip`；`read` 只用于读取阶段，`remember` 只用于写入阶段。显式意图优先于模型，但不能绕过敏感信息拦截。
- `context_available`：调用方确认已有适用上下文时才设为 true。Gate 不验证缓存、项目身份或时效；历史信息有变化时调用方必须失效缓存。明确恢复历史的请求仍可要求检索。
- `project_hint`：可选的短项目标识，同样接受敏感信息检查。

读取建议为 `retrieve`（检索）、`reuse`（复用）或 `skip`；写入建议为 `propose`（生成待审提案）、`review`（意图不清需复核）或 `skip`。`propose` 不代表可直接写入。

回执包含 `decision_id`、`phase`、`action`、`provider`、`reason_code`、`model_action`、`model_probability`、`latency_ms`、`degraded` 和固定的 `shadow: true`。`provider` 是实际决策来源，规则命中时为 `rules`。模型低概率回退仍保留原始 `model_action`，便于区分模型效果和兜底效果。概率尚未校准，不能理解为正确率。

## 使用

```bash
# 只用规则，完全不需要判断服务
echome gate decide --input request.json

# 在调用进程环境中设置 ECHOME_GATE_API_KEY，不把密钥放进命令参数或仓库
echome gate decide --input request.json \
  --provider kev --base-url http://127.0.0.1:18641 \
  --audit ~/.echome/gate/events.jsonl --event-id task-123

echome gate decide --input request.json \
  --provider laya --base-url http://127.0.0.1:18642
```

服务使用 `POST /v1/systemone`，也支持以 `/v1` 结尾的 base URL。`--model` 可覆盖默认模型 ID；这不是聊天补全接口。没有读取 Hub token 或自动发现其他服务凭据的逻辑，`--api-key-env` 可指定独立环境变量名。

默认阈值 0.8、总超时 2 秒；概率低、429/503、超时、非法标签或分布等均回退为读取 `retrieve` / 写入 `review`。不重试，不跟随重定向，不使用 HTTP 代理环境变量。HTTP 仅接受 localhost、loopback 或私网 IP，其他显式配置的服务需 HTTPS。

正文与项目提示中常见密钥、密码赋值、私钥、Bearer、`sshpass -p` 等会在模型请求前被拦截；这是常见凭据检测，并非完整数据脱敏。调用方仍应限制输入为必要的任务摘要。

可选审计只记录决策元数据，不记录任务正文、项目提示、访问密钥或服务错误正文。文件必须属于当前用户、权限 600 且为普通文件，拒绝符号链接。`event-id` 用于关联调用方任务，不提供去重保证；不要用正文或凭据充当 ID。

## 评测与选型

源码仓库包含 60 条合成中文用例（读取/写入各 30），其中 48 条为语义判断、12 条为显式控制和安全边界。它们不是实际用户对话，不代表生产流量分布；开发者自标注的 `dev` / `holdout` 分组也不等于独立盲测。

```bash
# 设置 ECHOME_GATE_KEV_API_KEY 和 ECHOME_GATE_LAYA_API_KEY 后执行
uv run python scripts/eval_memory_gate.py \
  --provider rules --provider kev --provider laya \
  --output /tmp/memory-gate-eval.json

# 只比较原始模型，检查选项位置敏感性
uv run python scripts/eval_memory_gate.py \
  --provider kev --provider laya --mode model --reverse-options \
  --output /tmp/memory-gate-reversed.json
```

脚本串行交错请求两个模型，避免并发冲击。`model` 模式绕过业务规则和概率阈值，仅对非敏感合成语义用例测原始分类；`gate` 模式测试完整判断链，包括兜底。报告分别统计读取漏判、误建议写入、有效模型预测数、错误、降级和延迟；报告保留用例 ID、文件哈希和单请求提示哈希，不包含原文或密钥。超时/接口错误计入总样本分母，不会虚增准确率。

实测报告见 [Kev / Laya 中文对比](memory-gate-evaluation.md)。第一版只观察建议，模型选型不能绕过上线验收。

## 推进顺序

| 优先级 | 工作 | 可验收结果 |
|---|---|---|
| P0 | 修复 context 交付预算 | 长记忆不会挤掉所有短记忆；完整硬约束保留；正文和索引分开计量 |
| P0 | 统一 Gate 与合成评测 | 同一协议比较规则/Kev/Laya；无记忆读写副作用；错误可追踪 |
| P1 | 一个客户端任务入口的 shadow adapter | 每个顶层任务有事件 ID，统计任务总量→Gate建议→context尝试→有效正文→实际使用；子任务去重 |
| P1 | 真实任务人工标注与校准 | 取得调用覆盖率、漏读/误提案、额外延迟，比较规则基线与模型；用新的留出集复核 |
| P2 | 小范围自动读取 | 保留显式读取与故障兜底；按项目/任务身份复用缓存；可一键退回规则 |
| P2 | 独立记忆提案箱 | 去重、关联来源、旧事实更正、反馈分流、敏感检查；审核后才入库 |
| P3 | 有条件的受控写入 | 按验收结果逐类开放，保留可撤销记录与审计 |

客户端入口必须通过其实际支持的 Hook 或外层启动器接入；只在 Hub 或 MCP 内增加模型，无法发现客户端从未发起的任务。后续 adapter 还需与调用方权限、项目身份解析和缓存契约结合，当前没有声称这些工作已完成。

当前 `ai_review` 记忆已经可以参与检索，不能拿它当隔离的提案箱；shadow 输出不得自动转换为 `echome_remember`。现有来源、审核、Sleep 保护规则继续适用。

## Context 预算交付变化

compact 输出先压缩重复的策略诊断，再按原相关性顺序尝试放入完整记录；放不下的大记录不会阻挡后面的短记录。constraints、guardrail、L0、must_include、冲突与完成契约仍完整保留，保护内容本身超限会返回 `OUTPUT_BUDGET_TOO_SMALL`。

当没有可交付的可选记忆正文时，尽量提供 `memory_index`，仅包含 ID、标题和 `needs_expansion: true`（必要时含策略干预标记）；按 `GET /api/v1/memories/{id}` 展开后才能使用。索引不是摘要，更不代表已获取完整规则，只有索引不能声称 `supported`。

`token_used` 保留编译预算含义；新增 `compiled_content_tokens`、`delivered_content_tokens`、`memory_index_tokens` 分开描述编译正文、交付正文和引用索引的估算。最终 JSON 硬上限仍以保守的 UTF-8 字节测量，不把这些估算混作实际模型 tokenizer 计费。ContextRun 的 `selected` 只计完整交付条目，索引 ID 单列到 trace；full 保留详细诊断。
