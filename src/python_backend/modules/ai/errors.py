"""可在 HTTP 和 SSE 边界复用的业务错误。"""


class AIError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code
