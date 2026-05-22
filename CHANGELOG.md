# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。

## [0.1.0] - 2025-05-22

### 新增

- **Hub**: FastAPI 后端，完整 CRUD + 语义搜索（pgvector + BGE-M3）
- **多用户系统**: GitHub OAuth 登录、JWT 认证、数据隔离
- **CLI**: `echome` 命令行工具（login, add, list, search, sync, review, market）
- **MCP Server**: 向 AI CLI 暴露记忆查询/写入能力
- **Web Console**: Vue.js 管理界面（Dashboard, Memories, Review, Projects, Market, Admin, Settings）
- **Embedding 服务**: 自托管 BGE-M3 模型（ModelScope + GPU）
- **三层注入策略**: L0（全局必载）/ L1（项目级）/ L2（按需搜索）
- **Market**: 公开记忆广场，支持 fork
- **Admin**: 系统统计、用户管理、内容审核

### 安全

- JWT Secret 启动检查（生产环境强制配置）
- Emergency auth token（GitHub 不可用时的紧急登录）
- CORS 来源可配置
- 数据库/Redis 不暴露外部端口
- CLI 配置文件 chmod 600

### 已知限制

- 暂无自动化测试覆盖
- Token 无法吊销（10 年有效期）
- 无 Rate Limiting
