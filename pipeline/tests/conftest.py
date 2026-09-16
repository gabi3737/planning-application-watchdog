"""Pytest fixtures and mock data."""

import pytest


@pytest.fixture
def mock_app_response():
    """Single application record from API matching actual response structure."""
    return {
        "name": "Newham/26/01919/CLP",
        "address": "121 Sebert Road Forest Gate London E7 0NL",
        "app_type": "Outline",
        "app_state": None,
        "app_size": "Small",
        "area_id": 318,
        "area_name": "Newham",
        "url": "https://www.planit.org.uk/planapplic/Newham/26/01919/CLP/",
        "location_x": 0.031164,
        "location_y": 51.551453,
        "other_fields": {
            "date_received": "2026-09-10",
        }
    }


@pytest.fixture
def mock_app_with_nested_location():
    """Application with geometry location object."""
    return {
        "name": "Newham/26/01920/CLP",
        "address": "456 Oak Road",
        "app_type": "Full",
        "app_state": "Approved",
        "app_size": "Major",
        "area_id": 323,
        "area_name": "Newham2",
        "url": "https://example.com/2001",
        "location": {"geometry": {"coordinates": [234.567, 890.123]}},
        "location_x": 234.567,
        "location_y": 890.123,
        "other_fields": {
            "date_received": "2026-09-09",
        }
    }


@pytest.fixture
def mock_app_missing_location():
    """Application with missing location fields."""
    return {
        "name": "Test/26/00001/APP",
        "address": "789 Pine Ave",
        "app_type": "Listed",
        "app_state": "Withdrawn",
        "app_size": None,
        "area_id": 305,
        "area_name": "Test Area",
        "url": "https://example.com/3001",
        "location_x": None,
        "location_y": None,
        "other_fields": {
            "date_received": "2026-09-08",
        }
    }
