# Python Backend

基于 FastAPI 的模块化 Python 后端，提供用户认证、多角色权限、文章管理、AI 流式聊天和知识库检索。用户字段和部分接口与 my-blob-api / myBlob 对齐，适合业务开发与逐步学习。

## 功能与技术栈

- **用户与权限**：注册、JWT 登录、Redis 令牌撤销、多角色分配与权限实时校验。
- **文章**：公开阅读、草稿与发布、作者归属校验、版本冲突检测和 HTML 清理。
- **AI 聊天**：多模型、思考内容、SSE 流式输出、附件解析、图片及 Word / Excel 文件生成、当前用户平台信息查询。
- **知识库**：TXT / Markdown 上传、文本切片、向量化、余弦相似度搜索与聊天 RAG。

技术栈：Python 3.13+、FastAPI、Pydantic、SQLAlchemy、PostgreSQL + pgvector、Redis、Alembic、OpenAI Python SDK；使用 uv 管理依赖，pytest / Ruff 验证代码。

## 文档导航

- [启动](#启动) · [环境变量](#环境变量) · [项目结构](#项目结构)
- [接口调用示例](#接口调用示例) · [角色管理与文章管理](#角色管理与文章管理)
- [数据库迁移](#数据库迁移) · [全局错误格式](#全局错误格式) · [验证](#验证)
- [登录、当前用户与退出](#登录当前用户与退出) · [AI、聊天与知识库](#ai聊天与知识库) · [常见问题](#常见问题)

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

### 环境准备

1. 安装 Python 3.13+、[uv](https://docs.astral.sh/uv/getting-started/installation/)；使用 Compose 启动 Redis 时还需要 Docker 与 Docker Compose。
2. 准备 PostgreSQL，创建数据库和可连接该数据库的账号，并在 PostgreSQL 服务端安装 pgvector。当前完整迁移包含向量表，即使暂不使用 AI，也需要该扩展。
3. 根目录的 `compose.yaml` **只提供 Redis**，不包含 PostgreSQL 或后端应用。

### 安装与启动

在项目根目录执行；已有 `.env` 时保留原配置，无需再次复制：

```bash
uv sync
cp .env.example .env
uv run python -c 'import secrets; print(secrets.token_hex(32))'
```

把生成的随机值填入 `.env` 的 `JWT_SECRET`，并填写 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`。示例中的 JWT 占位值仅用于展示，需自行替换。

```bash
docker compose up -d
uv run alembic upgrade head
uv run uvicorn python_backend.main:app --reload
```

迁移会执行 `CREATE EXTENSION IF NOT EXISTS vector`。账号没有创建扩展的权限时，可由数据库管理员先在目标数据库执行该语句，再运行迁移。

- 服务地址：<http://127.0.0.1:8000>。
- Swagger UI：<http://127.0.0.1:8000/docs>；ReDoc：<http://127.0.0.1:8000/redoc>；OpenAPI：<http://127.0.0.1:8000/openapi.json>。
- `uv run python-backend` 也能启动服务，但不自动重载。
- 应用不自动建表或执行迁移，也没有 `/health` 或根路径业务接口，访问 `/` 返回 404 属于正常行为。

## 环境变量

配置入口为 `src/python_backend/core/config.py`。从项目根目录启动时读取 `.env`，系统环境变量优先。以下以代码默认值为准；`.env.example` 中部分 AI 配置预填了示例值。

| 变量 | 默认值 / 要求 | 用途 |
| --- | --- | --- |
| `APP_NAME` | `Python Backend` | 接口文档标题 |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `5432` | PostgreSQL 地址与端口 |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `python_backend` / `postgres` / 空 | 目标数据库及凭据，按实际环境填写 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | JWT 黑名单存储 |
| `JWT_SECRET` | 必填，无默认值 | HS256 签名密钥 |
| `JWT_EXPIRE_SECONDS` | `3600` | 令牌有效期，单位秒 |
| `AI_API_KEY` | 空；也支持 `DASHSCOPE_API_KEY` | 聊天密钥；同时配置时优先 `AI_API_KEY` |
| `AI_BASE_URL` / `AI_MODEL` | 千问兼容地址 / `qwen3.8-max` | 聊天服务与默认模型 |
| `AI_MODELS` | 空 | JSON 模型白名单，配置时须包含默认模型，格式见 `.env.example` |
| `AI_SYSTEM_PROMPT` | `你是一个有帮助的中文助手。` | 聊天系统提示词 |
| `AI_TIMEOUT_MS` / `AI_MAX_TOKENS` | `120000` / `2048` | 模型超时（毫秒）与最大输出 token 数 |
| `AI_CONTEXT_MAX_BYTES` | `24000` | 上下文大小预算（字节） |
| `AI_IMAGE_TOOLS_ENABLED` / `AI_IMAGE_MODEL` | `true` / `qwen-image-3.0-pro` | 图片生成开关与模型 |
| `AI_IMAGE_BASE_URL` / `AI_IMAGE_API_KEY` | 空 / 空 | 原生图片接口完整 URL；密钥留空复用聊天密钥 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` | 千问兼容地址 / 空 | 向量接口地址；密钥留空复用聊天密钥 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | 空 / `1024` | 向量模型与输出维度；模型留空关闭聊天 RAG |

千问兼容地址为 `https://maas.qianwenapi.com/compatible-mode/v1`。`.env.example` 预填了图片接口，以及 SiliconFlow 的 embedding 地址、`BAAI/bge-m3` 模型和 1024 维配置；复制后若暂不使用向量化，可将 `EMBEDDING_MODEL` 留空。不同服务商通常需要分别配置密钥，模型名称与维度应以服务商实际支持情况为准。

## 项目结构

```text
.
├── src/python_backend/
│   ├── main.py              # FastAPI 应用与全局错误处理
│   ├── api/router.py        # 汇总业务路由
│   ├── core/                # 配置、JWT、Redis、错误协议
│   ├── db/                  # ORM Base、连接池、请求级 Session
│   └── modules/
│       ├── users/           # 注册、登录、当前用户、退出
│       ├── roles/           # 管理员用户查询与角色分配
│       ├── articles/        # 文章阅读与管理
│       ├── ai/              # 模型目录、SDK、工具调用
│       ├── chat/            # 会话、SSE、附件与生成文件
│       └── knowledge/       # 文档、切片、embedding、RAG
├── migrations/              # Alembic 迁移记录
├── tests/                   # API、AI/知识库、可选 PostgreSQL 测试
├── .env.example             # 环境变量示例
├── compose.yaml             # 本地 Redis
├── pyproject.toml           # 项目、依赖与工具配置
└── uv.lock                  # 锁定依赖版本
```

## 接口调用示例

以下命令在服务启动后执行。先注册用户（见下一节），再登录：

```bash
curl -sS http://127.0.0.1:8000/users/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"password123"}'

# 将登录响应中的 token 填入变量
TOKEN='替换为登录返回的JWT'
curl -sS http://127.0.0.1:8000/users/me \
  -H "Authorization: Bearer $TOKEN"

curl -sS http://127.0.0.1:8000/conversations \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"我的第一段对话"}'

# 将创建会话响应中的 id 填入变量；聊天需先配置有效的模型密钥
CONVERSATION_ID='替换为会话ID'
curl -N http://127.0.0.1:8000/conversations/$CONVERSATION_ID/messages/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"你好，请介绍一下自己。"}'
```

接口没有统一 `/api` 前缀。除注册、登录和公开文章阅读外，业务接口通常需要 Bearer Token；具体参数与响应以 `/docs` 和路由实现为准。聊天为 POST SSE，客户端需流式读取响应，并根据 `event` 分派 JSON `data`；流已开始后的错误通过 `error` 事件传递。

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

以目标环境的 `alembic current` 输出为准；重复执行 `upgrade head` 不会重复应用已经执行的迁移。`alembic_version` 是工具维护的版本表，不是业务表。

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

## AI、聊天与知识库

从 `my-blob-api` 迁移的业务位于 `modules/ai`、`modules/chat`、`modules/knowledge`。
路由仅处理 HTTP 参数和认证；模型、schema、业务、SDK 客户端、SSE、附件解析、向量及 RAG 各自独立。
聊天和 embedding 均通过 `AsyncOpenAI` SDK 调用兼容接口，不手工拼接模型 HTTP 请求。

1. 按 `.env.example` 配置 `DASHSCOPE_API_KEY`（或 `AI_API_KEY`）、`AI_BASE_URL`、`AI_MODEL`。
   默认地址为 `https://maas.qianwenapi.com/compatible-mode/v1`，默认模型为 `qwen3.8-max`。
2. PostgreSQL 需安装 pgvector；运行 `uv run alembic upgrade head` 创建会话与知识库表。
   首次迁移执行 `CREATE EXTENSION IF NOT EXISTS vector`，数据库账号需具备对应权限。
3. 需要向量化和聊天 RAG 时设置 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL` 和模型实际输出维度
   `EMBEDDING_DIMENSIONS`；可独立设置 `EMBEDDING_API_KEY`，否则复用聊天密钥。
   未配置 embedding 模型时普通聊天正常工作。切换向量模型后需重新向量化文档。
4. 默认开启 `AI_IMAGE_TOOLS_ENABLED=true`：聊天模型通过 `tool_choice=auto` 自行决定何时调用
   `generate_image`，后端使用 `AI_IMAGE_MODEL=qwen-image-3.0-pro` 生成图片，再通过 SSE 返回图片 Markdown。
   聊天继续使用 OpenAI SDK；图片工具调用千问原生多模态接口，使用 `input.messages` 和
   `parameters.prompt_extend` 请求格式，从 `output.choices[].message.content[].image` 读取图片。
   `AI_IMAGE_BASE_URL` 必须填写完整图片接口地址，后端直接请求，不拼接路径。
   `AI_IMAGE_API_KEY` 留空时复用聊天密钥。无需前端按钮；前端继续渲染 `delta` 中的 Markdown 图片。

所有接口沿用当前项目 Bearer Token 认证与用户数据隔离：

- `/conversations`：创建、列表；`DELETE /conversations/{id}` 删除会话。
- `GET /conversations/models`：模型及支持的思考档次。
- `GET /conversations/{id}/messages`：`before` 顺序号游标与 `limit` 分页。
- `POST /conversations/{id}/messages/stream`：`content`、`attachments`、`model`、`reasoningEffort`。
  SSE 事件包括 `start`、`reasoning`、`delta`、`image_generation`、`file_generation`、`file`、`done`、`error`，等待期间每 15 秒发送 `: ping` 心跳；
  中断、超时会保存回复状态，生成租约阻止同一会话并发生成。
- `POST /conversations/attachments/extract`：multipart `file`，支持 DOCX/XLSX/PDF/PPTX，最大 10 MB。
- `POST /conversations/{id}/messages/{messageId}/images/download`：下载该用户消息中的图片。
- `/knowledge-bases`：创建、列表。
- `/knowledge-bases/{id}/documents`：列表、multipart 上传 UTF-8 TXT/MD，最大 1 MB；
  可传 `chunkSize`（100–2000，默认 500）及 `chunkOverlap`（默认 50，小于片长）。
- `GET /knowledge-bases/{id}/documents/{documentId}/chunks`：切片分页。
- `DELETE /knowledge-bases/{id}/documents/{documentId}`：删除文档及切片。
- `POST /knowledge-bases/{id}/documents/{documentId}/embeddings`：文档向量化。
- `POST /knowledge-bases/{id}/search`：`query` 与 `limit`（1–20），返回余弦相似度结果。

此迁移创建新数据库表，不自动导入旧项目的用户、历史会话或知识库数据。


聊天文件工具：默认向模型提供 `generate_excel` 和 `generate_word`。用户提出生成文件请求时，
模型通过工具参数提供内容，后端生成 `.xlsx` / `.docx` 并保存到 `chat_generated_files`，
无需前端解析代码块。部署前执行 `uv run alembic upgrade head`。
SSE 新增 `file_generation`（生成中）和 `file`（id、name、mimeType、size、downloadUrl）事件；
历史消息的 `files` 数组返回相同元数据。下载地址需要 Bearer 登录认证，并校验会话与消息归属。
文件与消息关联，删除会话时一并清理。当前每轮最多生成一个文件，Excel 单元格作为普通值写入。

平台只读工具 `get_my_platform_info`：支持 `articles`、`roles`、`profile`、`all` 查询范围，
回答当前登录用户的文章数量/标题、角色、用户名和显示名称。用户身份由服务端注入，
模型不能指定其他用户；文章总数包含草稿及已发布文章，标题每次最多100条并标注是否还有更多。
后端将查询结果作为 tool 消息交回模型，由模型生成自然语言回答，无需前端修改或新增表。


## 常见问题

| 现象 | 排查方式 |
| --- | --- |
| 启动提示缺少 `JWT_SECRET` | 确认已创建 `.env`、填写密钥，并从项目根目录执行命令 |
| PostgreSQL 连接失败 | 检查数据库是否已创建、账号密码及网络；Compose 不提供 PostgreSQL |
| 迁移提示 `vector` 扩展不存在或权限不足 | 在 PostgreSQL 服务端安装 pgvector，并由有权限的账号在目标库创建扩展 |
| 请求提示表不存在 | 对当前 `.env` 指定的数据库执行 `uv run alembic upgrade head` |
| 受保护接口返回 503 | 检查 Redis 连接配置以及 `docker compose ps`、`docker compose logs redis` |
| 普通用户无法管理文章或分配角色 | 注册默认只分配角色 2；文章管理需角色 1 或 3，角色分配需角色 1，不提供公开提权接口 |
| AI 调用失败或超时 | 检查密钥、服务地址、模型访问权限以及 `AI_TIMEOUT_MS`；图片接口需填写完整原生 URL |
| 向量化失败或维度不匹配 | 检查 embedding 服务密钥、模型与输出维度；切换模型后重新向量化文档 |
| SSE 输出成批出现 | 客户端使用流式读取；代理层关闭响应缓冲，适当配置读取超时 |

基础用户、角色和文章功能不需要 AI 密钥。普通聊天不要求配置 embedding 模型；知识库向量化和检索则需要有效的 embedding 配置。测试中的 SQLite 与模型模拟不能代替真实 PostgreSQL、Redis 及模型服务的集成验证。
