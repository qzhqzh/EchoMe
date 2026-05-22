# EchoMe 接力开发文档

> 供下一个会话的 AI 阅读后直接开始实现。

---

## 当前状态

- 多用户系统已完成（GitHub OAuth + JWT + 数据隔离 + Market + Admin）
- Embedding 服务（BGE-M3 + ModelScope + GPU）已集成到 docker-compose
- Web Console 可正常登录和使用
- CLI `echome login --manual` 可工作但体验待优化

---

## 下一步开发计划

### 优先级 1：用户设置页 + Token 管理

**问题**：CLI 用户通过 `echome login --manual` 登录时，GitHub OAuth 回调到了 Web 前端，前端自动登录但 CLI 用户看不到 token。需要在 Web 界面提供 token 给用户复制。

**需要做的**：

1. **新增 `/settings` 页面**（`web/src/views/Settings.vue`）：
   - 显示当前用户信息（头像、用户名、角色、邮箱）
   - 显示当前 JWT token（可一键复制）
   - 显示 token 过期时间
   - "生成新 Token" 按钮（调 `/api/v1/auth/refresh`）
   - CLI 配置指引（告诉用户把 token 粘贴到哪里）

2. **修改 JWT 过期时间**：
   - `hub/app/core/config.py` 中 `jwt_expire_days` 从 7 改为 **3650**（约 10 年）
   - `.env.example` 同步更新

3. **路由和导航**：
   - 添加 `/settings` 路由到 `router.ts`
   - Sidebar 底部用户区域加 Settings 入口

4. **CLI 登录优化**：
   - `echome login --manual` 引导用户去 Web 设置页复制 token
   - 或 Hub 提供 `/api/v1/auth/cli-callback?code=xxx` 返回简单 HTML 显示 token

### 优先级 2：CLI 无 GUI 登录体验

**理想流程**：
```
echome login --manual
→ 显示 GitHub 授权 URL
→ 用户授权后跳到专门页面显示 token
→ 用户复制粘贴回终端
→ 完成
```

**实现**：前端 `/login` 页面检测到 `?source=cli` 时，不自动登录，而是显示 token 供复制。

### 优先级 3：其他

- 记忆编辑器 visibility 切换（public/private）
- Dashboard 显示最近活动
- token 过期提醒

---

## 技术上下文

| 文件 | 说明 |
|------|------|
| `hub/app/core/config.py` | `jwt_expire_days` 改为 3650 |
| `hub/app/core/jwt.py` | JWT 签发/验证 |
| `hub/app/api/auth.py` | OAuth 回调、/me、/refresh |
| `web/src/router.ts` | 前端路由 |
| `web/src/components/Sidebar.vue` | 导航 |
| `web/src/stores/auth.ts` | auth 状态 |
| `web/src/api/client.ts` | API 方法 |
| `echome/commands/login.py` | CLI 登录 |
| `echome/core/config.py` | 默认 hub_url=https://echome.qzhqzh.com |

### 开发规范

- 所有改动通过 PR 提交，合并到 main
- 中国镜像源：apt=aliyun, uv=tsinghua, npm=npmmirror, model=modelscope
- Hub 部署在 https://echome.qzhqzh.com
- GitHub OAuth Callback URL: https://echome.qzhqzh.com/login
- 首个登录用户 = admin
