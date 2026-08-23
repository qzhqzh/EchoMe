# EchoMe 数据生命周期

## 分类

| 类别 | 典型数据 | 默认策略 |
|---|---|---|
| 权威知识 | memories、artifacts、constraints、events、relations | 不自动删除，使用状态与版本演进 |
| 变更证据 | Sleep sessions、feedback、context outcomes、quality snapshots | append-only，保留来源和幂等键 |
| 运行遥测 | retrieval logs、context runs | 只存诊断所需元数据，后续可按保留期清理 |
| 本地降级缓存 | MCP context cache | AES-256-GCM 加密，按 TTL 失效，只读使用 |

## 当前行为

- 系统没有自动清理数据库记录的后台任务。
- Retrieval Logs 新写入时会移除结果中的 `content`，只保留 ID、标题、状态、分数、匹配原因和 trace。
- 已存在的历史日志不会在升级时被静默重写或删除。
- `archived`、`deprecated` 是记忆生命周期状态，不等于可清理的遥测。
- `data/postgres`、Alembic migration 和生产回填不属于日志清理范围。

## 建议保留策略

以下是后续自动化的目标值，当前版本尚未自动执行：

| 数据 | 建议在线保留 | 到期动作 |
|---|---:|---|
| Retrieval Logs | 30 天 | 先聚合指标，再删除原始 telemetry |
| 成功 Context Runs | 90 天 | 保留聚合质量指标和明确 outcome |
| 失败 Context Runs | 180 天 | 保留错误码、版本和 request ID，不保留上下文正文副本 |
| Feedback / Outcomes | 长期 | append-only；通过关联数据解释排序效果 |

## 自动清理上线门槛

1. 默认必须是 dry-run，并输出候选数量、最早/最晚时间和分类。
2. apply 必须使用显式开关和独立事务，只允许删除 telemetry 表。
3. 运行前备份，运行后校验权威表行数和 Alembic revision 未变化。
4. 不级联删除 memory、project、artifact、constraint、event 或 graph edge。
5. 首次生产执行需要人工审核 dry-run 回执；定期任务需在多轮稳定后单独启用。
