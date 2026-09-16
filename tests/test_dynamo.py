from decimal import Decimal

import pytest
from botocore.exceptions import ClientError

import vkyc.dynamo as dynamo


def test_convert_decimals_integer_and_float():
    assert dynamo.convert_decimals(Decimal("3")) == 3
    assert dynamo.convert_decimals(Decimal("3")) == 3 and isinstance(dynamo.convert_decimals(Decimal("3")), int)
    assert dynamo.convert_decimals(Decimal("3.5")) == 3.5


def test_convert_decimals_nested():
    value = {"a": [Decimal("1"), {"b": Decimal("2.5")}]}
    assert dynamo.convert_decimals(value) == {"a": [1, {"b": 2.5}]}


def test_from_dynamo_strips_declared_internal_fields():
    item = {"form_id": "1", "doc_key": "internal"}
    assert dynamo.from_dynamo(item, internal_fields=frozenset({"doc_key"})) == {"form_id": "1"}


def test_from_dynamo_keeps_everything_by_default():
    item = {"form_id": "1", "count": Decimal("2")}
    assert dynamo.from_dynamo(item) == {"form_id": "1", "count": 2}


def test_cursor_roundtrip():
    key = {"form_id": "1", "response_id": "2"}
    assert dynamo.decode_cursor(dynamo.encode_cursor(key)) == key


def test_decode_cursor_rejects_garbage():
    from vkyc.errors import BadRequestError
    with pytest.raises(BadRequestError):
        dynamo.decode_cursor("not-base64-json!!")


class FakeTable:
    """Симулирует Document API query(): несколько внутренних страниц,
    последняя страница внутри батча содержит элементы после лимита."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0)


def test_query_page_stops_at_limit_within_one_page():
    table = FakeTable([
        {"Items": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
    ])
    items, cursor = dynamo.query_page(table, {}, limit=2, cursor=None, cursor_key_fields=("id",))
    assert [i["id"] for i in items] == ["1", "2"]
    assert cursor is not None
    assert dynamo.decode_cursor(cursor) == {"id": "2"}


def test_query_page_continues_across_internal_pages():
    table = FakeTable([
        {"Items": [{"id": "1"}], "LastEvaluatedKey": {"id": "1"}},
        {"Items": [{"id": "2"}, {"id": "3"}]},
    ])
    items, cursor = dynamo.query_page(table, {}, limit=3, cursor=None, cursor_key_fields=("id",))
    assert [i["id"] for i in items] == ["1", "2", "3"]
    assert cursor is None


def test_query_page_no_more_data_returns_none_cursor():
    table = FakeTable([{"Items": [{"id": "1"}]}])
    items, cursor = dynamo.query_page(table, {}, limit=10, cursor=None, cursor_key_fields=("id",))
    assert [i["id"] for i in items] == ["1"]
    assert cursor is None


def test_query_page_resumes_from_cursor():
    table = FakeTable([{"Items": [{"id": "2"}]}])
    cursor_in = dynamo.encode_cursor({"id": "1"})
    dynamo.query_page(table, {}, limit=10, cursor=cursor_in, cursor_key_fields=("id",))
    assert table.calls[0]["ExclusiveStartKey"] == {"id": "1"}


class FakeTransactClient:
    def __init__(self, raise_error=False):
        self.raise_error = raise_error
        self.calls = []

    def transact_write_items(self, TransactItems):
        self.calls.append(TransactItems)
        if self.raise_error:
            raise ClientError(
                {"Error": {"Code": "X"}, "CancellationReasons": []}, "TransactWriteItems"
            )


def test_transact_write_serializes_values(monkeypatch):
    fake = FakeTransactClient()
    monkeypatch.setattr(dynamo, "transact_client", fake)

    dynamo.transact_write([{"Put": {"TableName": "forms", "Item": {"form_id": "1"}}}])

    assert fake.calls == [[{"Put": {"TableName": "forms", "Item": {"form_id": {"S": "1"}}}}]]


def test_transact_write_reraises_client_error(monkeypatch):
    fake = FakeTransactClient(raise_error=True)
    monkeypatch.setattr(dynamo, "transact_client", fake)

    with pytest.raises(ClientError):
        dynamo.transact_write([{"Put": {"TableName": "forms", "Item": {"form_id": "1"}}}])


def test_get_table_reads_env_var(monkeypatch):
    calls = []

    class FakeDynamodb:
        def Table(self, name):
            calls.append(name)
            return f"table:{name}"

    monkeypatch.setattr(dynamo, "dynamodb", FakeDynamodb())
    monkeypatch.setenv("FORMS_TABLE_NAME", "prod-forms")

    assert dynamo.get_table("FORMS_TABLE_NAME") == "table:prod-forms"
    assert calls == ["prod-forms"]
