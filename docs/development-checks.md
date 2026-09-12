# 开发验证与文档契约

## 常规检查

在仓库根目录执行：

```bash
uv run python scripts/check_project_truth.py
uv run python scripts/check_doc_contracts.py --surface client
uv run pytest
```

在 `hub/` 执行 `uv run python ../scripts/check_doc_contracts.py --surface hub` 和 `uv run pytest`。文档检查只导入 schema、解析参数，不执行 CLI 命令、连接 Hub 或修改用户配置。

客户端检查当前指南的 JSON、CLI 命令/参数、MCP schema 和相对链接；Hub 检查 API 路由及标注为 Request Body 的 JSON，并用实际 Pydantic 模型验证。MCP 调用示例可在 JSON fence 前添加 `<!-- echome-contract: mcp echome_context -->`，让工具参数参与校验。文档里的 enum/required 必须与实际定义一致，未列出的可选 schema 细节允许省略。

当前文档范围显式维护在 [check_doc_contracts.py](../scripts/check_doc_contracts.py) 的 `CURRENT_DOCS`。`discuss.md`、历史版本计划和历史讨论快照不按当前接口强制改写；新增当前指南时应加入检查范围。已有版本/schema/capabilities 真相门禁继续保留。

## 隔离数据库回归

默认单元测试不要求数据库；`tests/integration/` 在缺少 `ECHOME_INTEGRATION_DATABASE_URL` 时明确跳过。设置变量后会在名字以 `echome_test` 开头的专用数据库中为每个用例创建随机 schema，结束后只删除该 schema。不要使用生产数据库。

```bash
ECHOME_INTEGRATION_DATABASE_URL=postgresql+asyncpg://echome_test@127.0.0.1:5432/echome_test uv run pytest tests/integration -q
```

CI 使用临时 pgvector/PostgreSQL 16，先执行 Alembic upgrade，再运行集成测试。覆盖真实 JWT、REST、SQL、canonical/alias 范围、排除规则、生命周期、context 路由和输出预算、feedback/outcome 幂等、embedding 乱序完成。embedding 是受控边界，无外部模型调用。原有 31 条 Project Context Quality Eval 保留；本轮新增的是独立的数据库和客户端回归，不把它们当作生产语料质量评分。门禁通过不会自动开启 policy enforce 或 Sleep apply。

构建 job 将 wheel 安装到新环境后，执行 [MCP stdio smoke](../scripts/smoke_mcp_stdio.py) 的 CLI/module × core/full 四组握手。DSH 是可选本地兼容性检查，步骤见 [DSH 接入](dsh-integration.md)。
