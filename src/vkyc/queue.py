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
    """Кладёт сообщение в быструю очередь (где важна минимальная задержка)."""
    enqueue(os.environ["PROCESSING_QUEUE_URL"], message_type, payload)


def send_bulk_message(message_type: str, payload: dict) -> None:
    """Кладёт сообщение в медленную очередь (тяжёлые задачи, не важна задержка)."""
    enqueue(os.environ["BULK_QUEUE_URL"], message_type, payload)
