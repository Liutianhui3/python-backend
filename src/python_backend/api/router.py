"""统一挂载业务模块路由。"""

from fastapi import APIRouter

from python_backend.modules.articles.router import router as articles_router
from python_backend.modules.roles.router import router as roles_router
from python_backend.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(articles_router)
