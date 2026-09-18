"""Tests for extract module."""

from extract import (
    calculate_date_range,
    extract_from_record,
    fetch_applications,
)
import tempfile
import pandas as pd
from datetime import datetime
from unittest.mock import patch, Mock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDateRange:
    """Test date range calculation."""

    def test_calculate_date_range_returns_tuple(self):
        """Should return tuple of two strings."""
        start, end = calculate_date_range()
        assert isinstance(start, str)
        assert isinstance(end, str)

    def test_calculate_date_range_format(self):
        """Should return YYYY-MM-DD format."""
        start, end = calculate_date_range()
        assert len(start) == 10
        assert len(end) == 10
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")

    def test_calculate_date_range_seven_days(self):
        """Should be approximately 7 days apart."""
        start, end = calculate_date_range()
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
        diff = (e - s).days
        assert 6 <= diff <= 8


class TestExtractRecord:
    """Test field extraction."""

    def test_extract_all_fields(self, mock_app_response):
        """Should extract all required fields."""
        result = extract_from_record(mock_app_response)

        assert result["uid"] == "Newham/26/01919/CLP"
        assert result["address"] == "121 Sebert Road Forest Gate London E7 0NL"
        assert result["url"] == "https://www.planit.org.uk/planapplic/Newham/26/01919/CLP/"
        assert result["start_date"] == "2026-09-10"
        assert result["location_x"] == 0.031164
        assert result["location_y"] == 51.551453

    def test_extract_handles_missing_location(self, mock_app_missing_location):
        """Should handle missing location."""
        result = extract_from_record(mock_app_missing_location)

        assert result["location_x"] is None
        assert result["location_y"] is None
        assert result["uid"] == "Test/26/00001/APP"

    def test_extract_preserves_null_values(self, mock_app_response):
        """Should preserve null values in fields."""
        mock_app_response["app_state"] = None
        result = extract_from_record(mock_app_response)

        assert result["app_state"] is None

    def test_extract_returns_none_for_empty_record(self):
        """Should return None for record with no data."""
        result = extract_from_record({})
        assert result is None


class TestFetchApplications:
    """Test API fetching."""

    def test_fetch_single_page(self, mock_app_response):
        """Should fetch single page of results."""
        # Create mock responses that simulate pagination ending
        mock_response_page1 = Mock()
        mock_response_page1.json.return_value = {
            "records": [mock_app_response]}

        mock_response_page2 = Mock()
        mock_response_page2.json.return_value = {"records": []}

        with patch("extract.requests.get", side_effect=[mock_response_page1, mock_response_page2]):
            results = fetch_applications(318, "2026-09-01", "2026-09-15")

        assert len(results) == 1
        assert results[0]["name"] == "Newham/26/01919/CLP"

    def test_fetch_handles_empty_response(self):
        """Should handle empty records response."""
        mock_response = Mock()
        mock_response.json.return_value = {"records": []}

        with patch("extract.requests.get", return_value=mock_response):
            results = fetch_applications(318, "2026-09-01", "2026-09-15")

        assert len(results) == 0


# class TestSaveCSV:
#     """Test CSV saving."""

#     def test_save_creates_file(self, mock_app_response):
#         """Should create CSV file."""
#         with tempfile.TemporaryDirectory() as tmpdir:
#             records = [extract_from_record(mock_app_response)]

#             with patch("extract.DATA_DIR", Path(tmpdir)):
#                 result = save_to_csv(records, "test_area")

#             assert Path(tmpdir, "test_area.csv").exists()

#     def test_save_contains_data(self, mock_app_response):
#         """Should save correct data to CSV."""
#         with tempfile.TemporaryDirectory() as tmpdir:
#             records = [extract_from_record(mock_app_response)]

#             with patch("extract.DATA_DIR", Path(tmpdir)):
#                 save_to_csv(records, "test_area")

#             df = pd.read_csv(Path(tmpdir, "test_area.csv"))
#             assert len(df) == 1
#             assert df.loc[0, "uid"] == "Newham/26/01919/CLP"

#     def test_save_handles_empty_records(self):
#         """Should handle empty records list."""
#         with tempfile.TemporaryDirectory() as tmpdir:
#             with patch("extract.DATA_DIR", Path(tmpdir)):
#                 result = save_to_csv([], "test_area")

#             assert result is None
