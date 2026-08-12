## Unreleased

- feat: add evidence-first Project Context Compiler with chunk/FTS/vector/graph/temporal retrieval
- feat: add knowledge freshness, versioned revalidation, append-only events, and read-only preflight
- feat: add 26-case context quality eval, consecutive quality gates, and proposal-only automation
- feat(web): add Project Context quality evaluation and automation observability
- fix: generate trusted quality snapshots inside Hub instead of accepting client-supplied results
- fix: align MCP side-effect annotations and extend Project Context request timeout
- fix: persist expired revalidation proposals before returning a conflict
- fix: make Hub token counting fall back immediately when the tiktoken cache is unavailable offline

## v1.3.1

- 1730bfe feat: improve retrieval relevance and update MCP instructions
- 70e752c chore: update docker-compose and web dependencies
- 5bd9850 docs: update memory retrieval documentation
- 88a15ba feat(capabilities): add MCP capabilities guide
- 53745f9 feat(graph-tools): add memory graph MCP tools
- f769954 feat(retrieval-debug): add retrieval debug API and logs page
- 3f0c91d feat(feedback): add memory feedback API and MCP tools
- 7bff05d feat(observability): add web observability page and graph explain

## v1.3.0

- 8b9ddf1 docs: update CLAUDE.md with complete git-flow SOP
- 824fc64 feat: add memory sleep and observability features

## v1.2.0

- 180b1c9 feat: refine memory prompt bootstrap policy (#79)
- f720805 #76 Improve memory retrieval with summary-first workflow (#77)
- bb0a6a0 fix: echome update 默认从 PyPI 更新而非 GitHub
- 06a1060 Revert "fix: echome update 默认从 PyPI 更新而非 GitHub"
- 4fad02c fix: echome update 默认从 PyPI 更新而非 GitHub

## v1.1.7

- 6191a44 fix: use valid MemorySource enum value in seed_memories.json

## v1.1.6

- 27cfcf7 fix: use nested scope format in seed command

## v1.1.5

- 5ffa17f chore: remove old release.yml (merged into publish.yml)
- 49e84dd refactor: merge workflows into single publish.yml

## v1.1.4

- 2605496 fix: add permissions for reusable workflow call
- d5bf131 fix: call publish.yml from release.yml via reusable workflow

## v1.1.3

- a20961c fix: remove PyPI publish from release.yml

## v1.1.2

- ed91144 ci: add publish.yml for PyPI OIDC auto-publish

## v1.1.1

- 

## v1.1.0

- 52ed3be feat: add echome seed command for loading seed memories (#74)
- c9c708f feat: add echome seed command for loading seed memories
- 1759636 fix: show full UUID in echome_list_by_type instead of truncated 8-char (#73)
- b3120a7 fix: merge publish workflow into release workflow (#72)

## v1.0.1

- e22d508 fix: add trailing newline to doctor.py
- b9f0b8a fix: sync remote main before push in release action (#71)
- 4ec1198 release: v1.0.0
- a03e70c feat: add echome version command (#70)
- 8a7771c feat: add echome doctor command (#69)
- 2b90d5f fix: change default Hub URL to https://echome.qzhqzh.com (#67)
- db61ba8 feat(init): prompt to keep existing Hub config
- 6cde79d release: v0.2.2
- 4392126 docs: update installation instructions for MCP as default #63
- c79cd88 feat: MCP Server included by default #63 (#64)
- b3741ec fix: MCP 配置写入正确位置 #61 (#62)
- 8d91f51 fix: correct GitHub install syntax in README
- be90d25 docs: update README with PyPI and GitHub install methods

## v1.0.0

- a03e70c feat: add echome version command (#70)
- 8a7771c feat: add echome doctor command (#69)
- 2b90d5f fix: change default Hub URL to https://echome.qzhqzh.com (#67)
- db61ba8 feat(init): prompt to keep existing Hub config
- 6cde79d release: v0.2.2
- 4392126 docs: update installation instructions for MCP as default #63
- c79cd88 feat: MCP Server included by default #63 (#64)
- b3741ec fix: MCP 配置写入正确位置 #61 (#62)
- 8d91f51 fix: correct GitHub install syntax in README
- be90d25 docs: update README with PyPI and GitHub install methods

## v0.2.1

- 6722d52 fix: decision project association and type tabs order (#60)
- 4eb4ed8 feat: project association for all memory types (#59)
- b36e587 fix(web): redirect to type list after memory delete (#57)
- 2541867 fix(web): redirect to home after memory delete (#56)
- 046d8d7 fix(hub): resolve ruff lint error in main.py
- 34ee7ab fix(mcp): resolve ruff lint errors (#55)
- eabe9da feat(hub): add memory format standardization rule to MCP_INSTRUCTION (#53)
- 3620279 fix(hub): change memory list sort to updated_at only
- cc317e8 docs(hub): optimize MCP_INSTRUCTION for clarity and tool triggers (#50)
- 22241f4 fix(hub): commit before background task to prevent lock contention #47
- beaf8dd fix(web): resolve duplicate requests and add JWT auto-refresh
- afd852c feat(mcp): add task completion memory rule to MCP_INSTRUCTION
- dd514d6 feat(web): add 'All' option to status filter dropdown
- aadb900 feat(mcp): add project creation validation for AI memories
- 036cab3 feat(web): enhance memory/project views and review page
- 6f23c50 fix: add __main__.py for python -m echome_mcp
- 4b5871c feat: AI记忆写入 + 向量维度修复
- f619ff4 refactor(cli): extract update helpers for cleaner code organization
- 50f9953 Add Codex MCP config and memory_search alias
- 946b6e8 feat: add coding behavior guidelines to seed memories

## v0.2.0

- 03eddd5 feat(ci): auto release with changelog + tag + fix Node.js 20 warning
- 1faf1dc remove test-hub
- 64d3962 ci: remove test-hub job (requires PostgreSQL not available in CI)
- e342a91 fix(ci): skip DB-dependent tests, set env vars for hub tests
- 1fc6f81 fix(ci): skip DB-dependent tests, set env vars for hub tests
- 1e8f1b1 fix(ci): set test env vars in conftest + remove unused app.main import
- 4075eb8 fix(test): mock async_session_factory in embedding DB error test
- 6655609 ci: trigger actions to verify merged state
- 9a22f41 chore: apply minimal Ruff fixes
- 1fff68a test: initialize Memory fixture via ORM constructor in layer update tests
- acb000b Fix current CI blockers in lint and hub layer tests
- 15c7dee Initial plan
- 850e4c2 Initial plan
- 27ef955 test: initialize Memory fixture via ORM constructor in layer update tests
- 10ce4e7 Initial plan
- d50cc41 Initial plan
- 1072c92 Fix Ruff lint failures in CLI files
- b118e61 Initial plan
- 94ced95 feat: rename package to echome + add CI/CD workflows
- c26c5b3 fix: move dependencies out of [project.urls] section (build error)
- d2214c7 fix: rename PyPI package from echome-cli to echome
- 60f15b7 fix: add PyPI metadata (readme, authors, classifiers, urls)
- 5b584f2 feat: switch from Docker volumes to disk mount + migration script
- 10089fa chore: add uv.lock to gitignore
- 06b4855 fix: add session commit logging + layer update persistence tests
- f38c8dd fix(web): pass type to create-first-memory button too
- d3b17c1 fix(web): pre-select type when creating memory from filtered view
- 3a85030 fix: background embedding task exception rollbacks main request
- 90af167 fix: remove _claim_default_data and migration 004 - use manual SQL instead
- ece802e fix: claim orphaned default user_id data on first admin login
- 75fa478 fix: embedding background task race condition overwrites field updates
- abfa11c fix: add flush before return in PUT/PATCH to persist changes
- 8d78514 fix: separate L0 global from L1 project in sync/render
- 3b3b7b7 fix: Windows compatibility for chmod and pgrep
- ae17986 feat(web): add permanent delete option for memories
- a9bcc48 docs: add tech stack steering (soft preferences, non-binding)
- 0fae3aa feat(web): add i18n support with zh/en language switching
- 37f3130 feat: code cleanup, hub API unit tests, and /help page
- 0cc819f feat: rename memory types + add reasoning
- dfefa27 fix: back button uses router.back() to preserve filter state
- 96c21ad fix: seed memories deduplication by title (idempotent)
- e820de4 fix: preserve filter state when navigating back from memory detail
- 95cd194 feat: show user_id on Settings page
- c56e3cb fix: remove unused imports in Memories.vue (TS6133)
- 6dc7174 feat: memory type priority system, seed memories, tab UI
- df3a97e feat: add API rate limiting (slowapi)
- d773abc fix: security hardening, bug fixes, and open-source essentials
- 8382485 fix: check login before sync/push/pull, show friendly error when logged out
- 92b8e2e feat: make token-paste the default login flow, browser is --browser
- be4aa93 fix: CLI login retry on bad token + Settings copy UX improvements

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
