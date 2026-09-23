import json
from decimal import Decimal

from vkyc.errors import BadRequestError, InternalError
from vkyc.http import error_response, find_header, get_client_ip, get_user_agent, handle_errors, response


def test_response_shape_and_decimal_encoding():
    result = response(200, {"count": Decimal("3"), "ratio": Decimal("1.5")})
    assert result["statusCode"] == 200
    assert result["headers"]["Content-Type"] == "application/json"
    body = json.loads(result["body"])
    assert body == {"count": 3, "ratio": 1.5}


def test_response_defaults_to_empty_body():
    assert json.loads(response(204)["body"]) == {}


def test_error_response_shape():
    result = error_response(BadRequestError("плохой запрос"))
    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert body == {"error": {"code": "bad_request", "message": "плохой запрос"}}


def test_get_client_ip_prefers_source_ip():
    event = {
        "requestContext": {"http": {"sourceIp": "1.2.3.4"}},
        "headers": {"x-forwarded-for": "9.9.9.9"},
    }
    assert get_client_ip(event) == "1.2.3.4"


def test_get_client_ip_falls_back_to_forwarded_for():
    event = {"headers": {"x-forwarded-for": "9.9.9.9, 8.8.8.8"}}
    assert get_client_ip(event) == "9.9.9.9"


def test_get_client_ip_unknown():
    assert get_client_ip({}) == "unknown"


# Реальная форма события API Gateway с payload_format_version 0.1 (дефолт):
# заголовки в оригинальном регистре, IP/UA — в requestContext.identity.
EVENT_0_1 = {
    "requestContext": {
        "http": {"method": "POST"},
        "identity": {"sourceIp": "147.234.69.205", "userAgent": "Mozilla/5.0 Firefox/154.0"},
    },
    "headers": {"User-Agent": "Mozilla/5.0 Firefox/154.0", "X-Forwarded-For": "147.234.69.205"},
}


def test_get_client_ip_payload_0_1_identity():
    assert get_client_ip(EVENT_0_1) == "147.234.69.205"


def test_get_client_ip_identity_beats_spoofed_forwarded_for():
    event = {**EVENT_0_1, "headers": {"X-Forwarded-For": "6.6.6.6, 147.234.69.205"}}
    assert get_client_ip(event) == "147.234.69.205"


def test_get_client_ip_forwarded_for_case_insensitive():
    assert get_client_ip({"headers": {"X-Forwarded-For": "9.9.9.9, 8.8.8.8"}}) == "9.9.9.9"


def test_get_user_agent_prefers_identity():
    assert get_user_agent(EVENT_0_1) == "Mozilla/5.0 Firefox/154.0"


def test_get_user_agent_falls_back_to_header_any_case():
    assert get_user_agent({"headers": {"User-Agent": "UA-1"}}) == "UA-1"
    assert get_user_agent({"headers": {"user-agent": "UA-2"}}) == "UA-2"


def test_get_user_agent_unknown():
    assert get_user_agent({}) == "unknown"
    assert get_user_agent({"headers": None, "requestContext": {}}) == "unknown"


def test_find_header_missing_or_empty():
    assert find_header({"headers": {"X-A": ""}}, "x-a") == ""
    assert find_header({}, "x-a") == ""


def test_handle_errors_passthrough():
    @handle_errors
    def handler(event, context):
        return response(200, {"ok": True})

    result = handler({}, None)
    assert result["statusCode"] == 200


def test_handle_errors_converts_api_error():
    @handle_errors
    def handler(event, context):
        raise BadRequestError("плохо")

    result = handler({}, None)
    assert result["statusCode"] == 400


def test_handle_errors_converts_unhandled_exception():
    @handle_errors
    def handler(event, context):
        raise ValueError("boom")

    result = handler({}, None)
    assert result["statusCode"] == 500
    assert json.loads(result["body"])["error"]["code"] == InternalError.error_code


def test_handle_errors_normalizes_yandex_event_shape():
    seen = {}

    @handle_errors
    def handler(event, context):
        seen["pathParameters"] = event["pathParameters"]
        seen["method"] = event["requestContext"]["http"]["method"]
        return response(200)

    handler({"pathParams": {"id": "1"}, "httpMethod": "POST"}, None)
    assert seen == {"pathParameters": {"id": "1"}, "method": "POST"}
