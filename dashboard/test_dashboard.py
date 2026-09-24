# pylint: skip-file

import pandas as pd
import pytest

from dashboard import (
    map_app_type_to_folium_color,
    find_nearby_heritage_sites,
    get_geometry_representative_point,
    build_applications_per_area_chart,
    build_status_donut_chart,
    build_type_chart_per_area,
    filter_applications,
    filter_applications_by_postcode,
    get_status_color,
    get_status_badge,
    build_summary_card_html,
    build_empty_card_html,
    convert_info_to_dict,
    create_application_card,
)
import dashboard


def test_map_app_type_to_folium_color_valid_color():
    assert map_app_type_to_folium_color("Conditions") == "blue"


def test_map_app_type_to_folium_color_remaps_invalid_color(monkeypatch):
    monkeypatch.setitem(dashboard.APP_TYPE_COLORS, "Custom", "yellow")
    assert map_app_type_to_folium_color("Custom") == "orange"


def test_map_app_type_to_folium_color_unknown_type_defaults_to_gray():
    assert map_app_type_to_folium_color("Something Unmapped") == "gray"


def test_find_nearby_heritage_sites_returns_sites_within_radius():
    heritage_sites = [
        {"geometry": {"points": [[-0.04, 51.52]]},
            "attributes": {"Name": "Near Site"}},
        {"geometry": {"points": [[1.0, 55.0]]},
            "attributes": {"Name": "Far Site"}},
    ]

    result = find_nearby_heritage_sites(
        51.52, -0.04, heritage_sites, radius_meters=100)

    assert len(result) == 1
    assert result[0]["site"]["attributes"]["Name"] == "Near Site"
    assert result[0]["distance"] == 0


def test_find_nearby_heritage_sites_returns_empty_list_when_none_nearby():
    heritage_sites = [
        {"geometry": {"points": [[1.0, 55.0]]},
            "attributes": {"Name": "Far Site"}},
    ]

    result = find_nearby_heritage_sites(
        51.52, -0.04, heritage_sites, radius_meters=100)

    assert result == []


def test_find_nearby_heritage_sites_ignores_malformed_site():
    heritage_sites = [{"geometry": {"points": []}}, {"no_geometry": True}]

    result = find_nearby_heritage_sites(
        51.52, -0.04, heritage_sites, radius_meters=100)

    assert result == []


def test_find_nearby_heritage_sites_sorted_by_distance():
    heritage_sites = [
        {"geometry": {"points": [[-0.0395, 51.5205]]},
            "attributes": {"Name": "Slightly Further"}},
        {"geometry": {"points": [[-0.04, 51.52]]},
            "attributes": {"Name": "Closest"}},
    ]

    result = find_nearby_heritage_sites(
        51.52, -0.04, heritage_sites, radius_meters=1000)

    assert result[0]["site"]["attributes"]["Name"] == "Closest"
    assert result[0]["distance"] <= result[1]["distance"]


def test_get_geometry_representative_point_none_geometry():
    assert get_geometry_representative_point(None) is None
    assert get_geometry_representative_point({}) is None


def test_get_geometry_representative_point_esri_points():
    geometry = {"points": [[-0.04, 51.52]]}
    assert get_geometry_representative_point(geometry) == (51.52, -0.04)


def test_get_geometry_representative_point_polygon():
    geometry = {"type": "Polygon", "coordinates": [
        [[-0.04, 51.52], [-0.05, 51.53]]]}
    assert get_geometry_representative_point(geometry) == (51.52, -0.04)


def test_get_geometry_representative_point_multipolygon():
    geometry = {"type": "MultiPolygon",
                "coordinates": [[[[-0.04, 51.52], [-0.05, 51.53]]]]}
    assert get_geometry_representative_point(geometry) == (51.52, -0.04)


def test_get_geometry_representative_point_invalid_returns_none():
    geometry = {"type": "Polygon", "coordinates": []}
    assert get_geometry_representative_point(geometry) is None


def test_build_applications_per_area_chart_empty_df_returns_none():
    assert build_applications_per_area_chart(pd.DataFrame()) is None


def test_build_applications_per_area_chart_returns_chart():
    df = pd.DataFrame({"area": ["Newham", "Newham", "Greenwich"]})
    chart = build_applications_per_area_chart(df)
    assert chart is not None


def test_build_status_donut_chart_empty_df_returns_none():
    assert build_status_donut_chart(pd.DataFrame()) is None


def test_build_status_donut_chart_returns_chart():
    df = pd.DataFrame({"app_state": ["Permitted", "Undecided"]})
    chart = build_status_donut_chart(df)
    assert chart is not None


def test_build_type_chart_per_area_empty_df_returns_none():
    assert build_type_chart_per_area(pd.DataFrame()) is None


def test_build_type_chart_per_area_returns_chart():
    df = pd.DataFrame({"app_type": ["Householder", "Full Planning"]})
    chart = build_type_chart_per_area(df)
    assert chart is not None


@pytest.fixture
def sample_applications_df():
    return pd.DataFrame({
        "uid": ["1", "2", "3"],
        "address": ["1 Main St, Newham", "2 High St, Greenwich", "3 Low St, Tower Hamlets"],
        "area": ["Newham", "Greenwich", "Tower Hamlets"],
        "app_type": ["Householder", "Full Planning", "Householder"],
        "app_state": ["Permitted", "Undecided", "Withdrawn"],
        "start_date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
    })


def test_filter_applications_by_area(sample_applications_df):
    result = filter_applications(
        sample_applications_df, ["Newham"], [], [], (None, None), "")
    assert result["area"].tolist() == ["Newham"]


def test_filter_applications_by_type(sample_applications_df):
    result = filter_applications(
        sample_applications_df, [], ["Full Planning"], [], (None, None), "")
    assert result["app_type"].tolist() == ["Full Planning"]


def test_filter_applications_by_status(sample_applications_df):
    result = filter_applications(
        sample_applications_df, [], [], ["Withdrawn"], (None, None), "")
    assert result["uid"].tolist() == ["3"]


def test_filter_applications_by_date_range(sample_applications_df):
    date_range = (pd.Timestamp("2024-01-15"), pd.Timestamp("2024-02-15"))
    result = filter_applications(
        sample_applications_df, [], [], [], date_range, "")
    assert result["uid"].tolist() == ["2"]


def test_filter_applications_by_search_query_address(sample_applications_df):
    result = filter_applications(
        sample_applications_df, [], [], [], (None, None), "high st")
    assert result["uid"].tolist() == ["2"]


def test_filter_applications_by_search_query_uid(sample_applications_df):
    result = filter_applications(
        sample_applications_df, [], [], [], (None, None), "3")
    assert result["uid"].tolist() == ["3"]


def test_filter_applications_no_filters_returns_all(sample_applications_df):
    result = filter_applications(
        sample_applications_df, [], [], [], (None, None), "")
    assert len(result) == len(sample_applications_df)


# ==================== filter_applications_by_postcode ====================

def test_filter_applications_by_postcode_invalid_postcode_returns_df_copy():
    df = pd.DataFrame({"uid": ["1"]})
    result_df, result_coords = filter_applications_by_postcode(df, "")
    assert result_df.equals(df)
    assert result_coords == {}


def test_filter_applications_by_postcode_error_from_lookup(monkeypatch):
    monkeypatch.setattr(
        dashboard, "get_postcode_coordinates",
        lambda postcode: {"error": "Invalid postcode"})

    df = pd.DataFrame(
        {"uid": ["1"], "location_x": [-0.04], "location_y": [51.52]})
    result_df, result_coords = filter_applications_by_postcode(df, "INVALID")

    assert result_df.empty
    assert result_coords == {"error": "Invalid postcode"}


def test_filter_applications_by_postcode_filters_by_distance(monkeypatch):
    monkeypatch.setattr(
        dashboard, "get_postcode_coordinates",
        lambda postcode: {"latitude": 51.52, "longitude": -0.04, "postcode": "E1 6AN"})

    df = pd.DataFrame({
        "uid": ["near", "far"],
        "location_y": [51.52, 55.0],
        "location_x": [-0.04, 1.0],
    })

    result_df, result_coords = filter_applications_by_postcode(
        df, "E1 6AN", radius_km=1)

    assert result_df["uid"].tolist() == ["near"]
    assert result_coords["postcode"] == "E1 6AN"


def test_get_status_color_known_status():
    assert get_status_color("Permitted") == "#4ade80"


def test_get_status_color_unknown_status_defaults():
    assert get_status_color("Something Else") == "#9ca3af"


def test_get_status_badge_known_status():
    assert get_status_badge("Withdrawn") == "✗ Withdrawn"


def test_get_status_badge_unknown_status_defaults():
    assert get_status_badge("Something Else") == "• Unknown"


def test_build_summary_card_html_contains_expected_fields():
    app_info = {
        "uid": "26/2638",
        "address": "1 Main St",
        "app_type": "Householder",
        "area": "Newham",
        "app_state": "Permitted",
        "summary": "A summary",
    }
    html = build_summary_card_html(app_info)
    assert "26/2638" in html
    assert "1 Main St" in html
    assert "Householder" in html
    assert "Newham" in html
    assert "✓ Permitted" in html
    assert "A summary" in html


def test_build_summary_card_html_escapes_html_characters():
    app_info = {"uid": "<script>", "address": "A & B"}
    html = build_summary_card_html(app_info)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "A &amp; B" in html


def test_build_empty_card_html_contains_placeholder_text():
    html = build_empty_card_html()
    assert "Click a marker on the map" in html


def test_create_application_card_contains_expected_fields():
    app = {
        "uid": "26/2638",
        "address": "1 Main St",
        "app_type": "Householder",
        "area": "Newham",
        "app_state": "Undecided",
        "summary": "A summary",
    }
    html = create_application_card(app)
    assert "26/2638" in html
    assert "1 Main St" in html
    assert "Householder" in html
    assert "Newham" in html
    assert "⏳ Undecided" in html
    assert "A summary" in html


def test_convert_info_to_dict_parses_key_value_lines():
    info_string = (
        "UID: 26/2638\n"
        "Address: 1 Main St\n"
        "Type: Householder\n"
        "View on Council Website\n"
    )
    result = convert_info_to_dict(info_string)
    assert result == {
        "uid": "26/2638",
        "address": "1 Main St",
        "type": "Householder",
    }


def test_convert_info_to_dict_ignores_lines_without_colon():
    info_string = "UID: 26/2638\nNo colon here\nLast line ignored\n"
    result = convert_info_to_dict(info_string)
    assert result == {"uid": "26/2638"}
