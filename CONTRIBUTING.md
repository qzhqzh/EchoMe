# 贡献指南

感谢你对 EchoMe 的关注！欢迎贡献代码、文档、Bug 报告或功能建议。

## 开发环境搭建

### 前置要求

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- uv (推荐) 或 pip

### 本地开发

```bash
# 1. Clone 仓库
git clone https://github.com/qzhqzh/EchoMe.git
cd EchoMe

# 2. 安装 CLI（开发模式）
pip install -e ".[mcp,dev]"

# 3. 启动 Hub + 数据库
cp hub/.env.example hub/.env
# 编辑 hub/.env，设置 JWT_SECRET 和 GitHub OAuth
docker compose up -d

# 4. 前端开发
cd web
npm install
npm run dev
```

### 代码规范

- Python: 使用 ruff 进行 lint，line-length = 100
- TypeScript: 使用 vue-tsc 类型检查
- Commit 消息格式: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`

```bash
# 检查代码
ruff check echome/ echome_mcp/ hub/app/

# 类型检查
cd web && npx vue-tsc --noEmit
```

## 提交 PR

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feat/amazing-feature`)
3. 提交更改 (`git commit -m 'feat: add amazing feature'`)
4. 推送到分支 (`git push origin feat/amazing-feature`)
5. 开一个 Pull Request

### PR 要求

- 描述清楚改动内容和动机
- 确保通过 lint 检查
- 如果改动了 API，更新 `docs/api-spec.md`
- 如果新增配置项，更新 `.env.example`

## 项目结构

```
EchoMe/
├── echome/          # CLI 工具 (typer + rich)
├── echome_mcp/      # MCP Server
├── hub/             # FastAPI 后端
│   ├── app/api/     # API 路由
│   ├── app/core/    # 配置、认证、数据库
│   ├── app/models/  # SQLAlchemy 模型
│   ├── app/schemas/ # Pydantic 模式
│   └── app/services/# 业务逻辑
├── web/             # Vue.js 前端
├── embedding/       # BGE-M3 嵌入服务
└── docs/            # 文档
```

## 报告 Bug

请在 [GitHub Issues](https://github.com/qzhqzh/EchoMe/issues) 提交，包含：

- 操作系统和 Python 版本
- 复现步骤
- 预期行为 vs 实际行为
- 错误日志（如有）

## 联系

如有问题，欢迎在 Issues 中讨论。
