# EchoMe 多用户系统技术方案

> 本文档是多用户功能的接力开发文档，供新会话的 AI 或开发者阅读后直接开始实现。

---

## 1. 目标

将 EchoMe 从单租户（单一 Bearer Token）升级为多用户系统，支持：
- GitHub OAuth 登录
- 用户数据隔离
- 公开记忆市场 + Fork 机制

## 2. 当前状态

- Hub 运行在 port 20000（FastAPI + PostgreSQL + pgvector）
- Web Console 运行在 port 20001（Vue 3）
- CLI 命令 `echome`（别名 `eme`）可用
- MCP Server 已注册到 Claude Code
- 认证方式：单一 Bearer Token（`ECHOME_AUTH_TOKEN` in .env）
- memories 表有 `user_id` 字段（当前写死为 "default"）

## 3. 技术方案

### 3.1 认证流程：仅 GitHub OAuth

```
用户点击"Login with GitHub"
  → 前端跳转 GitHub 授权页
  → 用户授权
  → GitHub 回调到 Hub: /api/v1/auth/github/callback?code=xxx
  → Hub 用 code 换取 access_token
  → Hub 用 access_token 获取 GitHub 用户信息（id, login, email, avatar）
  → Hub 在 users 表创建/更新用户
  → Hub 签发 JWT Token 返回给前端
  → 前端存 JWT 到 localStorage
```

**GitHub OAuth App 配置**：
- Client ID: 从 `ECHOME_GITHUB_CLIENT_ID` 环境变量读取
- Client Secret: 从 `ECHOME_GITHUB_CLIENT_SECRET` 环境变量读取
- Callback URL: `http://<host>:20000/api/v1/auth/github/callback`

### 3.2 数据库变更

```sql
-- 新增 users 表
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    github_id       BIGINT UNIQUE NOT NULL,
    username        VARCHAR(64) UNIQUE NOT NULL,
    email           VARCHAR(256),
    avatar_url      VARCHAR(512),
    role            VARCHAR(16) NOT NULL DEFAULT 'user',  -- user/admin
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);

-- memories 表新增字段
ALTER TABLE memories ADD COLUMN visibility VARCHAR(16) NOT NULL DEFAULT 'private';
-- visibility: 'private' (默认，只有自己看到) / 'public' (所有人可搜索和 fork)

ALTER TABLE memories ADD COLUMN forked_from UUID REFERENCES memories(id) ON DELETE SET NULL;
-- 如果是从公开记忆 fork 的，记录原始来源
```

### 3.3 JWT Token

- 签发：Hub 在 GitHub OAuth 成功后签发
- 载荷：`{"sub": user_id, "username": "xxx", "role": "user", "exp": ...}`
- 有效期：7 天（可配置）
- 签名算法：HS256
- 密钥：`ECHOME_JWT_SECRET` 环境变量

### 3.4 向后兼容

- 旧的单一 Bearer Token（`ECHOME_AUTH_TOKEN`）继续有效
- 如果请求带的是旧 Token，映射到第一个 admin 用户
- 这样 CLI 用户不需要立即更改配置

### 3.5 权限矩阵

| 操作 | 未登录 | 普通用户 | Admin |
|---|---|---|---|
| 浏览公开记忆 | ✅ | ✅ | ✅ |
| Fork 公开记忆 | ❌ | ✅ | ✅ |
| 管理自己的记忆 | ❌ | ✅ | ✅ |
| 设置记忆为 public | ❌ | ✅ | ✅ |
| 查看所有用户 | ❌ | ❌ | ✅ |
| 删除任何记忆 | ❌ | ❌ | ✅ |

### 3.6 第一个用户 = Admin

第一个通过 GitHub OAuth 登录的用户自动设置为 `role = 'admin'`。

## 4. API 设计

### 4.1 Auth API

```
GET  /api/v1/auth/github          → 返回 GitHub OAuth 授权 URL
GET  /api/v1/auth/github/callback → 处理回调，返回 JWT
GET  /api/v1/auth/me              → 返回当前用户信息
POST /api/v1/auth/refresh         → 刷新 JWT
```

### 4.2 Market API（公开记忆市场）

```
GET  /api/v1/market/memories                → 浏览公开记忆（分页、搜索）
GET  /api/v1/market/memories/{id}           → 查看公开记忆详情
POST /api/v1/market/memories/{id}/fork      → 复制到自己的记忆库
GET  /api/v1/market/stats                   → 市场统计（公开记忆数、热门类型）
```

### 4.3 修改现有 API

- 所有 `/api/v1/memories` 接口：从 JWT 中提取 user_id，自动过滤
- `POST /api/v1/memories`：新增可选 `visibility` 字段（默认 private）
- `PATCH /api/v1/memories/{id}`：允许修改 visibility

## 5. CLI 变更

### 新增命令

```bash
echome login          # 打开浏览器完成 GitHub OAuth，获取 JWT 存到 ~/.echome/config.yaml
echome logout         # 清除本地 JWT
echome whoami         # 显示当前登录用户
echome market         # 浏览公开记忆市场
echome market search "关键词"   # 搜索公开记忆
echome market fork <id>         # Fork 一条公开记忆到自己的库
echome publish <id>             # 设置自己的记忆为 public
echome unpublish <id>           # 设为 private
```

### login 流程

```
1. CLI 启动本地 HTTP 服务（临时，用于接收回调）
2. 打开浏览器 → Hub 的 /auth/github → GitHub 授权
3. GitHub 回调到 Hub → Hub 签发 JWT
4. Hub 重定向到 CLI 的本地 HTTP 回调（带 JWT）
5. CLI 保存 JWT 到 ~/.echome/config.yaml
6. 关闭本地 HTTP 服务
```

或更简单：
```
1. CLI 打开浏览器到 Hub /auth/github
2. 用户授权后，Hub 页面显示一个 Token
3. 用户手动复制 Token 粘贴到 CLI
```

## 6. Web 前端变更

### 新增页面

| 页面 | 功能 |
|---|---|
| `/login` | GitHub OAuth 登录按钮 |
| `/market` | 公开记忆市场（搜索 + 浏览 + Fork） |
| `/settings` | 个人设置 |

### 现有页面改动

- 顶部导航：显示用户头像 + 用户名
- 记忆列表：显示 visibility 标签（🔒 / 🌐）
- 记忆编辑：添加"设为公开"开关

## 7. 迁移策略

1. 部署新版 Hub（带 users 表 + JWT）
2. 旧 Bearer Token 继续有效（映射到 admin）
3. 第一个 GitHub 登录的用户成为 admin
4. admin 的 user_id 替换旧的 "default"
5. 所有现有记忆自动归属 admin

## 8. 环境变量新增

```env
# GitHub OAuth
ECHOME_GITHUB_CLIENT_ID=Ov23liDr8JFeX8Rl5ZqV
ECHOME_GITHUB_CLIENT_SECRET=<重新生成的 Secret>

# JWT
ECHOME_JWT_SECRET=<随机字符串，至少32位>
ECHOME_JWT_EXPIRE_DAYS=7

# 旧的 token 继续保留用于兼容
ECHOME_AUTH_TOKEN=<现有 token>
```

## 9. 不做的事

- ❌ 邮箱注册/登录
- ❌ Google OAuth
- ❌ 团队/组织功能
- ❌ 记忆评分/点赞
- ❌ 付费功能

## 10. 开发顺序

```
Phase 1: users 表 + JWT + GitHub OAuth API（后端）
Phase 2: 修改现有 API 支持多用户（数据隔离）
Phase 3: visibility 字段 + market API
Phase 4: CLI login/market 命令
Phase 5: Web 前端登录页 + 市场页
Phase 6: 迁移脚本（现有数据归属 admin）
```

## 11. 文件改动清单

```
hub/
├── app/
│   ├── api/
│   │   ├── auth.py          # 新增：GitHub OAuth + JWT
│   │   ├── market.py        # 新增：公开记忆市场
│   │   ├── memories.py      # 修改：多用户隔离
│   │   └── ...
│   ├── core/
│   │   ├── auth.py          # 修改：JWT 验证 + 旧 Token 兼容
│   │   └── config.py        # 修改：新增 GitHub/JWT 配置
│   ├── models/
│   │   ├── user.py          # 新增
│   │   └── memory.py        # 修改：加 visibility/forked_from
│   └── schemas/
│       ├── user.py          # 新增
│       └── memory.py        # 修改
├── alembic/versions/
│   └── 002_add_users.py     # 新增迁移

echome/
├── commands/
│   ├── login.py             # 新增
│   └── market.py            # 新增

web/src/
├── views/
│   ├── Login.vue            # 修改：GitHub OAuth 按钮
│   └── Market.vue           # 新增
├── stores/
│   └── auth.ts              # 修改：JWT 管理
└── router.ts                # 修改：新增路由
```
