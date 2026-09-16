"""
Платформенные примитивы поверх YDB Document API (DynamoDB-совместимый,
boto3): настройка клиентов, атомарные многотабличные транзакции, курсорная
пагинация. Конкретные таблицы и бизнес-CRUD — забота приложения, не этой
библиотеки.
"""

import base64
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.config import Config
from botocore.exceptions import ClientError

from vkyc.errors import BadRequestError
from vkyc.logger import get_logger

log = get_logger(__name__)

# read_timeout/connect_timeout заведомо меньше самого короткого execution
# timeout среди функций, использующих этот клиент, и ограниченное число
# ретраев — чтобы один медленный/законтенченный вызов к YDB отваливался
# быстро и предсказуемо, а не съедал весь таймаут функции.
dynamodb = boto3.resource(
    "dynamodb",
    endpoint_url=os.environ.get("DOCAPI_ENDPOINT"),
    region_name="ru-central1",
    config=Config(
        read_timeout=5,
        connect_timeout=5,
        retries={"max_attempts": 2, "mode": "standard"},
    ),
)

# Отдельный low-level client — НЕ dynamodb.meta.client. Resource навешивает на
# свой клиент авто-сериализацию параметров для высокоуровневого Table API;
# если через тот же клиент вызвать transact_write_items с уже сериализованными
# через TypeSerializer Item/Key (как ниже), значения оборачиваются повторно
# (строка становится вложенной картой) и запрос падает с generic
# ValidationException. С отдельным клиентом транзакции (в т.ч. с
# ConditionExpression) отрабатывают штатно.
transact_client = boto3.client(
    "dynamodb",
    endpoint_url=os.environ.get("DOCAPI_ENDPOINT"),
    region_name="ru-central1",
)

serializer = TypeSerializer()


def get_table(env_var: str):
    """Таблица по имени переменной окружения, хранящей её физическое имя."""
    return dynamodb.Table(os.environ[env_var])


def transact_write(operations: list[dict]) -> None:
    """
    Атомарно выполняет до 25 Put/Update/Delete/ConditionCheck операций в
    разных таблицах (TransactWriteItems). Каждая операция — словарь вида
    {"Put": {...}} с обычными Python-типами в Item/Key/ExpressionAttributeValues;
    сериализация в формат DynamoDB происходит здесь.
    """
    serialized = []
    for op in operations:
        kind, spec = next(iter(op.items()))
        spec = dict(spec)
        if "Item" in spec:
            spec["Item"] = {k: serializer.serialize(v) for k, v in spec["Item"].items()}
        if "Key" in spec:
            spec["Key"] = {k: serializer.serialize(v) for k, v in spec["Key"].items()}
        if "ExpressionAttributeValues" in spec:
            spec["ExpressionAttributeValues"] = {
                k: serializer.serialize(v) for k, v in spec["ExpressionAttributeValues"].items()
            }
        serialized.append({kind: spec})

    try:
        transact_client.transact_write_items(TransactItems=serialized)
    except ClientError as e:
        log.error(
            "transact_write_items упал: %s, cancellation_reasons=%s",
            e.response.get("Error"), e.response.get("CancellationReasons"),
        )
        raise


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def convert_decimals(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_decimals(v) for v in obj]
    return obj


def from_dynamo(item: dict, internal_fields: frozenset[str] = frozenset()) -> dict:
    """Убирает служебные поля (если приложение их объявило) и конвертирует
    Decimal в числа Python."""
    clean = {k: v for k, v in item.items() if k not in internal_fields}
    return convert_decimals(clean)


def encode_cursor(key: dict) -> str:
    return base64.b64encode(json.dumps(key).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.b64decode(cursor.encode()).decode())
    except Exception:
        raise BadRequestError("некорректный cursor")


def query_page(
    table,
    kwargs: dict,
    limit: int,
    cursor: Optional[str],
    cursor_key_fields: tuple[str, ...],
) -> tuple[list, Optional[str]]:
    """
    Страница query с честной пагинацией при FilterExpression. Limit в
    Document API ограничивает число ПРОСМОТРЕННЫХ строк до применения
    фильтра, поэтому прямолинейный query(Limit=limit) возвращает "худеющие"
    страницы — вплоть до пустых с непустым next_cursor, на которых клиент
    решил бы, что данные закончились. Здесь внутренние страницы дочитываются,
    пока не наберётся limit прошедших фильтр элементов или не кончится
    выборка.

    При остановке посреди внутренней страницы next_cursor строится из
    ключевых полей последнего ОТДАННОГО элемента (cursor_key_fields: ключи
    таблицы + ключи индекса — ровно тот набор, который Document API кладёт в
    LastEvaluatedKey; ExclusiveStartKey не обязан быть настоящим
    LastEvaluatedKey) — LastEvaluatedKey внутренней страницы указывает на
    последний просмотренный элемент, и всё отданное после него терялось бы.
    """
    if cursor:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
    # Без фильтра каждая просмотренная строка попадает в выдачу — внутренняя
    # страница равна запрошенной. С фильтром отфильтрованные строки "съедают"
    # Limit, поэтому берём страницу с запасом, чтобы не ходить в БД на каждые
    # несколько строк.
    kwargs["Limit"] = max(limit * 3, 30) if "FilterExpression" in kwargs else limit

    items: list = []
    while True:
        resp = table.query(**kwargs)
        page = resp.get("Items", [])
        for idx, raw in enumerate(page):
            items.append(from_dynamo(raw))
            if len(items) < limit:
                continue
            if idx + 1 < len(page):
                return items, encode_cursor({k: raw[k] for k in cursor_key_fields})
            if "LastEvaluatedKey" in resp:
                return items, encode_cursor(resp["LastEvaluatedKey"])
            return items, None
        if "LastEvaluatedKey" not in resp:
            return items, None
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
