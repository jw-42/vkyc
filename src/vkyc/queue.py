"""
Отправка сообщений в Yandex Message Queue (SQS-совместимый API).

Рассчитан на паттерн, где HTTP-обработчик переносит тяжёлую или подверженную
всплескам запись в фоновую обработку через отдельного консьюмера: продюсер
кладёт конверт {"type": message_type, "payload": payload} в очередь, консьюмер
разбирает "type", чтобы выбрать обработчик.

Две функции соответствуют двум типовым профилям очереди — быстрой (короткие
идемпотентные задачи, важна задержка) и медленной (длинные пакетные задачи,
важна пропускная способность, не задержка), каждая читает свой URL из
окружения. Можно использовать только одну из них, если второй профиль не нужен.
"""

import json
import os

import boto3

sqs = boto3.client(
    "sqs",
    endpoint_url=os.environ.get("YMQ_ENDPOINT"),
    region_name="ru-central1",
)


def enqueue(queue_url: str, message_type: str, payload: dict) -> None:
    body = json.dumps({"type": message_type, "payload": payload}, ensure_ascii=False)
    sqs.send_message(QueueUrl=queue_url, MessageBody=body)


def send_message(message_type: str, payload: dict) -> None:
    """Кладёт конверт в "быструю" очередь (PROCESSING_QUEUE_URL)."""
    enqueue(os.environ["PROCESSING_QUEUE_URL"], message_type, payload)


def send_bulk_message(message_type: str, payload: dict) -> None:
    """Кладёт конверт в "медленную" очередь (BULK_QUEUE_URL) — для длинных
    пакетных задач, которые не должны блокировать голову быстрой очереди."""
    enqueue(os.environ["BULK_QUEUE_URL"], message_type, payload)
