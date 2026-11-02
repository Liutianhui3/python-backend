from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型共用的基类，用于收集表结构定义。"""
