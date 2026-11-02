def main() -> None:
    """供 uv run python-backend 启动服务。"""
    import uvicorn

    uvicorn.run("python_backend.main:app", host="127.0.0.1", port=8000)
