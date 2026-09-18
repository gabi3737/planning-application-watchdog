# pylint: skip-file

import pytest
from decimal import Decimal
from unittest.mock import Mock

import pandas as pd

import data_functions
from data_functions import (calculate_distance, get_sites,
                            get_conservation_areas, load_application_data, get_coords)


def test_calculate_distance():
    assert calculate_distance(51.509, -0.128, 51.509, -0.128) == 0

    distance = calculate_distance(51.509, -0.128, 51.507, -0.128)
    assert distance > 0
    assert isinstance(distance, (float))


def test_get_sites_returns_features(monkeypatch):
    expected_features = [{"attributes": {"Name": "Test",
                                         "Grade": "A", "hyperlink": "http://example.com"}}]

    response = Mock()
    response.json.return_value = {"features": expected_features}
    response.raise_for_status = None

    get_mock = Mock(return_value=response)
    monkeypatch.setattr(data_functions.requests, "get", get_mock)

    data_functions.get_sites.clear()

    result = get_sites(
        latitude=53.3811, longitude=-1.4701, radius=200)

    assert result == expected_features
    get_mock.assert_called_once()

    call_kwargs = get_mock.call_args.kwargs
    assert call_kwargs["impersonate"] == "chrome124"
    assert call_kwargs["url"].startswith(
        "https://services-eu1.arcgis.com/"
    )
    assert "geometry=-1.4701,53.3811" in call_kwargs["url"]
    assert "distance=200" in call_kwargs["url"]


def test_get_sites_returns_empty_list_when_no_features(monkeypatch):
    response = Mock()
    response.json.return_value = {"features": []}
    response.raise_for_status.return_value = None

    get_mock = Mock(return_value=response)
    monkeypatch.setattr(data_functions.requests, "get", get_mock)

    data_functions.get_sites.clear()

    result = get_sites(
        latitude=53.3811,
        longitude=-1.4701,
        radius=1000,
    )

    assert result == []


def test_get_sites_returns_empty_list_for_invalid_data(monkeypatch):
    response = Mock()
    response.json.return_value = {"unexpected_key": []}
    response.raise_for_status.return_value = None

    monkeypatch.setattr(
        data_functions.requests,
        "get",
        Mock(return_value=response),
    )

    data_functions.get_sites.clear()

    result = get_sites(
        latitude=53.3811,
        longitude=-1.4701,
        radius=1000,
    )

    assert result == []


def test_get_sites_returns_empty_list_for_invalid_data_with_heritage(monkeypatch):
    response = Mock()
    response.json.return_value = {"unexpected_key": []}
    response.raise_for_status.return_value = None

    monkeypatch.setattr(
        data_functions.requests,
        "get",
        Mock(return_value=response),
    )

    data_functions.get_sites.clear()

    result = get_sites(
        latitude=53.3811,
        longitude=-1.4701,
        radius=1000,
    )

    assert result == []


def test_get_conservation_areas_returns_features(monkeypatch):
    expected_features = [{"attributes": {"NAME": "Test"}}]

    response = Mock()
    response.json.return_value = {"features": expected_features}
    response.raise_for_status = None

    get_mock = Mock(return_value=response)
    monkeypatch.setattr(data_functions.requests, "get", get_mock)

    data_functions.get_conservation_areas.clear()

    result = data_functions.get_conservation_areas(
        latitude=53.3811, longitude=-1.4701, radius=200)

    assert result == expected_features
    get_mock.assert_called_once()

    call_kwargs = get_mock.call_args.kwargs
    assert call_kwargs["impersonate"] == "chrome124"
    assert call_kwargs["url"].startswith(
        "https://services-eu1.arcgis.com/"
    )
    assert "geometry=-1.4701,53.3811" in call_kwargs["url"]
    assert "distance=200" in call_kwargs["url"]


def test_get_conservation_areas_returns_empty_list_when_no_features(monkeypatch):
    response = Mock()
    response.json.return_value = {"features": []}
    response.raise_for_status.return_value = None

    get_mock = Mock(return_value=response)
    monkeypatch.setattr(data_functions.requests, "get", get_mock)

    data_functions.get_conservation_areas.clear()

    result = get_conservation_areas(
        latitude=53.3811,
        longitude=-1.4701,
        radius=1000,
    )

    assert result == []


def test_get_conservation_areas_returns_empty_list_for_invalid_data(monkeypatch):
    response = Mock()
    response.json.return_value = {"unexpected_key": []}
    response.raise_for_status.return_value = None

    monkeypatch.setattr(
        data_functions.requests,
        "get",
        Mock(return_value=response),
    )

    data_functions.get_conservation_areas.clear()

    result = get_conservation_areas(
        latitude=53.3811,
        longitude=-1.4701,
        radius=1000,
    )

    assert result == []


def test_load_application_data(monkeypatch):
    items = [
        {
            "application_id": "A001",
            "area_id": Decimal("42"),
            "location_x": Decimal("451234.5"),
            "location_y": Decimal("387654.2"),
            "start_date": "2025-01-15",
        }
    ]

    table = Mock()
    table.scan.return_value = {"Items": items}

    dynamodb = Mock()
    dynamodb.Table.return_value = table

    session = Mock()
    session.resource.return_value = dynamodb

    monkeypatch.setenv("PLANNING_TABLE_NAME", "test-planning-table")
    load_application_data.clear()

    result = load_application_data(session)

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 1
    assert result.loc[0, "application_id"] == "A001"
    assert result.loc[0, "area_id"] == 42.0
    assert result.loc[0, "location_x"] == 451234.5
    assert result.loc[0, "location_y"] == 387654.2
    assert result.loc[0, "start_date"] == pd.Timestamp("2025-01-15")

    session.resource.assert_called_once_with("dynamodb")
    dynamodb.Table.assert_called_once_with("test-planning-table")
    table.scan.assert_called_once_with()


def test_load_application_data_paginates(monkeypatch):
    first_page = {
        "Items": [
            {
                "application_id": "A001",
                "area_id": Decimal("1"),
                "start_date": "2025-01-01",
            }
        ],
        "LastEvaluatedKey": {"application_id": "A001"},
    }

    second_page = {
        "Items": [
            {
                "application_id": "A002",
                "area_id": Decimal("2"),
                "start_date": "2025-01-02",
            }
        ]
    }

    table = Mock()
    table.scan.side_effect = [first_page, second_page]

    dynamodb = Mock()
    dynamodb.Table.return_value = table

    session = Mock()
    session.resource.return_value = dynamodb

    monkeypatch.setenv("PLANNING_TABLE_NAME", "test-planning-table")
    load_application_data.clear()

    result = load_application_data(session)

    assert list(result["application_id"]) == ["A001", "A002"]
    assert list(result["area_id"]) == [1.0, 2.0]

    assert table.scan.call_count == 2
    table.scan.assert_any_call()
    table.scan.assert_any_call(
        ExclusiveStartKey={"application_id": "A001"}
    )


def test_load_application_data_returns_empty_dataframe_for_empty_table(
    monkeypatch,
):
    table = Mock()
    table.scan.return_value = {"Items": []}

    dynamodb = Mock()
    dynamodb.Table.return_value = table

    session = Mock()
    session.resource.return_value = dynamodb

    info_mock = Mock()
    monkeypatch.setattr(data_functions.st, "info", info_mock)

    load_application_data.clear()

    result = load_application_data(session)

    assert isinstance(result, pd.DataFrame)
    assert result.empty

    info_mock.assert_called_once_with(
        "⚠️ No planning applications found in the database."
    )


def test_load_application_data_handles_unexpected_error(monkeypatch):
    table = Mock()
    table.scan.side_effect = RuntimeError("unexpected failure")

    dynamodb = Mock()
    dynamodb.Table.return_value = table

    session = Mock()
    session.resource.return_value = dynamodb

    error_mock = Mock()
    monkeypatch.setattr(data_functions.st, "error", error_mock)

    load_application_data.clear()

    result = load_application_data(session)

    assert isinstance(result, pd.DataFrame)
    assert result.empty

    error_mock.assert_called_once_with(
        "⚠️ An unexpected error occurred while processing "
        "planning application data."
    )


def test_get_coords_returns_dataframe():
    df = pd.DataFrame({
        "application_id": ["A001", "A002"],
        "area_id": [1, 2],
        "start_date": ["2025-01-01", "2025-01-02"],
        "location_x": [0.1, 0.2],
        "location_y": [51.5, 51.6]
    })

    result = get_coords(df)

    assert isinstance(result, pd.DataFrame)
    assert list(result["location_x"]) == [0.1, 0.2]
    assert list(result["location_y"]) == [51.5, 51.6]
