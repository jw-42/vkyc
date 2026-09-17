"""Общие типы для сигнатур хендлеров Cloud Functions."""

from typing import Any, Callable, Protocol

Event = dict[str, Any]


class Context(Protocol):
    request_id: str


Handler = Callable[[Event, Context], dict[str, Any]]
