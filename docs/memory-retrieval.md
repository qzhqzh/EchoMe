# EchoMe 记忆检索设计

> 按 2026-10-22 当前源码校准。需要历史上下文时使用 `echome_context`；无需每次对话调用。summary-first 是 full profile 中的专业浏览流程。工具可用性以实际 capabilities 和 `tools/list` 为准。

## 目标

EchoMe 的记忆会持续增长，尤其是项目级记忆、历史决策和工作流规则。检索设计的目标不是“返回尽可能多的全文”，而是让 AI 能稳定找到相关记忆，并只把当前任务需要的内容加载进上下文。

## 问题

早期实现主要依赖 `echome_search(query, top_k)` 直接返回少量全文结果。这个方式在记忆较少时足够，但记忆变多后会出现几个问题：

- `top_k` 太小会漏掉后写入的具体记忆。
- `top_k` 太大或返回全部全文会让上下文变乱，降低回答质量。
- 泛化规则、早期高相似度记忆容易长期占据结果位。
- AI 很难知道“还有哪些候选记忆没有被返回”。

## 默认方案：按任务获取上下文

新安装默认使用 core profile：

```text
首次使用或不确定工具
  -> echome_capabilities
任务缺少会影响判断的历史信息，或用户明确要求回忆
  -> echome_context(task, project_hint, changed_paths)
  -> 查看 evidence / conflicts / unknowns / answerability
  -> 必要时 echome_memory_explain(memory_id)
有明确帮助或纠正的证据（可选）
  -> echome_memory_feedback 或 echome_context_outcome
无明确信号
  -> 直接继续工作，不需要 no_signal 收尾
```

`echome_context` 根据任务及项目线索选择 personal、project、impact 或 temporal 路径。auto 模式未解析项目时降级为全局个人记忆；显式项目模式仍返回身份恢复结果。没有相关记忆时不为凑结果扩大查询。未知项目不触发自动登记，也不要求用户先确认记忆；先按当前代码、配置与对话证据继续。只有用户要求项目登记/身份维护，或者项目专属写入确实需要确定归属时，才处理身份问题。

默认入口同时发现最多 4 条相关知识库/场景引用，给出简短摘要和展开参数，不注入整份知识树。引用只表示可能相关，展开后再核验；compact 下优先保留强约束，再按剩余空间返回引用。引用检索失败不阻断已有个人/项目上下文。历史查询不混入当前知识引用。

Memory search 与 personal context 使用共享的有界向量 + 词法召回，embedding 不可用时可降级为词法。项目 Context Compiler 还组合制品、约束、事件、派生视图以及图/时间证据；两者不能用同一个简单评分公式解释。详细参数和静态渲染区别见 [记忆模型](memory-model.md)。

## full profile：summary-first

需要浏览较多候选、手动选择精读条目时，显式启用 full profile，再使用 **summary-first**：先返回记忆摘要索引，再按 UUID 精读全文。该流程不要求默认 core 客户端调用未暴露的工具。

```text
AI 需要上下文
  -> echome_search_summary(query/project/type)
  -> 读取候选摘要索引
  -> 选择相关 UUID
  -> echome_get_memories(memory_ids=[...])
  -> 必要时 echome_memory_explain(memory_id)
  -> 只加载选中的全文
```

## 记忆图增强

普通检索回答“哪些记忆可能相关”，记忆图查询回答“这条记忆是否可靠、从哪里来、替代了什么、旁边还有什么”。它们不是替代关系：

- `echome_search_summary` / `echome_search`：发现候选记忆。
- `echome_get_memories` / `echome_get`：读取候选全文。
- `echome_memory_explain`：在使用某条记忆前检查来源、替代关系、相邻记忆和 temporal assessment。
- `echome_memory_neighbors`：围绕某条记忆展开局部图，适合构造稳定的项目上下文。
- `echome_temporal_candidates`：列出可能需要复核的记忆，不修改状态；长期未访问不会被单独视为过时，搁置项目会单独归类。
- `echome_memory_feedback` / `echome_memory_feedback_batch`：在记忆被使用后记录有效性信号，不直接修改记忆状态。

AI 先判断当前证据是否足够；缺少相关历史时再获取任务上下文并按需精读。当关键记忆可能过时、发生冲突或存在替代关系时，再调用记忆图工具做稳定性检查。当前用户指令与已验证的当前事实优先于历史记忆。


## 触发策略

EchoMe 在首轮和后续轮次都采用 **按需触发、已有上下文复用**：

- **需要才查**：用户要求找回历史，或缺少的偏好、既往决策、项目约定会改变当前判断时，调用 `echome_context`，传入已知项目线索。首次使用或不清楚工具时再读 `echome_capabilities`。
- **已有则复用**：当前对话已经有足够上下文时，继续使用；新信息缺口、冲突或时效疑点出现时才重新查。通用问答、信息齐全的独立修改不需要查询。
- **直接应用**：只精读相关条目；无需例行复述规范、让用户确认记忆或在每次编辑/测试前 preflight。影响方案、发现冲突或需要澄清时才说明。
- **无命中即停止**：没有相关记忆、项目未知或工具不可用时按当前证据继续，不盲目扩大搜索、不静默创建项目。full profile 的摘要浏览同样遵循此规则。
- **有证据再反馈**：确认记忆产生帮助、需要纠正或与当前事实冲突时可反馈；不能判断就不报，缺失反馈不代表失败。保留 `no_signal` 兼容能力，但不要求任务结束时例行提交。

这些是 Agent 的使用策略；服务不会监听每轮聊天，也不要求用户管理查询流程。`echome gate` 可用规则或可选小模型做影子判断，但不是每轮必经检查，也不会自行读取或写入记忆。

## MCP 工具分工

| Tool | 用途 |
|---|---|
| `echome_capabilities` | 返回 EchoMe MCP 能力目录、工具分组、推荐工作流；AI 不确定怎么用 EchoMe 时先调用 |
| `echome_context` | 缺少相关历史时的查询入口，自动选择个人/项目上下文路径 |
| `echome_runtime_health` | 检查运行中的版本、schema、依赖与 profile |
| `echome_context_outcome` | 有明确信号时，可选为 Context Run 追加幂等结果 |
| `echome_search_summary` | 返回紧凑候选索引：编号、UUID、标题、类型、标签、更新时间和简短摘要 |
| `echome_get_memories` | 按 UUID 批量读取选中记忆全文 |
| `echome_search` | 保留给明确、小范围的语义搜索 |
| `echome_get` | 单条记忆精读，兼容旧用法 |
| `echome_memory_explain` | 解释单条记忆的来源、替代关系、相邻记忆和 temporal assessment |
| `echome_memory_neighbors` | 返回围绕单条记忆的局部图，供 AI 扩展项目上下文 |
| `echome_temporal_candidates` | 只读列出可能需要复核的时间敏感记忆 |
| `echome_memory_feedback` | 记录单条记忆的有效性反馈，不自动修改记忆状态 |
| `echome_memory_feedback_batch` | 任务结束时批量记录多条记忆的有效性反馈 |

表中的摘要、精读、邻居、时态候选和批量反馈等专业工具需要 full profile；core 的准确列表见 [MCP 规范](mcp-spec.md)。摘要与按类型工具默认显式筛选 active；Memory search 与 context 默认有效集合包含 active + ai_review。

## 能力发现

EchoMe 不假设用户或 AI 记得工具名。MCP server 同时提供三种发现入口：

- Tool：`echome_capabilities`，适合所有支持 tools 的客户端，返回 JSON 能力目录。
- Prompt：`echome_retrieval_workflow`，适合支持 MCP prompts 的客户端，返回标准检索工作流提示。
- Resource：`echome://capabilities`，适合支持 MCP resources 的客户端，返回同一份能力目录。

如果客户端只支持 tools，默认让 AI 先调用 `echome_capabilities`；如果客户端支持 prompts/resources，可以把 `echome_retrieval_workflow` 或 `echome://capabilities` 作为系统级上下文注入。

## 检索调试与日志

Hub 记录检索调试日志，用于排查“AI 为什么找到/没找到某条记忆”：

- `echome_context` 可记录 Context Run，并返回按需提交的 completion contract；outcome 与 policy effect 保留为可追溯结果信号。
- full profile 的 `echome_search_summary` 会记录 query、轻量检索命中数、semantic fallback 是否触发、Top 结果和中间步骤。
- Web `/logs` 提供“记忆检索调试器”，可以输入 query、期望 memory id，查看 expected rank、Top 结果和 retrieval steps。
- Web `/eval` 用固定样例做快速回归；`/logs` 更适合临时排查真实查询。

这套日志是观测信号，不会自动改变记忆状态。若用户确认某条记忆有用/过时/冲突，再通过 feedback 机制记录有效性信号。

## 为什么不用数字编号直接取记忆

摘要结果会显示编号，方便人和 AI 讨论“第 1、2、5 条”。但 MCP 工具调用本身是无状态的，服务端不知道下一次调用里的 `1,2,5` 对应哪一次摘要结果。

因此工具层只接受 UUID：

1. `echome_search_summary` 输出编号和 UUID。
2. AI 根据编号选择相关条目。
3. AI 调用 `echome_get_memories` 时传对应 UUID。

这样避免引入 summary session、缓存过期、跨会话串页等状态复杂度。

## 使用规则

- 缺少的项目规范、历史决策或用户偏好会影响当前任务时，调用 `echome_context`；已有上下文足够时复用。
- full profile 中需要浏览更多候选时，再调用 `echome_search_summary`。
- 只对相关摘要条目调用 `echome_get_memories`。
- 如果摘要里没有相关记忆，不要为了凑结果盲目扩大搜索。
- full profile 中非常明确的小范围问题可以直接调用 `echome_search`。
- 使用一条关键记忆做项目判断前，优先调用 `echome_memory_explain` 检查是否稳定、是否 time-sensitive、是否被整理/替代。
- 当用户纠正记忆、AI 明确依赖了某条记忆，或任务结束时能判断记忆是否有用/过时/冲突，调用 `echome_memory_feedback` 记录信号；不要每轮都打扰用户。

## 当前状态

- 已实现 `echome_capabilities`、`echome_retrieval_workflow` prompt 和 `echome://capabilities` resource。
- 已实现 `echome_search_summary`。
- 已实现 `echome_get_memories`。
- 已实现 `echome_memory_explain`、`echome_memory_neighbors`、`echome_temporal_candidates`。
- 已实现 `echome_memory_feedback`、`echome_memory_feedback_batch` 和 Web 观测页反馈按钮。
- 已实现 retrieval logs 和 Web `/logs` 检索调试器。
- 已将渲染到 AGENTS/CLAUDE 的 MCP 默认指令切换为 capability discovery + `echome_context`，保留 full profile 的 summary-first。
- 已实现 Context Run、Context Outcome、runtime health 和相同请求键的加密只读缓存降级；缓存不是本地 vault 同步。
- Hub 列表接口支持 `query` 轻量过滤，用于摘要索引。
