from fastapi import FastAPI

from python_backend.api.router import api_router
from python_backend.core.config import settings
from python_backend.core.errors import ErrorResponse, register_error_handlers

app = FastAPI(
    title=settings.app_name,
    responses={code: {"model": ErrorResponse} for code in (404, 405, 409, 422, 500)},
)
register_error_handlers(app)
app.include_router(api_router)
