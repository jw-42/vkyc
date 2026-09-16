import json

import vkyc.queue as queue


class FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, QueueUrl, MessageBody):
        self.calls.append((QueueUrl, MessageBody))


def test_enqueue_sends_envelope(monkeypatch):
    fake = FakeSqs()
    monkeypatch.setattr(queue, "sqs", fake)

    queue.enqueue("https://queue/one", "some_event", {"a": 1})

    assert len(fake.calls) == 1
    url, body = fake.calls[0]
    assert url == "https://queue/one"
    assert json.loads(body) == {"type": "some_event", "payload": {"a": 1}}


def test_send_message_uses_processing_queue_url(monkeypatch):
    fake = FakeSqs()
    monkeypatch.setattr(queue, "sqs", fake)
    monkeypatch.setenv("PROCESSING_QUEUE_URL", "https://queue/fast")

    queue.send_message("event", {})

    assert fake.calls[0][0] == "https://queue/fast"


def test_send_bulk_message_uses_bulk_queue_url(monkeypatch):
    fake = FakeSqs()
    monkeypatch.setattr(queue, "sqs", fake)
    monkeypatch.setenv("BULK_QUEUE_URL", "https://queue/slow")

    queue.send_bulk_message("event", {})

    assert fake.calls[0][0] == "https://queue/slow"
