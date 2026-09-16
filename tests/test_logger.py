import json
import logging

from vkyc.logger import JsonFormatter, get_logger, with_request_id


def make_record(msg="hello", extra=None):
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in (extra or {}).items():
        setattr(record, k, v)
    return record


def test_json_formatter_basic_fields():
    payload = json.loads(JsonFormatter().format(make_record("hi")))
    assert payload["level"] == "INFO"
    assert payload["message"] == "hi"
    assert payload["logger"] == "test"


def test_json_formatter_includes_extra():
    payload = json.loads(JsonFormatter().format(make_record(extra={"form_id": "f1"})))
    assert payload["form_id"] == "f1"


def test_json_formatter_survives_non_serializable_extra():
    class Weird:
        def __str__(self):
            return "weird-value"

    payload = json.loads(JsonFormatter().format(make_record(extra={"obj": Weird()})))
    assert payload["obj"] == "weird-value"


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failed", args=(), exc_info=__import__("sys").exc_info(),
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "boom" in payload["exception"]


def test_get_logger_installs_one_handler():
    logger = get_logger("vkyc.test.singleton")
    assert len(logger.handlers) == 1
    again = get_logger("vkyc.test.singleton")
    assert len(again.handlers) == 1


def test_with_request_id_merges_call_site_extra(caplog):
    logger = get_logger("vkyc.test.ctx")
    adapter = with_request_id(logger, "req-1")
    msg, kwargs = adapter.process("msg", {"extra": {"form_id": "f1"}})
    assert kwargs["extra"] == {"request_id": "req-1", "form_id": "f1"}
