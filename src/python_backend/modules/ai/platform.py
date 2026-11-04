"""当前登录用户的平台只读查询；身份由服务端提供，不接受模型指定用户。"""

from sqlalchemy import func, select

from python_backend.modules.ai.errors import AIError
from python_backend.modules.articles.models import Article
from python_backend.modules.roles.models import Role, UserRole
from python_backend.modules.users.models import User

PLATFORM_TOOL = {
    "type": "function",
    "function": {
        "name": "get_my_platform_info",
        "description": (
            "查询当前登录用户在本平台的文章总数、文章标题、角色或用户名。"
            "涉及这些问题必须调用，不能猜测。文章包含草稿和已发布文章。"
            "标题分页，每页最多100条。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["articles", "roles", "profile", "all"]},
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "文章标题分页偏移，默认0",
                },
            },
            "required": ["scope"],
            "additionalProperties": False,
        },
    },
}


def query_platform(session, user_id, arguments):
    if (
        not isinstance(arguments, dict)
        or set(arguments) - {"scope", "offset"}
        or arguments.get("scope") not in ("articles", "roles", "profile", "all")
        or type(arguments.get("offset", 0)) is not int
        or not 0 <= arguments.get("offset", 0) <= 1000000
    ):
        raise AIError("平台查询工具参数无效", 502)
    result = {}
    if arguments["scope"] in ("articles", "all"):
        offset = arguments.get("offset", 0)
        total = session.scalar(
            select(func.count()).select_from(Article).where(Article.user_id == user_id)
        )
        rows = session.execute(
            select(Article.title, Article.status)
            .where(Article.user_id == user_id)
            .order_by(Article.created_at.desc(), Article.id)
            .offset(offset)
            .limit(100)
        ).all()
        result["articles"] = {
            "total": total,
            "includesDrafts": True,
            "items": [{"title": r.title, "status": r.status} for r in rows],
            "nextOffset": offset + len(rows) if offset + len(rows) < total else None,
        }
    if arguments["scope"] in ("roles", "all"):
        rows = session.scalars(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.id)
        )
        result["roles"] = [{"id": r.id, "name": r.name, "label": r.name_cn} for r in rows]
    if arguments["scope"] in ("profile", "all"):
        row = session.execute(select(User.username, User.name).where(User.id == user_id)).first()
        if row is None:
            raise AIError("当前账户不存在", 404)
        result["profile"] = {"username": row.username, "displayName": row.name}
    return result
