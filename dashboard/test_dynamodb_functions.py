# pylint: skip-file

from unittest.mock import Mock

from botocore.exceptions import ClientError

import dynamodb_functions
from dynamodb_functions import subscribe_user, get_subscribers, unsubscribe_user


def make_client_error(message="Something went wrong", operation_name="Operation"):
    return ClientError(
        error_response={"Error": {"Message": message}},
        operation_name=operation_name,
    )


def test_subscribe_user_success(monkeypatch):
    mock_table = Mock()
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = subscribe_user("Newham", "user@example.com")

    assert result["success"] is True
    assert "user@example.com" in result["message"]
    assert "Newham" in result["message"]

    mock_table.put_item.assert_called_once()
    put_kwargs = mock_table.put_item.call_args.kwargs
    assert put_kwargs["Item"]["email"] == "user@example.com"
    assert put_kwargs["Item"]["area"] == "Newham"
    assert put_kwargs["Item"]["active"] is True


def test_subscribe_user_client_error(monkeypatch):
    mock_table = Mock()
    mock_table.put_item.side_effect = make_client_error("Table not found")
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = subscribe_user("Newham", "user@example.com")

    assert result["success"] is False
    assert "Table not found" in result["message"]


def test_subscribe_user_unexpected_error(monkeypatch):
    mock_table = Mock()
    mock_table.put_item.side_effect = ValueError("boom")
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = subscribe_user("Newham", "user@example.com")

    assert result["success"] is False
    assert "boom" in result["message"]


def test_get_subscribers_with_area_filter(monkeypatch):
    expected_items = [{"email": "a@example.com",
                       "area": "Newham", "active": True}]
    mock_table = Mock()
    mock_table.scan.return_value = {"Items": expected_items}
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = get_subscribers(area="Newham")

    assert result == expected_items
    scan_kwargs = mock_table.scan.call_args.kwargs
    assert scan_kwargs["ExpressionAttributeValues"][":area"] == "Newham"
    assert scan_kwargs["ExpressionAttributeValues"][":active"] is True


def test_get_subscribers_without_area_filter(monkeypatch):
    expected_items = [{"email": "a@example.com", "active": True}]
    mock_table = Mock()
    mock_table.scan.return_value = {"Items": expected_items}
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = get_subscribers()

    assert result == expected_items
    scan_kwargs = mock_table.scan.call_args.kwargs
    assert ":area" not in scan_kwargs["ExpressionAttributeValues"]


def test_get_subscribers_missing_items_returns_empty_list(monkeypatch):
    mock_table = Mock()
    mock_table.scan.return_value = {}
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = get_subscribers()

    assert result == []


def test_get_subscribers_client_error_returns_empty_list(monkeypatch):
    mock_table = Mock()
    mock_table.scan.side_effect = make_client_error("Access denied")
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = get_subscribers(area="Newham")

    assert result == []


def test_get_subscribers_unexpected_error_returns_empty_list(monkeypatch):
    mock_table = Mock()
    mock_table.scan.side_effect = ValueError("boom")
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = get_subscribers()

    assert result == []


def test_unsubscribe_user_success(monkeypatch):
    mock_table = Mock()
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = unsubscribe_user("user@example.com")

    assert result["success"] is True
    assert "user@example.com" in result["message"]

    mock_table.update_item.assert_called_once()
    update_kwargs = mock_table.update_item.call_args.kwargs
    assert update_kwargs["Key"] == {"email": "user@example.com"}
    assert update_kwargs["ExpressionAttributeValues"][":active"] is False


def test_unsubscribe_user_client_error(monkeypatch):
    mock_table = Mock()
    mock_table.update_item.side_effect = make_client_error("Item not found")
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = unsubscribe_user("user@example.com")

    assert result["success"] is False
    assert "Item not found" in result["message"]


def test_unsubscribe_user_unexpected_error(monkeypatch):
    mock_table = Mock()
    mock_table.update_item.side_effect = ValueError("boom")
    mock_dynamodb = Mock()
    mock_dynamodb.Table.return_value = mock_table
    monkeypatch.setattr(dynamodb_functions, "dynamodb", mock_dynamodb)

    result = unsubscribe_user("user@example.com")

    assert result["success"] is False
    assert "boom" in result["message"]
