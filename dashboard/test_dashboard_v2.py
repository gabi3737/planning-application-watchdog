# pylint: skip-file

from unittest.mock import Mock

import pandas as pd
import pytest

import dashboard_v2
from dashboard_v2 import (
    map_app_type_to_folium_color,
    find_nearby_heritage_sites,
    filter_applications,
    display_metrics,
    load_all_applications,
    load_heritage_sites,
    load_conservation_areas_data,
)


class TestMapAppTypeToFoliumColor:
    """Tests for map_app_type_to_folium_color."""

    def test_returns_valid_color_unchanged(self, monkeypatch):
        monkeypatch.setitem(dashboard_v2.APP_TYPE_COLORS, "Full", "green")
        assert map_app_type_to_folium_color("Full") == "green"

    def test_remaps_invalid_color(self, monkeypatch):
        monkeypatch.setitem(dashboard_v2.APP_TYPE_COLORS, "Full", "yellow")
        assert map_app_type_to_folium_color("Full") == "orange"

    def test_defaults_to_gray_for_unknown_type(self):
        assert map_app_type_to_folium_color("Unknown Type") == "gray"


class TestFindNearbyHeritageSites:
    """Tests for find_nearby_heritage_sites."""

    def test_finds_sites_within_radius(self):
        heritage_sites = [
            {"geometry": {"points": [[-0.01, 51.51]]},
                "attributes": {"Name": "Near"}},
            {"geometry": {"points": [[10.0, 10.0]]},
                "attributes": {"Name": "Far"}},
        ]

        result = find_nearby_heritage_sites(
            51.51, -0.01, heritage_sites, radius_meters=100)

        assert len(result) == 1
        assert result[0]["site"]["attributes"]["Name"] == "Near"

    def test_returns_empty_list_when_no_sites_nearby(self):
        heritage_sites = [
            {"geometry": {"points": [[10.0, 10.0]]},
                "attributes": {"Name": "Far"}},
        ]

        result = find_nearby_heritage_sites(
            51.51, -0.01, heritage_sites, radius_meters=100)

        assert result == []

    def test_ignores_malformed_sites(self):
        heritage_sites = [{"geometry": {}}, {"no_geometry": True}]

        result = find_nearby_heritage_sites(
            51.51, -0.01, heritage_sites, radius_meters=100)

        assert result == []

    def test_sorts_results_by_distance(self):
        heritage_sites = [
            {"geometry": {"points": [[-0.0095, 51.5105]]},
                "attributes": {"Name": "Further"}},
            {"geometry": {"points": [[-0.0101, 51.5101]]},
                "attributes": {"Name": "Closer"}},
        ]

        result = find_nearby_heritage_sites(
            51.51, -0.01, heritage_sites, radius_meters=200)

        assert [item["site"]["attributes"]["Name"]
                for item in result] == ["Closer", "Further"]


class TestFilterApplications:
    """Tests for filter_applications."""

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "area": ["Newham", "Croydon", "Newham"],
            "app_type": ["Full", "Outline", "Full"],
            "app_state": ["Pending", "Approved", "Approved"],
            "address": ["10 Main St", "20 High St", "30 Park Rd"],
            "uid": ["App/1", "App/2", "App/3"],
            "start_date": pd.to_datetime(
                ["2024-01-01", "2024-02-01", "2024-03-01"]),
        })

    def test_filters_by_area(self, sample_df):
        result = filter_applications(
            sample_df, ["Newham"], [], [], (None, None), "")
        assert set(result["area"]) == {"Newham"}

    def test_filters_by_type(self, sample_df):
        result = filter_applications(
            sample_df, [], ["Outline"], [], (None, None), "")
        assert set(result["app_type"]) == {"Outline"}

    def test_filters_by_status(self, sample_df):
        result = filter_applications(
            sample_df, [], [], ["Pending"], (None, None), "")
        assert set(result["app_state"]) == {"Pending"}

    def test_filters_by_date_range(self, sample_df):
        result = filter_applications(
            sample_df, [], [], [], (pd.Timestamp("2024-01-15"), pd.Timestamp("2024-02-15")), "")
        assert list(result["uid"]) == ["App/2"]

    def test_filters_by_search_query_address(self, sample_df):
        result = filter_applications(
            sample_df, [], [], [], (None, None), "high st")
        assert list(result["uid"]) == ["App/2"]

    def test_filters_by_search_query_uid(self, sample_df):
        result = filter_applications(
            sample_df, [], [], [], (None, None), "app/3")
        assert list(result["uid"]) == ["App/3"]

    def test_no_filters_returns_all_rows(self, sample_df):
        result = filter_applications(
            sample_df, [], [], [], (None, None), "")
        assert len(result) == len(sample_df)


class TestDisplayMetrics:
    """Tests for display_metrics (streamlit calls are no-ops outside a script run)."""

    def test_runs_without_error_on_populated_dataframe(self):
        df = pd.DataFrame({"area": ["Newham", "Newham", "Croydon"]})
        display_metrics(df)

    def test_runs_without_error_on_empty_dataframe(self):
        display_metrics(pd.DataFrame())


class TestLoadAllApplications:
    """Tests for load_all_applications."""

    def test_returns_dataframe_from_dynamodb(self, monkeypatch):
        df = pd.DataFrame({
            "uid": ["App/1"],
            "address": ["10 Main St"],
            "app_type": ["Full"],
            "app_state": ["Pending"],
            "location_x": [0.01],
            "location_y": [51.5],
            "start_date": ["2024-01-01"],
            "area": ["Newham"],
        })
        monkeypatch.setattr(
            dashboard_v2, "create_boto3_session", Mock(return_value=Mock()))
        monkeypatch.setattr(
            dashboard_v2, "load_application_data", Mock(return_value=df))

        load_all_applications.clear()
        result = load_all_applications()

        assert len(result) == 1
        assert result.iloc[0]["uid"] == "App/1"

    def test_fills_missing_columns(self, monkeypatch):
        df = pd.DataFrame({"uid": ["App/1"]})
        monkeypatch.setattr(
            dashboard_v2, "create_boto3_session", Mock(return_value=Mock()))
        monkeypatch.setattr(
            dashboard_v2, "load_application_data", Mock(return_value=df))

        load_all_applications.clear()
        result = load_all_applications()

        assert "area" in result.columns
        assert "location_x" in result.columns

    def test_returns_empty_dataframe_on_error(self, monkeypatch):
        monkeypatch.setattr(
            dashboard_v2, "create_boto3_session", Mock(side_effect=Exception("boom")))

        load_all_applications.clear()
        result = load_all_applications()

        assert result.empty


class TestLoadHeritageSites:
    """Tests for load_heritage_sites."""

    def test_returns_sites_from_get_sites(self, monkeypatch):
        sites = [{"attributes": {"Name": "Test"}}]
        monkeypatch.setattr(dashboard_v2, "get_sites",
                            Mock(return_value=sites))

        load_heritage_sites.clear()
        result = load_heritage_sites()

        assert result == sites

    def test_returns_empty_list_on_error(self, monkeypatch):
        monkeypatch.setattr(
            dashboard_v2, "get_sites", Mock(side_effect=Exception("boom")))

        load_heritage_sites.clear()
        result = load_heritage_sites()

        assert result == []


class TestLoadConservationAreasData:
    """Tests for load_conservation_areas_data."""

    def test_returns_areas_from_get_conservation_areas(self, monkeypatch):
        areas = [{"geometry": {}, "properties": {"NAME": "Test Area"}}]
        monkeypatch.setattr(
            dashboard_v2, "get_conservation_areas", Mock(return_value=areas))

        load_conservation_areas_data.clear()
        result = load_conservation_areas_data()

        assert result == areas

    def test_returns_empty_list_on_error(self, monkeypatch):
        monkeypatch.setattr(
            dashboard_v2, "get_conservation_areas", Mock(side_effect=Exception("boom")))

        load_conservation_areas_data.clear()
        result = load_conservation_areas_data()

        assert result == []
