# 拾光集市 · 后端

FastAPI 服务承载校园认证、商品、聊天、订单、信用、治理和运营后台。PostgreSQL 保存业务事实，Redis 保存验证码、短期票据和限流状态；文件由受控存储接口读取。

## 结构

```text
app/api/             路由、依赖和身份门禁
app/services/        业务规则与事务协作
app/repositories/    SQLAlchemy 查询、锁与持久化
app/models/          数据模型
app/schemas/         请求与响应定义
app/core/            配置、安全、限流与日志
app/db/              会话、初始化和维护命令
app/workers/         审计导出、订单过期任务
alembic/             数据库结构迁移
var/                 本地对象与私密文件，Git 忽略
```

API 统一使用 `/api/v1` 前缀。领域入口包括 `auth`、`account`、`campus`、`market`、`seller`、`product-images`、聊天与通知、`orders`、`credit`、`reports`、`moderation` 和 `admin`。

## 安装与启动

使用 Python 3.12 和专用 PostgreSQL 数据库 `campus_trading_platform`。从根目录 `.env.example` 创建 `backend/.env`，配置数据库、Redis、SMTP、认证密钥和文件目录。当前配置没有完整的生产启动校验，上线前必须逐项核对密钥、来源白名单、Cookie、协议文本和服务地址。

以下命令在本目录执行：

```powershell
python -m pip install -r requirements.txt
python -m alembic heads
python -m alembic upgrade head
python -m app.db.seed
python -m app.db.bootstrap_super_admin
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`seed` 用于首次安装角色、权限和默认分类；它会校正默认分类状态，日常运营时不要把它当作每次启动命令。超级管理员用户名固定为 `guo`，密码通过无回显提示输入，首次登录强制改密；已有用户名会拒绝覆盖。无邮箱管理员无法使用邮件找回密码。

初次上线需要由运营人员准备真实学校、校区和邮箱域名，经受控数据库初始化写入 `schools`、`campuses` 和 `school_email_domains`。当前后台支持维护已存在目录条目的状态和属性，尚未提供创建学校、校区和域名的界面。禁止借用其他学校的域名或制造校园身份。

单独启动导出 worker，API 与 worker 使用相同配置和文件目录：

```powershell
python -m app.workers.audit_export
```

导出 worker 同时执行到期导出清理和有限批次隐私清理。API 内运行通知与订单过期后台任务。临时商品图片清理需由调度器定期执行：

```powershell
python -m app.db.cleanup_product_images
```

## 身份、数据与交易

- 普通邮箱登录与校园身份分开。发布、私聊、下单和评价需要有效校园认证；收藏不需要校园认证。
- Access Token 用于 API；刷新会话可撤销。首登管理员改密前只开放本人账户恢复入口。
- 暂停账户保留登录、本人账户、通知和处罚申诉渠道；业务与后台入口拒绝访问。工作人员停用由专门权限流程处理。
- 订单命令使用版本和幂等请求标识；实际 PostgreSQL 行锁保护并发交易、注销与上传配额。
- 处罚下架商品通过独立申诉复核恢复，卖家不能通过改草稿或重新提审绕过处罚。
- 图片校验实际内容并重新编码、去除 EXIF；私密材料和审计导出下载重新校验权限。

当前应用依赖注入使用本地文件存储。仓库内的 S3 兼容适配器尚未接入运行配置，启用对象桶需要另行完成集成与验收。

## 检查与运维

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff format --check .
python -m ruff check .
python -m mypy app
```

存活探针 `/api/v1/health/live` 不访问依赖；就绪探针 `/api/v1/health/ready` 检查 PostgreSQL 和 Redis。当前 `/docs` 默认开放；正式发布前需在应用或代理层关闭或限制文档入口。

开发验收脚本已按收尾要求移除。修改权限、迁移、文件或交易逻辑时，应重新建立有针对性的 PostgreSQL 与浏览器回归验证。

详细操作见 [运维手册](../docs/运维手册.md)、[发布流程](../docs/发布流程.md) 和 [监控与安全运维](../docs/监控与安全运维.md)。
