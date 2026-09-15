"""Test Suite for document saving pipeline"""

from unittest.mock import patch, MagicMock
import pytest
from requests.exceptions import HTTPError
from save_documents import (
    create_session, convert_url_to_documents_url, load_webpage, find_pdf_urls, get_pdf)


def test_convert_url_to_documents_url_documents_case():
    url = "https://example.co.uk/applications?activeTab=documents"
    assert convert_url_to_documents_url(url) == url


def test_convert_url_to_documents_url_summary_case():
    url = "https://example.co.uk/applications?activeTab=summary"
    expected = "https://example.co.uk/applications?activeTab=documents"
    assert convert_url_to_documents_url(url) == expected


@patch("save_documents.requests.Session.get")
def test_load_webpage(mock_get):
    session = create_session()
    url = "https://example.co.uk/applications?activeTab=documents"
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = "<html></html>"
    soup = load_webpage(url, session)
    assert soup is not None


@patch("save_documents.requests.Session.get")
@patch("save_documents.logging")
def test_load_webpage_failure_case(mock_logging, mock_get):
    session = create_session()
    url = "https://example.co.uk/applications?activeTab=documents"
    mock_get.return_value.status_code = 404
    mock_get.return_value.text = "<html></html>"
    mock_get.return_value.raise_for_status.side_effect = HTTPError(
        "404 Not Found")
    result = load_webpage(url, session)
    assert result is None
    mock_logging.error.assert_called()


def test_find_pdf_urls():
    mock_soup = MagicMock()
    mock_soup.find_all.return_value = [
        {"href": "https://example.co.uk/applications/document1.pdf"},
        {"href": "https://example.co.uk/applications/document2.pdf"}
    ]
    url = "https://example.co.uk/applications?activeTab=documents"
    pdf_urls = find_pdf_urls(mock_soup, url)
    assert pdf_urls == [
        "https://example.co.uk/applications/document1.pdf",
        "https://example.co.uk/applications/document2.pdf"
    ]


def test_find_pdf_urls_empty_case():
    mock_soup = MagicMock()
    mock_soup.find_all.return_value = []
    url = "https://example.co.uk/applications?activeTab=documents"
    pdf_urls = find_pdf_urls(mock_soup, url)
    assert pdf_urls == []


@patch("save_documents.requests.Session.get")
def test_get_pdf(mock_get):
    session = create_session()
    url = "https://example.co.uk/applications/document1.pdf"
    mock_get.return_value.status_code = 200
    mock_get.return_value.content = b"%PDF-1.4"
    pdf_content = get_pdf(url, session)
    assert pdf_content == b"%PDF-1.4"


@patch("save_documents.requests.Session.get")
def test_get_pdf_failure_case(mock_get):
    session = create_session()
    url = "https://example.co.uk/applications?activeTab=documents"
    mock_get.return_value.status_code = 404
    mock_get.return_value.content = b"%PDF-1.4"
    mock_get.return_value.raise_for_status.side_effect = HTTPError(
        "404 Not Found")
    with pytest.raises(HTTPError):
        get_pdf(url, session)
