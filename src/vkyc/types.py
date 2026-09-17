from typing import Any, Callable, Protocol, TypedDict

Event = dict[str, Any]


class Context(Protocol):
    request_id: str


class GatewayResponse(TypedDict):
    """Ответ в формате API Gateway HTTP API."""
    statusCode: int
    headers: dict[str, str]
    body: str


Handler = Callable[[Event, Context], GatewayResponse]
