"""Tests for load module."""

from pathlib import Path
from decimal import Decimal
from unittest.mock import patch, Mock

import pytest
import pandas as pd
from botocore.exceptions import ClientError

from load import (
    csv_row_to_dynamodb_item,
    load_dataframe,
    load_from_dataframes,
    load_csv_file,
    load_all_files,
    initialize_dynamodb,
    initialize_s3,
    main_from_dataframes,
    upload_documents_to_s3,
    main,
)


class TestCsvRowToDynamodbItem:
    """Test conversion of a CSV row into DynamoDB key/attribute dicts."""

    def test_converts_basic_row(self):
        row = pd.Series({
            "area_name": "Newham",
            "uid": "App/001",
            "address": "123 Main St",
            "area_id": 318,
            "location_x": 0.031164,
            "location_y": 51.551453,
        })
        keys, attributes = csv_row_to_dynamodb_item(row)

        assert keys == {"area": "Newham", "uid": "App/001"}
        assert attributes["address"] == "123 Main St"
        assert attributes["area_id"] == 318
        assert attributes["location_x"] == Decimal("0.031164")
        assert attributes["location_y"] == Decimal("51.551453")

    def test_skips_nan_values(self):
        row = pd.Series({
            "area_name": "Newham",
            "uid": "App/001",
            "address": float("nan"),
        })
        _, attributes = csv_row_to_dynamodb_item(row)
        assert "address" not in attributes

    def test_returns_none_when_missing_partition_key(self):
        row = pd.Series({"uid": "App/001", "address": "123 Main St"})
        keys, attributes = csv_row_to_dynamodb_item(row)
        assert keys is None
        assert attributes is None

    def test_returns_none_when_missing_sort_key(self):
        row = pd.Series({"area_name": "Newham", "address": "123 Main St"})
        keys, attributes = csv_row_to_dynamodb_item(row)
        assert keys is None
        assert attributes is None

    def test_invalid_numeric_value_falls_back_to_string(self):
        row = pd.Series({
            "area_name": "Newham",
            "uid": "App/001",
            "area_id": "not_a_number",
        })
        _, attributes = csv_row_to_dynamodb_item(row)
        assert attributes["area_id"] == "not_a_number"


class TestLoadDataframe:
    """Test loading a single DataFrame into DynamoDB."""

    def test_returns_zeros_for_empty_dataframe(self):
        assert load_dataframe(Mock(), pd.DataFrame(), "area_318") == (0, 0, 0)

    def test_returns_zeros_for_none_dataframe(self):
        assert load_dataframe(Mock(), None, "area_318") == (0, 0, 0)

    def test_skips_rows_missing_keys(self):
        df = pd.DataFrame({"address": ["123 Main St"]})
        created, updated, failed = load_dataframe(Mock(), df, "area_318")
        assert (created, updated, failed) == (0, 0, 1)

    def test_creates_new_record(self):
        df = pd.DataFrame({
            "area_name": ["Newham"],
            "uid": ["App/001"],
            "address": ["123 Main St"],
        })
        table = Mock()
        table.get_item.return_value = {}  # No existing item

        created, updated, failed = load_dataframe(table, df, "area_318")

        assert (created, updated, failed) == (1, 0, 0)
        table.update_item.assert_called_once()

    def test_updates_existing_record(self):
        df = pd.DataFrame({
            "area_name": ["Newham"],
            "uid": ["App/001"],
            "address": ["123 Main St"],
        })
        table = Mock()
        table.get_item.return_value = {"Item": {"area": "Newham"}}

        created, updated, failed = load_dataframe(table, df, "area_318")

        assert (created, updated, failed) == (0, 1, 0)

    def test_no_db_mode_skips_writes(self):
        df = pd.DataFrame({
            "area_name": ["Newham"],
            "uid": ["App/001"],
            "address": ["123 Main St"],
        })
        table = Mock()

        result = load_dataframe(table, df, "area_318", no_db=True)

        assert result == (0, 0, 0)
        table.get_item.assert_not_called()

    def test_handles_client_error(self):
        df = pd.DataFrame({
            "area_name": ["Newham"],
            "uid": ["App/001"],
            "address": ["123 Main St"],
        })
        table = Mock()
        table.get_item.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "boom"}}, "GetItem")

        _, _, failed = load_dataframe(table, df, "area_318")

        assert failed == 1


class TestLoadFromDataframes:
    """Test loading multiple area DataFrames into DynamoDB."""

    def test_aggregates_totals_across_areas(self):
        table = Mock()
        table.get_item.return_value = {}
        dfs = {
            "area_318": pd.DataFrame({
                "area_name": ["Newham"], "uid": ["App/001"], "address": ["123"],
            }),
            "area_323": pd.DataFrame({
                "area_name": ["Tower Hamlets"], "uid": ["App/002"], "address": ["456"],
            }),
        }

        created, updated, failed = load_from_dataframes(table, dfs)

        assert (created, updated, failed) == (2, 0, 0)


class TestLoadCsvFile:
    """Test loading a single CSV file into DynamoDB."""

    def test_loads_valid_csv(self, tmp_path):
        csv_path = tmp_path / "area_318.csv"
        pd.DataFrame({
            "area_name": ["Newham"], "uid": ["App/001"], "address": ["123"],
        }).to_csv(csv_path, index=False)

        table = Mock()
        table.get_item.return_value = {}

        created, updated, failed = load_csv_file(table, csv_path)

        assert (created, failed) == (1, 0)

    def test_returns_failed_for_missing_file(self):
        result = load_csv_file(Mock(), Path("/nonexistent/file.csv"))
        assert result == (0, 0, 1)


class TestLoadAllFiles:
    """Test loading all CSV files in the data directory."""

    def test_returns_empty_dict_when_data_dir_missing(self):
        with patch("load.DATA_DIR", Path("/nonexistent/dir")):
            result = load_all_files(Mock())
        assert result == {}

    def test_returns_empty_dict_when_no_csv_files(self, tmp_path):
        with patch("load.DATA_DIR", tmp_path):
            result = load_all_files(Mock())
        assert result == {}

    def test_loads_all_csv_files(self, tmp_path):
        pd.DataFrame({
            "area_name": ["Newham"], "uid": ["App/001"], "address": ["123"],
        }).to_csv(tmp_path / "area_318.csv", index=False)

        table = Mock()
        table.get_item.return_value = {}

        with patch("load.DATA_DIR", tmp_path):
            result = load_all_files(table)

        assert result["area_318.csv"] == (1, 0, 0)


class TestInitializeDynamodb:
    """Test DynamoDB resource initialization."""

    def test_returns_table_on_success(self):
        mock_table = Mock()
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table

        with patch("load.boto3.resource", return_value=mock_dynamodb):
            table = initialize_dynamodb()

        assert table is mock_table
        mock_table.load.assert_called_once()

    def test_raises_on_client_error(self):
        mock_dynamodb = Mock()
        mock_dynamodb.Table.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "boom"}}, "DescribeTable")

        with patch("load.boto3.resource", return_value=mock_dynamodb):
            with pytest.raises(ClientError):
                initialize_dynamodb()


class TestInitializeS3:
    """Test S3 client initialization."""

    def test_returns_client_on_success(self):
        mock_s3 = Mock()

        with patch("load.boto3.client", return_value=mock_s3):
            s3_client = initialize_s3()

        assert s3_client is mock_s3
        mock_s3.head_bucket.assert_called_once()

    def test_raises_on_client_error(self):
        mock_s3 = Mock()
        mock_s3.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "boom"}}, "HeadBucket")

        with patch("load.boto3.client", return_value=mock_s3):
            with pytest.raises(ClientError):
                initialize_s3()


class TestMainFromDataframes:
    """Test the DataFrame-based load entry point."""

    def test_delegates_to_load_from_dataframes(self):
        table = Mock()
        table.get_item.return_value = {}
        dfs = {
            "area_318": pd.DataFrame({
                "area_name": ["Newham"], "uid": ["App/001"], "address": ["123"],
            }),
        }

        with patch("load.initialize_dynamodb", return_value=table):
            created, _, failed = main_from_dataframes(dfs)

        assert (created, failed) == (1, 0)


class TestUploadDocumentsToS3:
    """Test uploading local documents to S3."""

    def test_returns_zero_when_documents_dir_missing(self):
        with patch("load.DOCUMENTS_DIR", Path("/nonexistent/dir")):
            assert upload_documents_to_s3(Mock()) == (0, 0)

    def test_returns_zero_when_no_uid_folders(self, tmp_path):
        with patch("load.DOCUMENTS_DIR", tmp_path):
            assert upload_documents_to_s3(Mock()) == (0, 0)

    def test_uploads_pdfs_successfully(self, tmp_path):
        uid_folder = tmp_path / "App_001"
        uid_folder.mkdir()
        (uid_folder / "form.pdf").write_bytes(b"content")

        s3_client = Mock()

        with patch("load.DOCUMENTS_DIR", tmp_path):
            uploaded, failed = upload_documents_to_s3(s3_client)

        assert (uploaded, failed) == (1, 0)
        s3_client.upload_file.assert_called_once()

    def test_handles_upload_client_error(self, tmp_path):
        uid_folder = tmp_path / "App_001"
        uid_folder.mkdir()
        (uid_folder / "form.pdf").write_bytes(b"content")

        s3_client = Mock()
        s3_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "boom"}}, "PutObject")

        with patch("load.DOCUMENTS_DIR", tmp_path):
            uploaded, failed = upload_documents_to_s3(s3_client)

        assert (uploaded, failed) == (0, 1)


class TestMain:
    """Test the local-testing main() entry point."""

    def test_main_runs_without_error(self, tmp_path):
        pd.DataFrame({
            "area_name": ["Newham"], "uid": ["App/001"], "address": ["123"],
        }).to_csv(tmp_path / "area_318.csv", index=False)

        table = Mock()
        table.get_item.return_value = {}
        s3_client = Mock()

        with patch("load.DATA_DIR", tmp_path), \
                patch("load.DOCUMENTS_DIR", Path("/nonexistent/dir")), \
                patch("load.initialize_dynamodb", return_value=table), \
                patch("load.initialize_s3", return_value=s3_client):
            main()
