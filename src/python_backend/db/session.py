"""每个请求使用独立 Session，不在多个请求之间共享事务。"""

from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from python_backend.db.engine import engine

SessionLocal = sessionmaker(bind=engine)


def get_session() -> Generator[Session, None, None]:
    # yield 将会话交给接口，退出 with 时自动关闭；未提交事务会被回滚。
    with SessionLocal() as session:
        yield session
