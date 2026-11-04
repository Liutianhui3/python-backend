from alembic import context

from python_backend.db.base import Base
from python_backend.db.engine import database_url, engine
from python_backend.modules.articles.models import Article  # noqa: F401 -- 注册文章表
from python_backend.modules.chat.models import Conversation, Message  # noqa: F401
from python_backend.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument  # noqa: F401
from python_backend.modules.roles.models import Role  # noqa: F401 -- 注册角色表
from python_backend.modules.users.models import User  # noqa: F401 -- 导入后注册用户表

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """只生成 SQL，不连接数据库。"""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """复用项目配置连接数据库，在事务内执行迁移。"""
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
