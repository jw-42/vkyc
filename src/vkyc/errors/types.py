from typing import TypedDict


class ErrorDetail(TypedDict):
    code: str
    message: str


class ErrorEnvelope(TypedDict):
    """Тело ответа при ошибке — см. `vkyc.http.error_response`."""
    error: ErrorDetail
