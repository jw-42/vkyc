"""
Единая настройка логирования для Cloud Functions.

Использует стандартный logging, но гарантирует:
  - JSON-совместимый формат (удобно парсить в Cloud Logging): фиксированные
    ключи level / message / logger, плюс exception при record.exc_info, плюс
    любые поля, переданные через extra= в вызов лога (в т.ч. request_id из
    контекста функции),
  - request_id из контекста функции попадает в каждую запись лога,
  - уровень логирования регулируется переменной окружения LOG_LEVEL (по
    умолчанию INFO — DEBUG в проде не включаем без необходимости, иначе
    Cloud Logging становится неожиданно дорогой статьёй расходов).
"""

import json
import logging
import os
from typing import Any

# Стандартные атрибуты LogRecord — их в JSON-payload не тащим, туда идут
# только пользовательские поля из extra=.
RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key in RESERVED or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ContextAdapter(logging.LoggerAdapter):
    """
    LoggerAdapter, который СЛИВАЕТ call-site extra со своим контекстом.

    Штатный logging.LoggerAdapter в Python 3.12 затирает call-site extra
    адаптеровым (kwargs["extra"] = self.extra), из-за чего
    log.warning("...", extra={"form_id": x}) терял бы form_id.
    """

    def process(self, msg, kwargs):
        kwargs["extra"] = {**self.extra, **(kwargs.get("extra") or {})}
        return msg, kwargs


def get_logger(name: str) -> logging.Logger:
    """
    Возвращает настроенный логгер. Вызывать один раз на модуль:

        from vkyc.logger import get_logger
        log = get_logger(__name__)
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
        logger.propagate = False

    return logger


def with_request_id(logger: logging.Logger, request_id: str) -> logging.LoggerAdapter:
    """
    Добавляет request_id ко всем последующим записям лога в рамках одного вызова handler'а.

        log = with_request_id(get_logger(__name__), context.request_id)
        log.info("обработка запроса начата")
    """
    return ContextAdapter(logger, {"request_id": request_id})
