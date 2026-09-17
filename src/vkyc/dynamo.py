from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.config import Config
from botocore.exceptions import ClientError

from vkyc.dynamo_types import TransactOp
from vkyc.errors import BadRequestError
from vkyc.logger import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table
    from mypy_boto3_dynamodb.type_defs import QueryInputTableQueryTypeDef

log = get_logger(__name__)

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

transact_client = boto3.client(
    "dynamodb",
    endpoint_url=os.environ.get("DOCAPI_ENDPOINT"),
    region_name="ru-central1",
)

serializer = TypeSerializer()


def get_table(env_var: str) -> Table:
    """Получает таблицу по имени переменной окружения."""
    return dynamodb.Table(os.environ[env_var])


def transact_write(operations: list[TransactOp]) -> None:
    """Атомарно выполняет до 25 операций (Put/Update/Delete/ConditionCheck) в разных таблицах."""
    serialized = []
    for op in operations:
        # Каждый TransactOp — TypedDict ровно с одним ключом (Put/Update/Delete/
        # ConditionCheck) — какой именно, статически неизвестно до чтения самого
        # значения, поэтому дальше работаем с ним как с обычным dict.
        kind, spec = next(iter(cast(dict[str, Any], op).items()))
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
        transact_client.transact_write_items(TransactItems=cast(Any, serialized))
    except ClientError as e:
        log.error(
            "transact_write_items error=%s, cancellation_reasons=%s",
            e.response.get("Error"), e.response.get("CancellationReasons"),
        )
        raise


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def convert_decimals(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_decimals(v) for v in obj]
    return obj


def from_dynamo(item: dict[str, Any], internal_fields: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Убирает служебные поля (если объявлены) и конвертирует Decimal в числа Python."""
    clean = {k: v for k, v in item.items() if k not in internal_fields}
    return cast(dict[str, Any], convert_decimals(clean))


def encode_cursor(key: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(key).encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], json.loads(base64.b64decode(cursor.encode()).decode()))
    except Exception:
        raise BadRequestError("Некорректный указатель на страницу.")


def query_page(
    table: Table,
    kwargs: QueryInputTableQueryTypeDef,
    limit: int,
    cursor: str | None,
    cursor_key_fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], str | None]:
    """Страница запроса с честной пагинацией при использовании фильтра."""
    if cursor:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor)

    kwargs["Limit"] = max(limit * 3, 30) if "FilterExpression" in kwargs else limit

    items: list[dict[str, Any]] = []
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
