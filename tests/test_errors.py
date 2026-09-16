from vkyc.errors import (
    ApiError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    InternalError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)


def test_default_message_is_class_name():
    assert ApiError().message == "ApiError"
    assert BadRequestError().message == "BadRequestError"


def test_custom_message_kept():
    assert ApiError("что-то пошло не так").message == "что-то пошло не так"


def test_status_and_error_codes():
    cases = [
        (BadRequestError, 400, "bad_request"),
        (UnauthorizedError, 401, "unauthorized"),
        (ForbiddenError, 403, "forbidden"),
        (NotFoundError, 404, "not_found"),
        (ConflictError, 409, "conflict"),
        (TooManyRequestsError, 429, "too_many_requests"),
        (InternalError, 500, "internal_error"),
    ]
    for cls, status, code in cases:
        err = cls()
        assert err.status_code == status
        assert err.error_code == code
