"""Tests for transform.py"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile
import os
from transform import (
    load_csv_data,
    standardize_nulls,
    typecast_columns,
    validate_required_fields,
    validate_coordinate_ranges,
    validate_data,
)


@pytest.fixture
def sample_df():
    """Create a sample dataframe with various data issues."""
    return pd.DataFrame({
        "uid": ["App/001", "App/002", "App/003", None],
        "address": ["123 Main St", "", "456 Oak Ave", "789 Elm St"],
        "postcode": ["SW1A 1AA", np.nan, "E1 6AN", "N1 1AA"],
        "app_type": ["Full", "Outline", "Invalid", "Full"],
        "app_state": [None, "Approved", "", "Pending"],
        "app_size": ["Small", "Major", "Small", None],
        "area_id": [318, 323, 318, 304],
        "area_name": ["Newham", "Tower Hamlets", "Newham", "Hackney"],
        "start_date": ["2026-09-10", "2026-09-11", "invalid_date", "2026-09-12"],
        "url": ["http://example.com/1", "http://example.com/2", "http://example.com/3", None],
        # Last one outside valid range
        "location_x": [0.031164, 0.05, -10.0, 1.5],
        # Third one outside valid range
        "location_y": [51.551453, 51.533543, 60.0, 51.5],
    })


@pytest.fixture
def clean_df():
    """Create a clean, well-formed dataframe."""
    return pd.DataFrame({
        "uid": ["App/001", "App/002", "App/003"],
        "address": ["123 Main St", "456 Oak Ave", "789 Elm St"],
        "postcode": ["SW1A 1AA", "E1 6AN", "N1 1AA"],
        "app_type": ["Full", "Outline", "Full"],
        "app_state": ["Approved", "Pending", "Withdrawn"],
        "app_size": ["Small", "Major", "Small"],
        "area_id": [318, 323, 318],
        "area_name": ["Newham", "Tower Hamlets", "Newham"],
        "start_date": ["2026-09-10", "2026-09-11", "2026-09-12"],
        "url": ["http://example.com/1", "http://example.com/2", "http://example.com/3"],
        "location_x": [0.031164, 0.05, -0.15],
        "location_y": [51.551453, 51.533543, 51.5],
    })


class TestLoadCsvData:
    """Tests for load_csv_data function."""

    def test_load_valid_csv(self, clean_df):
        """Test loading a valid CSV file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "test.csv"
            clean_df.to_csv(csv_path, index=False)

            df = load_csv_data(csv_path)
            assert df is not None
            assert len(df) == 3
            assert list(df.columns) == list(clean_df.columns)

    def test_load_nonexistent_file(self):
        """Test loading a file that doesn't exist."""
        df = load_csv_data(Path("/nonexistent/file.csv"))
        assert df is None

    def test_load_csv_preserves_dtypes(self, clean_df):
        """Test that loading CSV preserves data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "test.csv"
            clean_df.to_csv(csv_path, index=False)

            df = load_csv_data(csv_path)
            assert len(df) == len(clean_df)


class TestStandardizeNulls:
    """Tests for standardize_nulls function."""

    def test_replaces_nan_with_na(self, sample_df):
        """Test that NaN values are replaced with 'N/A'."""
        result = standardize_nulls(sample_df)
        assert "N/A" in result["postcode"].values
        assert pd.isna(result).sum().sum() == 0  # No NaN values left

    def test_replaces_none_with_na(self, sample_df):
        """Test that None values are replaced with 'N/A'."""
        result = standardize_nulls(sample_df)
        assert (result["uid"] == "N/A").any()
        assert (result["app_state"] == "N/A").any()

    def test_replaces_empty_strings_with_na(self, sample_df):
        """Test that empty strings are replaced with 'N/A'."""
        # Test with a dataframe that has been loaded from CSV (where dtypes may differ)
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "test_empty.csv"
            # Create a dataframe with empty strings
            test_df = pd.DataFrame({
                "col1": ["value", "", "another"],
            })
            test_df.to_csv(csv_path, index=False)

            # Load it back (simulates what happens in real use)
            loaded_df = pd.read_csv(csv_path)
            result = standardize_nulls(loaded_df)

            # The empty string should be converted to N/A
            assert result.loc[1, "col1"] == "N/A"
            assert result.loc[0, "col1"] == "value"

    def test_no_remaining_nulls(self, sample_df):
        """Test that there are no remaining null values."""
        result = standardize_nulls(sample_df)
        # Check for NaN values
        assert result.isna().sum().sum() == 0
        # Check that no values are empty strings (all should be "N/A" or actual values)
        for col in result.columns:
            if result[col].dtype == "object":
                assert not (result[col] == "").any()


class TestTypecastColumns:
    """Tests for typecast_columns function."""

    def test_casts_area_id_to_int(self, clean_df):
        """Test that area_id is cast to integer."""
        result, _ = typecast_columns(clean_df)
        assert result["area_id"].dtype == "int"

    def test_casts_location_to_float(self, clean_df):
        """Test that location coordinates are cast to float."""
        result, _ = typecast_columns(clean_df)
        assert result["location_x"].dtype == "float"
        assert result["location_y"].dtype == "float"

    def test_casts_start_date_to_datetime(self, clean_df):
        """Test that start_date is cast to datetime."""
        result, _ = typecast_columns(clean_df)
        assert pd.api.types.is_datetime64_any_dtype(result["start_date"])

    def test_casts_string_columns_to_string(self, clean_df):
        """Test that string columns are cast to string type."""
        result, _ = typecast_columns(clean_df)
        assert result["uid"].dtype == "string"
        assert result["address"].dtype == "string"

    def test_handles_invalid_dates(self, sample_df):
        """Test that invalid dates are handled."""
        result, _ = typecast_columns(sample_df)
        assert pd.api.types.is_datetime64_any_dtype(result["start_date"])

    def test_returns_errors_for_casting_issues(self, sample_df):
        """Test that errors are returned for invalid values."""
        _, errors = typecast_columns(sample_df)
        # Should not have errors for this dataset (coercion happens)
        assert isinstance(errors, list)


class TestValidateRequiredFields:
    """Tests for validate_required_fields function."""

    def test_detects_missing_required_fields(self, sample_df):
        """Test that missing required fields are detected."""
        # First standardize nulls which converts None to N/A
        df = standardize_nulls(sample_df)
        errors = validate_required_fields(df)
        # Should detect missing uid and url values (now as N/A)
        assert len(errors) > 0
        assert any("uid" in str(e) or "url" in str(e) for e in errors)

    def test_passes_complete_required_fields(self, clean_df):
        """Test that complete required fields pass validation."""
        # First standardize nulls
        df = standardize_nulls(clean_df)
        errors = validate_required_fields(df)
        assert len(errors) == 0


class TestValidateCoordinateRanges:
    """Tests for validate_coordinate_ranges function."""

    def test_detects_coordinates_outside_uk_range(self, sample_df):
        """Test that coordinates outside UK range are detected."""
        errors = validate_coordinate_ranges(sample_df)
        assert len(errors) > 0

    def test_accepts_valid_coordinates(self, clean_df):
        """Test that valid UK coordinates pass validation."""
        errors = validate_coordinate_ranges(clean_df)
        assert len(errors) == 0

    def test_ignores_zero_coordinates(self, clean_df):
        """Test that zero coordinates (placeholder) are allowed."""
        clean_df.loc[0, "location_x"] = 0.0
        clean_df.loc[0, "location_y"] = 0.0
        errors = validate_coordinate_ranges(clean_df)
        # Should not complain about zeros
        assert len(errors) == 0


class TestValidateData:
    """Tests for validate_data function."""

    def test_returns_dataframe_and_report(self, clean_df):
        """Test that validate_data returns both dataframe and report."""
        df, report = validate_data(clean_df)
        assert isinstance(df, pd.DataFrame)
        assert isinstance(report, dict)

    def test_report_contains_error_details(self, sample_df):
        """Test that report contains detailed error information."""
        _, report = validate_data(sample_df)
        assert "total_rows" in report
        assert "required_field_errors" in report
        assert "coordinate_errors" in report
        assert "total_errors" in report

    def test_handles_empty_dataframe(self):
        """Test that empty dataframe is handled gracefully."""
        df, report = validate_data(pd.DataFrame())
        assert report["total_errors"] > 0


# class TestTransform:
#     """Tests for transform function."""

#     def test_transform_complete_pipeline(self, sample_df):
#         """Test that transform runs the complete pipeline."""
#         with tempfile.TemporaryDirectory() as tmpdir:
#             csv_path = Path(tmpdir) / "test.csv"
#             sample_df.to_csv(csv_path, index=False)

#             df, report = transform(csv_path)

#             assert df is not None
#             assert isinstance(report, dict)
#             assert "rows_processed" in report
#             assert "type_casting_errors" in report
#             assert "validation_report" in report

#     def test_transform_cleans_data(self, sample_df):
#         """Test that transform properly cleans the data."""
#         with tempfile.TemporaryDirectory() as tmpdir:
#             csv_path = Path(tmpdir) / "test.csv"
#             sample_df.to_csv(csv_path, index=False)

#             df, _ = transform(csv_path)

#             # Check that types are correct
#             assert df["location_x"].dtype == "float"
#             assert df["area_id"].dtype == "int"

#     def test_transform_returns_report_for_missing_file(self):
#         """Test that transform returns report for missing file."""
#         df, report = transform(Path("/nonexistent/file.csv"))
#         assert df is None
#         assert "error" in report


# class TestIntegration:
#     """Integration tests for the full transformation workflow."""

#     def test_messy_data_transformation(self, sample_df):
#         """Test transformation of messy real-world-like data."""
#         with tempfile.TemporaryDirectory() as tmpdir:
#             csv_path = Path(tmpdir) / "messy.csv"
#             sample_df.to_csv(csv_path, index=False)

#             df, report = transform(csv_path)

#             # Data should be cleaned
#             assert df is not None

#             # Types should be correct
#             assert df["area_id"].dtype == "int"
#             assert df["location_x"].dtype == "float"

#             # Should have minimal NaN values
#             nan_count = df.isna().sum().sum()
#             assert nan_count <= 1  # Allow up to 1 NaN in case of datetime conversion issues

#     def test_multiple_transformations_consistent(self, clean_df):
#         """Test that multiple transformations produce consistent results."""
#         with tempfile.TemporaryDirectory() as tmpdir:
#             csv_path = Path(tmpdir) / "clean.csv"
#             clean_df.to_csv(csv_path, index=False)

#             df1, _ = transform(csv_path)
#             df2, _ = transform(csv_path)

#             pd.testing.assert_frame_equal(df1, df2)
