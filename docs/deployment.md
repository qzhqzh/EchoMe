# EchoMe 部署指南

本文档分两部分：**服务端部署**（管理员执行一次）和**用户接入**（每个用户执行）。

---

## Part 1: 服务端部署（管理员）

> 管理员在服务器上部署 EchoMe Hub，让所有用户可以通过 Web 或 CLI 使用。

### 前提条件

- 一台 Linux 服务器（推荐 Ubuntu 22.04+）
- Docker + Docker Compose
- 一个域名（如 `echome.qzhqzh.com`）+ nginx 反向代理
- （可选）NVIDIA GPU + nvidia-container-toolkit（用于 embedding 加速）

### Step 1: 克隆仓库

```bash
git clone https://github.com/qzhqzh/EchoMe.git
cd EchoMe
```

### Step 2: 配置环境变量

```bash
cp hub/.env.example hub/.env
vim hub/.env
```

必须修改的项：

```env
# 旧的单租户 token（保留用于 CLI 兼容）
ECHOME_AUTH_TOKEN=你的随机token

# GitHub OAuth（去 https://github.com/settings/developers 创建 OAuth App）
# Homepage URL: https://你的域名
# Callback URL: https://你的域名/login
ECHOME_GITHUB_CLIENT_ID=你的ClientID
ECHOME_GITHUB_CLIENT_SECRET=你的ClientSecret

# JWT 密钥（openssl rand -hex 32 生成）
ECHOME_JWT_SECRET=随机64位hex字符串

# 数据库（docker-compose 内网，不用改）
ECHOME_DATABASE_URL=postgresql+asyncpg://echome:echome@postgres:5432/echome
```

### Step 3: 启动所有服务

```bash
docker compose up -d
```

启动的服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| hub | 20000 | FastAPI 后端 |
| web | 20001 | Vue 3 前端 |
| embedding | 20002 | BGE-M3 向量服务 |
| postgres | 5432 | PostgreSQL + pgvector |
| redis | 6379 | 缓存 |

### Step 4: 配置 nginx 反向代理

```nginx
server {
    listen 443 ssl;
    server_name echome.qzhqzh.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # 前端
    location / {
        proxy_pass http://127.0.0.1:20001;
        proxy_set_header Host $host;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:20000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 健康检查
    location /health {
        proxy_pass http://127.0.0.1:20000;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Step 5: 验证部署

```bash
# 后端健康检查
curl https://echome.qzhqzh.com/health
# 应返回: {"status":"ok","version":"0.1.0"}

# 前端
# 浏览器访问 https://echome.qzhqzh.com 应看到登录页
```

### Step 6: 首次登录（成为 Admin）

1. 访问 `https://echome.qzhqzh.com`
2. 点击 "Login with GitHub"
3. 授权后自动跳回，**第一个登录的用户自动成为 admin**
4. 侧边栏出现 "Admin" 入口

### Step 7: 迁移旧数据（如果之前有单租户数据）

```bash
docker compose exec -T postgres psql -U echome -d echome -c "
DO \$\$
DECLARE
    admin_uuid TEXT;
    cnt INTEGER;
BEGIN
    SELECT id::text INTO admin_uuid FROM users WHERE role = 'admin' ORDER BY created_at ASC LIMIT 1;
    IF admin_uuid IS NULL THEN RAISE EXCEPTION 'No admin user found'; END IF;
    RAISE NOTICE 'Migrating to admin: %', admin_uuid;
    UPDATE memories SET user_id = admin_uuid WHERE user_id = 'default';
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'Memories: % rows', cnt;
    UPDATE projects SET user_id = admin_uuid WHERE user_id = 'default';
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'Projects: % rows', cnt;
    UPDATE sync_log SET user_id = admin_uuid WHERE user_id = 'default';
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'Sync logs: % rows', cnt;
END \$\$;
"
```

### 日常维护

```bash
# 查看日志
docker compose logs -f hub
docker compose logs -f embedding

# 重启
docker compose restart hub

# 更新代码
git pull origin main
docker compose up -d --build

# 备份数据库
docker compose exec -T postgres pg_dump -U echome echome > backup.sql
```

---

## Part 2: 用户接入

> 每个用户在自己的电脑上执行，连接到管理员部署的 Hub。

### 方式 A: Web 使用（零安装）

1. 打开 `https://echome.qzhqzh.com`（管理员提供的地址）
2. 点击 "Login with GitHub" 完成授权
3. 开始使用：
   - **Dashboard** — 概览
   - **Memories** — 管理记忆（增删改查）
   - **Review** — 审核 AI 建议的记忆
   - **Market** — 浏览/Fork 公开记忆
   - **Projects** — 管理项目

无需安装任何东西，浏览器即可使用全部功能。

### 方式 B: CLI + MCP（推荐开发者）

#### 1. 安装 CLI

```bash
# 推荐：完整安装（CLI + MCP Server）
pip install echome[mcp]

# 或用 uv
uv tool install echome[mcp]
```

#### 2. 登录

```bash
echome login
```

会打开浏览器完成 GitHub OAuth，自动保存 JWT 到 `~/.echome/config.yaml`。

如果浏览器打不开（如远程服务器），用手动模式：

```bash
echome login --manual
# 按提示操作：浏览器授权 → 复制 token → 粘贴
```

#### 3. 验证连接

```bash
echome whoami
# 输出：
#   User:     qzhqzh
#   Role:     admin
#   Hub:      https://echome.qzhqzh.com
```

#### 4. 添加记忆

```bash
# 交互式
echome add

# 快速模式
echome add "PR 必须带工单号" \
  -c "所有 PR 标题以 [JIRA-XXX] 开头" \
  -t workflow --layer L0 -p 9 --tags "git,pr"
```

#### 5. 同步到 AI CLI

```bash
echome sync
# 将 L0 记忆写入 ~/.claude/CLAUDE.md
# 将 L1 记忆写入当前项目的 CLAUDE.md
```

#### 6. 注册 MCP Server

```bash
echome mcp install
# 自动写入 ~/.claude/mcp.json
# 重启 Claude Code 后生效
```

之后 Claude Code / Codex CLI 就能通过 MCP 实时查询你的记忆了。

#### 7. 日常使用

```bash
echome list                    # 查看记忆
echome search "代码规范"        # 搜索
echome review                  # 审核 AI 建议
echome market browse           # 浏览公开记忆
echome market fork <id>        # Fork 感兴趣的记忆
echome sync                    # 有改动时重新同步
```

### 方式 C: 纯 API 使用（高级）

如果你用其他 AI 工具或想自己集成：

```bash
# 获取 JWT（通过 GitHub OAuth）
TOKEN="your-jwt-token"

# 列出记忆
curl -H "Authorization: Bearer $TOKEN" https://echome.qzhqzh.com/api/v1/memories

# 搜索（语义）
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  https://echome.qzhqzh.com/api/v1/memories/search \
  -d '{"query": "git 规范", "top_k": 5}'

# 创建记忆
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  https://echome.qzhqzh.com/api/v1/memories \
  -d '{"title": "新规则", "content": "详细内容", "type": "workflow", "layer": "L0"}'
```

完整 API 文档见 [api-spec.md](api-spec.md)。

---

## 用户操作流程图

```
新用户注册:
  浏览器打开 Hub → Login with GitHub → 自动创建账号 → 开始使用

日常使用 (Web):
  登录 → Memories 页面 → 添加/编辑记忆 → 设置 type/layer/scope

日常使用 (CLI):
  echome login → echome add → echome sync → AI 自动读取

AI 写入记忆:
  AI 对话中调用 echome_remember → 记忆进入 pending → 用户 echome review 确认

记忆共享:
  设置 visibility=public → 出现在 Market → 其他用户可 Fork
```

---

## 权限说明

| 角色 | 能做什么 |
|------|---------|
| **user** | 管理自己的记忆、项目；浏览 Market；Fork 公开记忆 |
| **admin** | 以上全部 + Admin 面板（系统统计、用户管理、删除任何记忆） |

第一个 GitHub 登录的用户自动成为 admin。后续用户为普通 user。Admin 可在 Admin 面板提升/降级其他用户。
