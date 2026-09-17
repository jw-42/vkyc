from typing import Any, NotRequired, TypedDict


class PutSpec(TypedDict):
    TableName: str
    Item: dict[str, Any]
    ConditionExpression: NotRequired[str]
    ExpressionAttributeNames: NotRequired[dict[str, str]]
    ExpressionAttributeValues: NotRequired[dict[str, Any]]


class UpdateSpec(TypedDict):
    TableName: str
    Key: dict[str, Any]
    UpdateExpression: str
    ConditionExpression: NotRequired[str]
    ExpressionAttributeNames: NotRequired[dict[str, str]]
    ExpressionAttributeValues: NotRequired[dict[str, Any]]


class DeleteSpec(TypedDict):
    TableName: str
    Key: dict[str, Any]
    ConditionExpression: NotRequired[str]
    ExpressionAttributeNames: NotRequired[dict[str, str]]
    ExpressionAttributeValues: NotRequired[dict[str, Any]]


class ConditionCheckSpec(TypedDict):
    TableName: str
    Key: dict[str, Any]
    ConditionExpression: str
    ExpressionAttributeNames: NotRequired[dict[str, str]]
    ExpressionAttributeValues: NotRequired[dict[str, Any]]


class PutOp(TypedDict):
    Put: PutSpec


class UpdateOp(TypedDict):
    Update: UpdateSpec


class DeleteOp(TypedDict):
    Delete: DeleteSpec


class ConditionCheckOp(TypedDict):
    ConditionCheck: ConditionCheckSpec


TransactOp = PutOp | UpdateOp | DeleteOp | ConditionCheckOp
