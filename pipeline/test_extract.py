"""Tests for extract module."""

from extract import (
    calculate_date_range,
    extract_from_record,
    fetch_applications,
    flatten_location,
    create_session,
    convert_url_to_documents_url,
    load_webpage,
    find_pdf_urls,
    get_pdf,
    upload_pdf_to_s3_or_local,
    download_documents,
    extract_all_areas,
    main,
)
import tempfile
import pandas as pd
from datetime import datetime
from unittest.mock import patch, Mock
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from requests.exceptions import HTTPError
from botocore.exceptions import ClientError
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


class TestFlattenLocation:
    """Test location flattening."""

    def test_none_location_returns_none_none(self):
        assert flatten_location(None) == (None, None)

    def test_non_dict_location_returns_none_none(self):
        assert flatten_location("not a dict") == (None, None)

    def test_x_y_keys(self):
        assert flatten_location({"x": 1.1, "y": 2.2}) == (1.1, 2.2)

    def test_coordinates_list(self):
        assert flatten_location({"coordinates": [3.3, 4.4]}) == (3.3, 4.4)

    def test_coordinates_wrong_length_falls_through(self):
        assert flatten_location({"coordinates": [3.3]}) == (None, None)

    def test_geometry_coordinates(self):
        location = {"geometry": {"coordinates": [5.5, 6.6]}}
        assert flatten_location(location) == (5.5, 6.6)

    def test_empty_dict_returns_none_none(self):
        assert flatten_location({}) == (None, None)


class TestCreateSession:
    """Test HTTP session creation."""

    def test_create_session_returns_session(self):
        session = create_session()
        assert session is not None


class TestConvertUrlToDocumentsUrl:
    """Test URL conversion for documents tab."""

    def test_converts_summary_to_documents(self):
        url = "https://example.com/app?activeTab=summary"
        assert convert_url_to_documents_url(
            url) == "https://example.com/app?activeTab=documents"

    def test_leaves_other_urls_unchanged(self):
        url = "https://example.com/app?activeTab=other"
        assert convert_url_to_documents_url(url) == url


class TestLoadWebpage:
    """Test webpage loading."""

    def test_returns_soup_on_success(self):
        mock_response = Mock()
        mock_response.text = "<html><body>hello</body></html>"
        mock_response.raise_for_status = Mock()
        mock_session = Mock()
        mock_session.get.return_value = mock_response

        soup = load_webpage("https://example.com", mock_session)
        assert isinstance(soup, BeautifulSoup)
        assert soup.body.text == "hello"

    def test_returns_none_on_http_error(self):
        mock_session = Mock()
        mock_session.get.side_effect = HTTPError("boom")

        assert load_webpage("https://example.com", mock_session) is None

    def test_returns_none_on_generic_error(self):
        mock_session = Mock()
        mock_session.get.side_effect = ValueError("boom")

        assert load_webpage("https://example.com", mock_session) is None


class TestFindPdfUrls:
    """Test PDF link extraction."""

    def test_finds_pdf_links(self):
        html = """
        <html><body>
        <a href="form.pdf">Application Form</a>
        <a href="page.html">Not a PDF</a>
        <a href="/docs/plan.PDF">Plan</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        urls = find_pdf_urls(soup, "https://example.com/base/")

        assert len(urls) == 2
        assert urls[0] == ("https://example.com/base/form.pdf",
                           "Application Form")
        assert urls[1] == ("https://example.com/docs/plan.PDF", "Plan")

    def test_returns_empty_list_when_no_pdfs(self):
        soup = BeautifulSoup(
            "<html><body><a href='page.html'>Page</a></body></html>", "html.parser")
        assert find_pdf_urls(soup, "https://example.com") == []


class TestGetPdf:
    """Test PDF downloading."""

    def test_returns_content_on_success(self):
        mock_response = Mock()
        mock_response.content = b"%PDF-1.4 fake content"
        mock_response.raise_for_status = Mock()
        mock_session = Mock()
        mock_session.get.return_value = mock_response

        result = get_pdf("https://example.com/form.pdf", mock_session)
        assert result == b"%PDF-1.4 fake content"

    def test_returns_none_on_error(self):
        mock_session = Mock()
        mock_session.get.side_effect = ValueError("boom")

        assert get_pdf("https://example.com/form.pdf", mock_session) is None


class TestUploadPdfToS3OrLocal:
    """Test PDF upload/save logic."""

    def test_saves_locally_when_use_s3_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("extract.USE_S3", False), \
                    patch("extract.DOCUMENTS_DIR", Path(tmpdir)):
                result = upload_pdf_to_s3_or_local(
                    b"content", "Newham/26/001", "form.pdf")

            assert result is True
            assert (Path(tmpdir) / "Newham_26_001" / "form.pdf").exists()

    def test_local_save_failure_returns_false(self):
        with patch("extract.USE_S3", False), \
                patch("pathlib.Path.mkdir", side_effect=OSError("boom")):
            result = upload_pdf_to_s3_or_local(
                b"content", "Newham/26/001", "form.pdf")

        assert result is False

    def test_uploads_to_s3_when_use_s3_true(self):
        mock_s3_client = Mock()
        with patch("extract.USE_S3", True), \
                patch("extract.get_s3_client", return_value=mock_s3_client):
            result = upload_pdf_to_s3_or_local(
                b"content", "Newham/26/001", "form.pdf")

        assert result is True
        mock_s3_client.put_object.assert_called_once()

    def test_s3_client_error_returns_false(self):
        mock_s3_client = Mock()
        mock_s3_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "boom"}}, "PutObject")
        with patch("extract.USE_S3", True), \
                patch("extract.get_s3_client", return_value=mock_s3_client):
            result = upload_pdf_to_s3_or_local(
                b"content", "Newham/26/001", "form.pdf")

        assert result is False


class TestDownloadDocuments:
    """Test document download orchestration."""

    def test_returns_false_when_no_url(self):
        assert download_documents(
            None, Mock(), "uid", force_pdf=False) is False

    def test_returns_false_when_webpage_fails_to_load(self):
        with patch("extract.load_webpage", return_value=None):
            result = download_documents(
                "https://example.com", Mock(), "uid", force_pdf=False)
        assert result is False

    def test_returns_false_when_no_pdfs_found(self):
        soup = BeautifulSoup("<html></html>", "html.parser")
        with patch("extract.load_webpage", return_value=soup):
            result = download_documents(
                "https://example.com", Mock(), "uid", force_pdf=False)
        assert result is False

    def test_downloads_form_pdf_when_found(self):
        soup = BeautifulSoup("<html></html>", "html.parser")
        pdf_links = [("https://example.com/other.pdf", "Other"),
                     ("https://example.com/applicationform.pdf", "Form")]
        with patch("extract.load_webpage", return_value=soup), \
                patch("extract.find_pdf_urls", return_value=pdf_links), \
                patch("extract.get_pdf", return_value=b"content"), \
                patch("extract.upload_pdf_to_s3_or_local", return_value=True):
            result = download_documents(
                "https://example.com", Mock(), "uid", force_pdf=False)
        assert result is True

    def test_returns_false_when_pdf_download_fails(self):
        soup = BeautifulSoup("<html></html>", "html.parser")
        pdf_links = [("https://example.com/form.pdf", "Form")]
        with patch("extract.load_webpage", return_value=soup), \
                patch("extract.find_pdf_urls", return_value=pdf_links), \
                patch("extract.get_pdf", return_value=None):
            result = download_documents(
                "https://example.com", Mock(), "uid", force_pdf=False)
        assert result is False

    def test_returns_false_when_upload_fails(self):
        soup = BeautifulSoup("<html></html>", "html.parser")
        pdf_links = [("https://example.com/form.pdf", "Form")]
        with patch("extract.load_webpage", return_value=soup), \
                patch("extract.find_pdf_urls", return_value=pdf_links), \
                patch("extract.get_pdf", return_value=b"content"), \
                patch("extract.upload_pdf_to_s3_or_local", return_value=False):
            result = download_documents(
                "https://example.com", Mock(), "uid", force_pdf=False)
        assert result is False


class TestExtractAllAreas:
    """Test extraction across all configured areas."""

    def test_extracts_records_into_dataframes(self, mock_app_response):
        with patch("extract.fetch_applications", return_value=[mock_app_response]):
            result = extract_all_areas("2026-09-01", "2026-09-15")

        assert isinstance(result, dict)
        assert len(result) == 3
        for df in result.values():
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 1

    def test_skips_areas_with_no_records(self):
        with patch("extract.fetch_applications", return_value=[]):
            result = extract_all_areas("2026-09-01", "2026-09-15")

        assert result == {}

    def test_defaults_date_range_when_not_given(self, mock_app_response):
        with patch("extract.fetch_applications", return_value=[mock_app_response]):
            result = extract_all_areas()

        assert len(result) == 3

    def test_downloads_pdfs_when_save_pdf_true(self, mock_app_response):
        with patch("extract.fetch_applications", return_value=[mock_app_response]), \
                patch("extract.create_session", return_value=Mock()), \
                patch("extract.download_documents", return_value=True) as mock_download:
            result = extract_all_areas(
                "2026-09-01", "2026-09-15", save_pdf=True, force_pdf=False)

        assert len(result) == 3
        assert mock_download.called


class TestMain:
    """Test the main entry-point wrapper."""

    def test_main_delegates_to_extract_all_areas(self):
        with patch("extract.extract_all_areas", return_value={"area_318": pd.DataFrame()}) as mock_extract:
            result = main("2026-09-01", "2026-09-15",
                          save_pdf=True, force_pdf=False)

        mock_extract.assert_called_once_with(
            "2026-09-01", "2026-09-15", True, False)
        assert "area_318" in result


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
