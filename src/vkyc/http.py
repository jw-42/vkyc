"""
Единый формат ответа для HTTP-эндпоинтов за Yandex API Gateway (HTTP API,
payload format 2.0).

Цель: handler конкретной функции не формирует JSON и статус-коды руками,
а пользуется response()/error_response() — это гарантирует одинаковую
структуру ответов и заголовков по всему API.
"""

import json
from decimal import Decimal
from typing import Any

from vkyc.errors import ApiError, InternalError
from vkyc.logger import get_logger

log = get_logger(__name__)

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
}


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def response(status_code: int, body: dict[str, Any] | list[Any] | None = None) -> dict[str, Any]:
    """Формирует ответ в формате, который ожидает API Gateway HTTP API."""
    return {
        "statusCode": status_code,
        "headers": DEFAULT_HEADERS,
        "body": json.dumps(
            body if body is not None else {},
            ensure_ascii=False,
            sort_keys=True,
            cls=JSONEncoder,
        ),
    }


def get_client_ip(event: dict) -> str:
    """
    IP клиента запроса. Приоритет — sourceIp от API Gateway: заголовок
    X-Forwarded-For клиент может подделать, поэтому он лишь fallback, когда
    шлюз sourceIp не проставил.
    """
    ctx = event.get("requestContext", {})
    source_ip = ctx.get("http", {}).get("sourceIp")
    if source_ip:
        return source_ip
    headers = event.get("headers") or {}
    forwarded_for = headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return "unknown"


def error_response(error: ApiError) -> dict[str, Any]:
    """Превращает доменное исключение в стандартный ответ-ошибку."""
    return response(
        error.status_code,
        {"error": {"code": error.error_code, "message": error.message}},
    )


def handle_errors(handler):
    """
    Декоратор для handler'ов HTTP-эндпоинтов (Cloud Functions).

    Перехватывает ApiError и превращает в корректный HTTP-ответ.
    Любое необработанное исключение логируется и превращается в 500,
    чтобы наружу никогда не утекали внутренние детали (stack trace, имена таблиц и т.п.).

        @handle_errors
        def handler(event, context):
            ...
            raise NotFoundError("форма не найдена")
    """

    def wrapper(event, context):
        # Yandex API Gateway uses 'pathParams'; normalize to 'pathParameters' (AWS convention)
        if event.get("pathParams") and not event.get("pathParameters"):
            event["pathParameters"] = event["pathParams"]
        # Yandex API Gateway puts HTTP method in 'httpMethod'; normalize to AWS format
        if event.get("httpMethod") and not event.get("requestContext", {}).get("http", {}).get("method"):
            event.setdefault("requestContext", {}).setdefault("http", {})["method"] = event["httpMethod"]
        try:
            return handler(event, context)
        except ApiError as exc:
            log.warning(
                "обработанная ошибка API: %s",
                exc.message,
                extra={"error_code": exc.error_code, "status_code": exc.status_code},
            )
            return error_response(exc)
        except Exception:
            log.exception("необработанная ошибка в handler'е")
            return error_response(InternalError("внутренняя ошибка сервера"))

    return wrapper
