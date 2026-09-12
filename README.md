# 拾光集市

面向校内学生的二手交易平台。当前完成工程骨架、质量基线和 PostgreSQL 数据底座的前置准备；业务功能按 `开发文档.md` 的阶段门禁逐步实现。

## 环境要求

- Node.js 24 与 Corepack
- pnpm 9.15.9
- `D:\python\virtual\fastapi-env` 中的 Python 3.12
- 本机 PostgreSQL 18 与 Redis

本机实测版本、复检命令和故障处理见 `docs/环境说明.md`。

## 初始化

```powershell
Copy-Item '.env.example' 'backend\.env'
```

编辑 `backend/.env`，只在本机填写项目数据库连接和 Redis 地址。该文件被 Git 忽略，不要把真实连接 URL、密码或令牌复制到文档、终端输出或提交中。

安装或核对依赖：

```powershell
& '.\scripts\check.ps1' -Install
```

`-Install` 会复用固定 Python 环境，并只在 `frontend` 安装 pnpm 依赖，不创建新虚拟环境。

## 本地启动

打开两个 PowerShell 终端。

后端：

```powershell
Set-Location 'backend'
& 'D:\python\virtual\fastapi-env\Scripts\python.exe' -m uvicorn app.main:app --reload
```

前端：

```powershell
Set-Location 'frontend'
pnpm dev
```

访问 `http://127.0.0.1:5173`。前端开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。后端 OpenAPI 位于 `http://127.0.0.1:8000/docs`。

## 完整检查

```powershell
& '.\scripts\check.ps1'
```

该命令依次执行后端 Ruff 格式检查、Ruff Lint、严格 mypy、pytest，以及前端类型检查、ESLint、Prettier、Vitest 和生产构建；任一步失败都会停止。

第二阶段数据库门禁使用独立临时 schema，不触碰 `public` 中的数据：

```powershell
& '.\scripts\check.ps1' -Postgres
```

该模式在上述检查后执行真实 PostgreSQL 迁移往返、Alembic 漂移检查、事务与领域约束测试，并重复运行分类种子验证幂等性。连接只从进程环境或被 Git 忽略的项目 MCP 配置读取，不会回显。

## 当前边界

- 首页、登录、管理端和 404 当前是工程外壳，不包含伪造的商品或账号数据。
- 存活检查 `/api/v1/health/live` 不依赖外部服务。
- 就绪检查 `/api/v1/health/ready` 会分别报告 PostgreSQL 与 Redis 状态。
- 数据库结构变更统一使用 Alembic，不以 MCP 临时操作替代迁移。
