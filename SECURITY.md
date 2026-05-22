# 安全策略

## 报告漏洞

如果你发现了安全漏洞，请 **不要** 在公开的 Issue 中报告。

请通过以下方式私密报告：

1. 发送邮件至项目维护者（在 GitHub profile 查看联系方式）
2. 或使用 GitHub 的 [Private Vulnerability Reporting](https://github.com/qzhqzh/EchoMe/security/advisories/new) 功能

### 报告内容

- 漏洞描述
- 复现步骤
- 影响范围
- 建议的修复方式（如有）

我们会在 48 小时内确认收到，并在 7 天内提供初步评估。

## 安全最佳实践

部署 EchoMe 时，请确保：

1. **设置强 JWT Secret**：使用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成
2. **限制网络访问**：PostgreSQL 和 Redis 不应暴露到公网
3. **使用 HTTPS**：在反向代理（如 Nginx/Caddy）中配置 TLS
4. **定期更新依赖**：关注安全公告
5. **Emergency Token**：`ECHOME_AUTH_TOKEN` 仅在 GitHub 不可用时临时启用，用完即禁用

## 已知安全设计

- JWT Token 有效期 10 年（设计选择，适合个人工具场景）
- 首个注册用户自动成为 Admin
- CLI 配置文件使用 `chmod 600` 保护
- 数据按用户隔离（user_id 过滤）
