"""全局错误协议：HTTP 状态码保持原义，响应统一为 code / message。"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    """供接口文档和前端共同使用的错误结构。"""

    code: int
    message: str


def error_response(code: int, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=code, content={"code": code, "message": message}, headers=headers
    )


def validation_message(error: dict) -> str:
    """只转换错误类型和字段名，不把 input、密码或异常上下文回传前端。"""
    field = str(error["loc"][-1]) if error["loc"] else "请求参数"
    label = {"username": "用户名", "email": "邮箱", "password": "密码"}.get(field, "请求参数")
    kind = error["type"]
    if kind == "json_invalid":
        return "请求体不是有效的 JSON"
    if kind == "extra_forbidden":
        return "请求包含不支持的字段"
    if kind == "missing":
        return f"{label}不能为空"
    if field == "username":
        return "用户名需为 3–32 位字母、数字或下划线"
    if field == "email":
        return "请输入有效邮箱"
    if field == "password" and error.get("ctx", {}).get("min_length") == 1:
        return "密码长度为 1–128 位"
    if field == "password" and error.get("ctx", {}).get("max_length") == 128:
        return "密码长度不能超过 128 位"
    if field == "password":
        return "密码需为 8–128 字符，且包含英文字母和数字"
    return "请求参数不合法"


def register_error_handlers(app: FastAPI) -> None:
    # 捕获 Starlette HTTPException，才能同时处理框架产生的 404 / 405。
    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, error: HTTPException) -> JSONResponse:
        defaults = {404: "接口不存在", 405: "请求方法不支持"}
        message = defaults.get(error.status_code, "请求失败")
        if error.status_code >= 500:
            message = "服务器内部错误，请稍后重试"
        elif error.status_code not in defaults and isinstance(error.detail, str):
            message = error.detail
        # 保留认证、限流等异常携带的响应头。
        return error_response(error.status_code, message, error.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # 一次展示第一条校验错误，前端可以直接显示 message。
        errors = error.errors()
        message = validation_message(errors[0]) if errors else "请求参数不合法"
        return error_response(422, message)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        # 不记录请求体和异常原文，数据库异常可能附带 SQL 参数或密码哈希。
        logger.error(
            "Unhandled %s on %s %s", type(error).__name__, request.method, request.url.path
        )
        return error_response(500, "服务器内部错误，请稍后重试")
