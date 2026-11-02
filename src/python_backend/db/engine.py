from sqlalchemy import URL, create_engine

from python_backend.core.config import settings

# 分别传入连接参数，不手工拼接 URL，密码中的 @、/ 等字符也能正确处理。
database_url = URL.create(
    drivername="postgresql+psycopg",
    host=settings.db_host,
    port=settings.db_port,
    database=settings.db_name,
    username=settings.db_user,
    password=settings.db_password.get_secret_value(),
)

# Engine 管理连接池；调用 connect() 或实际执行查询时才连接数据库。
engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
)
