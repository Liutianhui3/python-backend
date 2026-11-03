# Python Backend

适合逐步学习的 FastAPI 项目骨架，按业务模块组织代码。已实现用户注册、登录、当前用户和退出接口，并与 my-blob-api 的用户字段对齐。

## 角色管理与文章管理

- 管理员（角色 1）：可访问角色管理，查询和维护所有文章。
- 普通用户（角色 2）：可阅读已发布文章。
- 文章编辑（角色 3）：可新建文章，只能查询管理、编辑、发布、删除自己的文章（含草稿），不能分配角色。

管理员接口：`GET /admin/users` 分页查询用户（`page`、`limit`、`q`、`role`），
`GET /admin/roles` 查询可分配角色，`PATCH /admin/users/{id}/role` 替换用户角色。
保存请求示例：`{"roleIds":[2,3]}`。每人至少保留一个角色，并且系统至少保留一位管理员。
角色变更在事务中完成，服务端每次访问管理接口都会查询当前角色，旧 JWT 不会保留已撤销的权限。

文章接口兼容 myBlob：公开阅读 `GET /articles`、`GET /articles/{id}`；
管理员和文章编辑可访问 `GET /articles/manage`、`GET /articles/manage/{id}`、
`POST /articles`、`PATCH /articles/{id}`、`DELETE /articles/{id}`。
管理列表及总数按文章归属过滤；编辑访问他人文章的管理详情、修改或删除接口返回 404。同时拥有角色 1 和 3 时按管理员权限处理。
更新文章时需提交当前 `version`，版本冲突返回 409；正文经过 HTML 清理，草稿不会公开返回。
迁移 `60ba1b3b77ce` 创建文章表，其他环境需执行 `uv run alembic upgrade head`。

JWT 无效返回 401，角色不满足要求返回 403，响应仍使用 `code/message`。
myBlob 收到当前登录请求的 401/403 后清除 token 和用户缓存、跳转登录页；
旧请求迟到的鉴权失败不会清除后续新登录的会话。Redis 不可用返回 503，不触发强制登出。

## 启动

在项目根目录执行：

```bash
uv sync
cp .env.example .env
# 设置 JWT_SECRET，启动 Redis：docker compose up -d
uv run alembic upgrade head
uv run uvicorn python_backend.main:app --reload
```

- 注册：`POST http://127.0.0.1:8000/users/register`。
- 自动接口文档：<http://127.0.0.1:8000/docs>。
- `uv run python-backend` 也能启动服务，但不自动重载。

已移除占位的 `/health` 接口。启动应用不会自动执行迁移，请先运行 `uv run alembic upgrade head`。

## 注册接口与学习路径

```bash
curl -X POST http://127.0.0.1:8000/users/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"password123"}'
```

成功返回 `201` 和公开用户资料；用户名或邮箱重复返回 `409`，输入校验失败返回 `422`。
返回字段采用 camelCase（如 `workExperiences`、`createdAt`），不返回密码哈希。

建议按下面顺序读代码，文件中有解释职责和关键行为的中文注释：

1. `main.py → api/router.py`：创建应用、汇总业务路由。
2. `modules/users/router.py`：相当于 NestJS Controller，把 HTTP 输入交给 Service，将业务异常映射为 HTTP 响应。
3. `modules/users/schemas.py`：Pydantic 请求/响应模型，类似 DTO；响应模型只允许输出公开字段。
4. `db/session.py`：通过 Depends 为每次请求提供独立数据库会话，请求结束关闭。
5. `modules/users/service.py`：生成密码哈希、写入用户、提交事务；唯一约束失败时回滚。当前逻辑简单，直接使用 ORM，暂不增加 Repository。
6. `modules/users/models.py`：SQLAlchemy 数据库映射；修改它不代表数据库已经变更，需要执行迁移。

注册规则：用户名去首尾空格，3–32 位字母、数字或下划线；邮箱去首尾空格并转小写；密码为 8–128 字符，包含英文字母和数字，不去空格。拒绝额外字段，因此客户端不能指定管理员权限。
邮箱使用 `EmailStr`，比旧项目正则更严格。`SecretStr` 仅隐藏模型显示中的密码，真正存储前仍需哈希。
密码使用随机盐和 scrypt，存储格式及参数与 my-blob-api 一致。注册不自动登录或创建会话。

## 验证

```bash
uv run pytest
TEST_POSTGRES=1 uv run pytest  # 额外验证真实 PostgreSQL 唯一索引和事务回滚
uv run ruff check .
uv run alembic check
```

普通测试使用独立 SQLite 数据库。PostgreSQL 测试使用当前 `.env` 配置，通过外层事务回滚测试数据，需先执行迁移。

## 数据库配置

在项目根目录的 `.env` 中填写 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER` 和 `DB_PASSWORD`，分别对应地址、端口、数据库名、账号和密码。`.env.example` 提供配置格式，不包含实际密码。

`core/config.py` 中的 `Settings` 会读取这些值，例如 `DB_HOST` 对应 `settings.db_host`。端口会被转换成整数，并检查是否在 1–65535 范围内。系统环境变量优先于 `.env`，未配置时使用代码里的默认值。

密码使用 `SecretStr`，常规显示时会隐藏内容。当前空密码仅表示尚未填写，不会自动获得数据库访问权限；连接数据库前需填入实际密码。不要输出密码或完整连接信息。

配置本身只读取参数，不创建连接。`db/engine.py` 使用这些参数创建 SQLAlchemy Engine，类似 Node.js `pg` 的 Pool 所承担的连接管理角色。创建 Engine 不代表连接已经成功，实际调用 `connect()` 时才建立连接。

当前使用同步连接方式。`pool_pre_ping=True` 用于检查从连接池取出的连接是否可用，`connect_timeout=5` 设置连接超时。连接地址用 `URL.create()` 组装，`.env` 中的密码直接填写原值，不需要手动做 URL 编码。

目前没有把数据库查询加入 `/health`，应用启动时不会自动建表，表结构由 Alembic 迁移管理。

## 用户 ORM 模型

`db/base.py` 定义公共 `Base`；`modules/users/models.py` 中的 `User` 继承它，映射到名为 `users` 的表。

用户字段与 my-blob-api 对齐，包括：

- 基础字段：`id`、`name`、`username`、`email`、`created_at`、`updated_at`。
- 角色通过 `user_roles` 关联 `roles`，支持多角色；新注册用户默认拥有角色 2（普通用户）。`is_admin` 已移除。
- 资料字段：`location`、`website`、`bio`、`avatar`、`phone`、`about`，默认空字符串。
- JSONB 字段：`skills`、`work_experiences`，默认空数组。

字段长度、可空性和默认值沿用旧项目：用户名和密码哈希允许 NULL，以支持仅创建资料的用户；注册接口仍强制填写。注册时 `name` 默认等于用户名。
`password_hash` 是仅供服务端验证密码的凭据，不属于公开资料响应；登录依赖它校验用户名和密码，因此不能随 JWT 改造一起删除。JWT 取代的是数据库会话记录，不取代密码哈希。
用户名和邮箱有忽略大小写的唯一索引。`onupdate` 是 ORM 的更新行为，不是数据库触发器，手写 SQL 更新时需自行更新 `updated_at`。

新增迁移 `92f0b3c1a801_align_user_profile.py` 补齐字段，并用已有 username 回填 name，不重建用户表。回退该迁移会删除新增资料字段；若已有用户名或密码为空的资料用户，恢复非空约束会失败，需先处理数据。

## 数据库迁移

可以把迁移理解为“数据库表结构的版本记录”：

```text
models.py 定义期望的表结构
    ↓ alembic revision --autogenerate
migrations/versions/ 保存变更步骤
    ↓ alembic upgrade head
数据库实际执行变更，alembic_version 表记录当前版本
```

第一份迁移是 `migrations/versions/4a74ba13dd88_create_users_table.py`：`upgrade()` 创建用户表和索引，`downgrade()` 描述反向操作。回退这份迁移会删除用户表及其中的数据，不作为日常检查命令。

以下命令在项目根目录执行：

```bash
uv run alembic current        # 查看数据库当前的迁移版本
uv run alembic upgrade head   # 把尚未执行的迁移应用到当前 .env 指定的数据库
uv run alembic check          # 检查 ORM 模型与数据库是否还有待生成的结构变更
```

迁移已经在当前数据库执行成功；重复执行 `upgrade head` 不会重复创建用户表。`alembic_version` 是工具维护的版本表，不是业务表。

以后修改模型时，先执行 `uv run alembic revision --autogenerate -m "describe change"` 生成迁移，检查生成内容，再执行 `uv run alembic upgrade head`。自动生成的文件需要人工审查，不能只改模型后直接认为数据库已经同步。将 `alembic.ini` 和整个 `migrations/` 目录提交到 Git。

## 全局错误格式

所有错误响应统一为 `{"code": 409, "message": "用户名或邮箱已被使用"}`。
`code` 等于真实 HTTP 状态码，前端通过 `response.ok` 判断是否成功，失败时直接显示 `message`。
参数校验失败返回 422 和第一条中文提示；404、405、未处理的 500 也采用同一结构。
内部错误不向客户端暴露 SQL、异常堆栈或请求内容。成功响应仍直接返回用户资料。
全局处理位于 `core/errors.py`，新增业务接口通常只需抛出带提示词的 `HTTPException`。

## 登录、当前用户与退出

认证接口沿用以下地址和响应：

- `POST /users/login`：请求 `{"username":"alice","password":"password123"}`，成功返回 200 和 `{"user":{公开用户资料},"token":"JWT"}`。
- `GET /users/me`：携带 `Authorization: Bearer <token>`，成功返回 200 和公开用户资料；未登录、令牌无效或过期返回 401 和“请先登录”。
- `POST /users/logout`：携带同一请求头，把 JWT 的 `jti` 放入 Redis 黑名单直到令牌过期，返回 204 空响应。重复退出或未携带令牌也返回 204。

用户名去首尾空格且忽略大小写。登录密码允许 1–128 字符，不套用注册复杂度规则，不去除空格。
用户名或密码错误统一返回 401 和“用户名或密码不正确”；输入格式错误继续沿用本项目的 422 错误协议。
登录不会设置 Cookie，客户端需保存 token 并在后续请求中携带 Bearer 请求头。
登录、注册和当前用户响应的用户资料包含 `roles` 数组，每个角色返回 `id`、`name`、`nameCn`。迁移为已有用户补上角色 2，并把原管理员标志转换为角色 1；前端返回的角色用于展示，不能替代后端接口权限校验。

令牌使用 HS256 签名，包含用户 ID（`sub`）、唯一令牌 ID（`jti`）和过期时间（`exp`），有效期由 `JWT_EXPIRE_SECONDS` 配置。受保护请求会检查 Redis 黑名单；Redis 不可用时返回 503 并拒绝请求。
退出仅撤销当前令牌，同一用户的其他登录令牌仍有效。新增迁移 `c8d0f6a12b34_drop_user_sessions.py` 删除旧 `user_sessions` 表；运行 `uv run alembic upgrade head` 后该表及其中数据会被删除。该迁移不可逆。

Redis 通过根目录的 `compose.yaml` 运行：`docker compose up -d` 启动，`docker compose ps` 查看状态，`docker compose down` 停止并移除容器（数据卷保留）。`.env` 设置 `REDIS_URL`，本机运行后端时默认地址为 `redis://127.0.0.1:6379/0`。设置 `JWT_SECRET` 为随机秘密值，不要提交 `.env`。
