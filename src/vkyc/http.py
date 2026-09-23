import json
from decimal import Decimal
from typing import Any, Mapping

from vkyc.errors import ApiError, InternalError
from vkyc.errors.types import ErrorEnvelope
from vkyc.logger import get_logger
from vkyc.types import Context, Event, GatewayResponse, Handler

log = get_logger(__name__)

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
}


class JSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def response(status_code: int, body: Mapping[str, Any] | list[Any] | None = None) -> GatewayResponse:
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


UNKNOWN = "unknown"


def find_header(event: Event, name: str) -> str:
    """Значение заголовка без учёта регистра имени; пустая строка, если его нет."""
    wanted = name.lower()
    for key, value in (event.get("headers") or {}).items():
        if isinstance(key, str) and key.lower() == wanted and value:
            return str(value)
    return ""


def get_client_ip(event: Event) -> str:
    """
    Возвращает IP клиента запроса.

    Приоритет — sourceIp, проставленный API Gateway: `requestContext.identity`
    (payload_format_version 0.1, дефолт) или `requestContext.http` (2.0).
    X-Forwarded-For клиент может дополнить сам, поэтому он используется только
    как fallback, если шлюз sourceIp не передал. Заголовки в формате 0.1
    приходят в оригинальном регистре (`X-Forwarded-For`), поэтому ищутся без
    учёта регистра.
    """
    ctx = event.get("requestContext") or {}
    source_ip = (ctx.get("identity") or {}).get("sourceIp") or (ctx.get("http") or {}).get("sourceIp")
    if source_ip:
        return str(source_ip)
    forwarded_for = find_header(event, "X-Forwarded-For")
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return UNKNOWN


def get_user_agent(event: Event) -> str:
    """Возвращает User-Agent клиента: `identity.userAgent` шлюза, затем заголовок User-Agent."""
    ctx = event.get("requestContext") or {}
    user_agent = (ctx.get("identity") or {}).get("userAgent") or find_header(event, "User-Agent")
    return str(user_agent) if user_agent else UNKNOWN


def error_response(error: ApiError) -> GatewayResponse:
    """Превращает доменное исключение в стандартный ответ-ошибку."""
    body: ErrorEnvelope = {"error": {"code": error.error_code, "message": error.message}}
    return response(error.status_code, body)


def handle_errors(handler: Handler) -> Handler:
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
    def wrapper(event: Event, context: Context) -> GatewayResponse:
        if event.get("pathParams") and not event.get("pathParameters"):
            event["pathParameters"] = event["pathParams"]

        if event.get("httpMethod") and not event.get("requestContext", {}).get("http", {}).get("method"):
            event.setdefault("requestContext", {}).setdefault("http", {})["method"] = event["httpMethod"]

        try:
            return handler(event, context)
        except ApiError as exc:
            log.warning(
                "Обработанная ошибка API: %s",
                exc.message,
                extra={"error_code": exc.error_code, "status_code": exc.status_code},
            )
            return error_response(exc)
        except Exception:
            log.exception("Необработанная ошибка в handler'е")
            return error_response(InternalError("Внутренняя ошибка сервера."))

    return wrapper
