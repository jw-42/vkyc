"""
Базовые исключения для HTTP-эндпоинтов.

Идея: бизнес-логика поднимает понятное исключение (например, NotFoundError),
а общий обработчик в http.py превращает его в правильный HTTP-ответ с нужным
статус-кодом — handler'у конкретной функции не нужно знать про коды ответов.
"""


class ApiError(Exception):
    """Базовый класс для всех ожидаемых ошибок API. Не использовать напрямую."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message or self.__class__.__name__


class BadRequestError(ApiError):
    status_code = 400
    error_code = "bad_request"


class NotFoundError(ApiError):
    status_code = 404
    error_code = "not_found"


class ConflictError(ApiError):
    status_code = 409
    error_code = "conflict"


class UnauthorizedError(ApiError):
    status_code = 401
    error_code = "unauthorized"


class ForbiddenError(ApiError):
    status_code = 403
    error_code = "forbidden"


class TooManyRequestsError(ApiError):
    status_code = 429
    error_code = "too_many_requests"


class InternalError(ApiError):
    status_code = 500
    error_code = "internal_error"
