# EchoMe 记忆检索设计

## 目标

EchoMe 的记忆会持续增长，尤其是项目级记忆、历史决策和工作流规则。检索设计的目标不是“返回尽可能多的全文”，而是让 AI 能稳定找到相关记忆，并只把当前任务需要的内容加载进上下文。

## 问题

早期实现主要依赖 `echome_search(query, top_k)` 直接返回少量全文结果。这个方式在记忆较少时足够，但记忆变多后会出现几个问题：

- `top_k` 太小会漏掉后写入的具体记忆。
- `top_k` 太大或返回全部全文会让上下文变乱，降低回答质量。
- 泛化规则、早期高相似度记忆容易长期占据结果位。
- AI 很难知道“还有哪些候选记忆没有被返回”。

## 方案：summary-first

EchoMe 采用 **summary-first** 工作流：先返回记忆摘要索引，再按 UUID 精读全文。

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

AI 的默认策略是：先检索，再精读；当记忆涉及项目决策、历史方案、可能过时的环境/版本/部署信息，或多条记忆存在整理关系时，再调用记忆图工具做稳定性检查。


## 触发策略

EchoMe 不要求 AI 在同一会话的每一轮都查询记忆，而是采用 **首轮启动 + 后续按需触发**：

- **首轮启动**：第一次收到任务时，AI 先调用 `echome_search_summary` 查询相关的个人习惯、开发规范、技术偏好、项目规范和历史决策。
- **规范确认**：如果找到相关规范，AI 只精读必要条目，并用 1-3 句复述本次会遵守的关键规范。
- **后续按需**：后续只有在任务涉及偏好、规范、历史决策、项目约定、高风险改动或用户说“按老规矩/继续/记住/以后/永远/always”时再查。
- **无命中即停止**：如果摘要没有相关项，AI 不应盲目扩大搜索。

这个策略避免了“每轮都查”的噪音，同时保留首轮加载规范和后续主动触发的能力。

## MCP 工具分工

| Tool | 用途 |
|---|---|
| `echome_capabilities` | 返回 EchoMe MCP 能力目录、工具分组、推荐工作流；AI 不确定怎么用 EchoMe 时先调用 |
| `echome_search_summary` | 返回紧凑候选索引：编号、UUID、标题、类型、标签、更新时间和简短摘要 |
| `echome_get_memories` | 按 UUID 批量读取选中记忆全文 |
| `echome_search` | 保留给明确、小范围的语义搜索 |
| `echome_get` | 单条记忆精读，兼容旧用法 |
| `echome_memory_explain` | 解释单条记忆的来源、替代关系、相邻记忆和 temporal assessment |
| `echome_memory_neighbors` | 返回围绕单条记忆的局部图，供 AI 扩展项目上下文 |
| `echome_temporal_candidates` | 只读列出可能需要复核的时间敏感记忆 |
| `echome_memory_feedback` | 记录单条记忆的有效性反馈，不自动修改记忆状态 |
| `echome_memory_feedback_batch` | 任务结束时批量记录多条记忆的有效性反馈 |

## 能力发现

EchoMe 不假设用户或 AI 记得工具名。MCP server 同时提供三种发现入口：

- Tool：`echome_capabilities`，适合所有支持 tools 的客户端，返回 JSON 能力目录。
- Prompt：`echome_retrieval_workflow`，适合支持 MCP prompts 的客户端，返回标准检索工作流提示。
- Resource：`echome://capabilities`，适合支持 MCP resources 的客户端，返回同一份能力目录。

如果客户端只支持 tools，默认让 AI 先调用 `echome_capabilities`；如果客户端支持 prompts/resources，可以把 `echome_retrieval_workflow` 或 `echome://capabilities` 作为系统级上下文注入。

## 检索调试与日志

Hub 记录检索调试日志，用于排查“AI 为什么找到/没找到某条记忆”：

- MCP `echome_search_summary` 会记录 query、轻量检索命中数、semantic fallback 是否触发、Top 结果和中间步骤。
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

- 宽泛问题、项目规范、历史决策、用户偏好：优先调用 `echome_search_summary`。
- 只对相关摘要条目调用 `echome_get_memories`。
- 如果摘要里没有相关记忆，不要为了凑结果盲目扩大搜索。
- 非常明确的小范围问题可以直接调用 `echome_search`。
- 使用一条关键记忆做项目判断前，优先调用 `echome_memory_explain` 检查是否稳定、是否 time-sensitive、是否被整理/替代。
- 当用户纠正记忆、AI 明确依赖了某条记忆，或任务结束时能判断记忆是否有用/过时/冲突，调用 `echome_memory_feedback` 记录信号；不要每轮都打扰用户。

## 当前状态

- 已实现 `echome_capabilities`、`echome_retrieval_workflow` prompt 和 `echome://capabilities` resource。
- 已实现 `echome_search_summary`。
- 已实现 `echome_get_memories`。
- 已实现 `echome_memory_explain`、`echome_memory_neighbors`、`echome_temporal_candidates`。
- 已实现 `echome_memory_feedback`、`echome_memory_feedback_batch` 和 Web 观测页反馈按钮。
- 已实现 retrieval logs 和 Web `/logs` 检索调试器。
- 已将渲染到 AGENTS/CLAUDE 的 MCP 指令切换为 summary-first。
- Hub 列表接口支持 `query` 轻量过滤，用于摘要索引。
