"""
Test suite for AI summary functions.
"""
from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError
from ai_summary_functions import (create_boto3_session, load_document, load_data,
                                  create_openai_client, summarise_document)


@patch("os.getenv")
def test_create_boto3_session(mock_getenv):
    """Test that create_boto3_session raises ValueError when credentials are not set."""
    mock_getenv.return_value = None
    with pytest.raises(ValueError):
        session = create_boto3_session()


@patch("ai_summary_functions.boto3.Session")
def test_load_document_invalid_bucket_name(mock_session):
    """Test that load_document returns None when the bucket does not exist."""
    # Mock the S3 client to raise NoSuchBucket exception
    mock_s3_client = mock_session.return_value.client.return_value
    mock_s3_client.list_objects.side_effect = mock_s3_client.exceptions.NoSuchBucket({
    }, "")

    result = load_document(mock_session.return_value, "sample_uid")
    assert result is None


@patch("ai_summary_functions.boto3.Session")
def test_load_document_uid_not_found(mock_session):
    """Test that load_document returns None when UID is not found in S3."""
    # Mock the S3 client
    mock_s3_client = mock_session.return_value.client.return_value

    # Mock list_objects to return objects that don't match the UID
    mock_s3_client.list_objects.return_value = {
        "Contents": [
            {"Key": "documents/example/1.pdf"},
            {"Key": "documents/example/2.pdf"}
        ]
    }

    # Call the function with a UID that won't match
    result = load_document(mock_session.return_value, "non_existent_uid")

    # Assert that None is returned
    assert result is None


@patch("ai_summary_functions.boto3.Session")
def test_load_document_uid_found(mock_session):
    """Test that load_document returns PDF content when UID is found."""
    mock_s3_client = mock_session.return_value.client.return_value

    # Mock list_objects to return a matching file
    mock_s3_client.list_objects.return_value = {
        "Contents": [
            {"Key": "documents/Greenwich_26_2646_SD.pdf"}
        ]
    }

    # Mock the get_object response
    mock_s3_client.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=b"PDF content here"))
    }

    result = load_document(mock_session.return_value, "Greenwich_26_2646_SD")

    assert result == b"PDF content here"


@patch("ai_summary_functions.boto3.Session")
def test_load_data_invalid_table_name(mock_session):
    """Test that load_data returns an empty dictionary when the table does not exist."""
    mock_dynamodb_client = mock_session.return_value.client.return_value

    error_response = {
        'Error': {'Code': 'ResourceNotFoundException', 'Message': 'Table not found'}}
    mock_dynamodb_client.get_item.side_effect = ClientError(
        error_response, 'GetItem')

    result = load_data(mock_session.return_value, "sample_uid")
    assert result == {}


@patch("ai_summary_functions.os.getenv")
def test_create_openai_client_missing_api_key(mock_getenv):
    """Test that create_openai_client raises ValueError when OPENAI_API_KEY is not set."""
    mock_getenv.return_value = None
    with pytest.raises(ValueError):
        create_openai_client()


def test_summarise_document_empty_document():
    """Test that summarise_document returns an empty summary when document content is empty."""
    mock_openai_client = MagicMock()
    result = summarise_document(mock_openai_client, "")
    assert result == ""


@patch("ai_summary_functions.OpenAI")
def test_summarise_document_invalid_response(mock_openai, caplog):
    """Test that summarise_document handles errors gracefully."""
    # Create a mock OpenAI instance
    mock_openai_client = MagicMock()
    mock_openai.return_value = mock_openai_client

    # Mock the API to raise an exception
    mock_openai_client.beta.chat.completions.create.side_effect = Exception(
        "API Error")

    result = summarise_document(mock_openai_client, "Sample document content")

    assert result == ""
    assert "Error summarising document: " in caplog.text
