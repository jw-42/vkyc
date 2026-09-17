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


def get_table(env_var: str):
    """Получает таблицу по имени переменной окружения."""
    return dynamodb.Table(os.environ[env_var])


def transact_write(operations: list[dict]) -> None:
    """Атомарно выполняет до 25 операций в разных таблицах."""
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
            "transact_write_items error=%s, cancellation_reasons=%s",
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
    """Убирает служебные поля (если объявлены) и конвертирует Decimal в числа Python."""
    clean = {k: v for k, v in item.items() if k not in internal_fields}
    return convert_decimals(clean)


def encode_cursor(key: dict) -> str:
    return base64.b64encode(json.dumps(key).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.b64decode(cursor.encode()).decode())
    except Exception:
        raise BadRequestError("Некорректный указатель на страницу.")


def query_page(
    table,
    kwargs: dict,
    limit: int,
    cursor: Optional[str],
    cursor_key_fields: tuple[str, ...],
) -> tuple[list, Optional[str]]:
    """Страница запроса с честной пагинацией при использовании фильтра."""
    if cursor:
        kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
        
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
