# pylint: skip-file

"""Tests for notification module."""

from unittest.mock import patch, Mock
from datetime import date

import pytest
import pandas as pd

from notification import (
    load_user_data,
    get_active_emails,
    load_planning_data,
    group_user_emails,
    get_yesterday_data,
    match_users_to_new_applications,
    dataframe_to_html,
    create_html_body,
    send_email,
    send_all_emails,
    lambda_handler,
)


class TestLoadUserData:
    """Tests for load_user_data."""

    def test_loads_single_page(self):
        mock_table = Mock()
        mock_table.scan.return_value = {
            "Items": [{"email": "a@example.com", "active": True, "area": "Newham"}]}
        mock_session = Mock()
        mock_session.resource.return_value.Table.return_value = mock_table

        df = load_user_data(mock_session)

        assert len(df) == 1
        assert df.iloc[0]["email"] == "a@example.com"

    def test_paginates_with_last_evaluated_key(self):
        mock_table = Mock()
        mock_table.scan.side_effect = [
            {"Items": [{"email": "a@example.com"}],
                "LastEvaluatedKey": {"email": "a@example.com"}},
            {"Items": [{"email": "b@example.com"}]},
        ]
        mock_session = Mock()
        mock_session.resource.return_value.Table.return_value = mock_table

        df = load_user_data(mock_session)

        assert len(df) == 2
        assert mock_table.scan.call_count == 2

    def test_raises_on_error(self):
        mock_session = Mock()
        mock_session.resource.side_effect = Exception("boom")

        with pytest.raises(Exception):
            load_user_data(mock_session)


class TestGetActiveEmails:
    """Tests for get_active_emails."""

    def test_filters_active_users(self):
        df = pd.DataFrame({
            "email": ["a@example.com", "b@example.com"],
            "active": [True, False],
            "area": ["Newham", "Croydon"],
        })
        result = get_active_emails(df)

        assert len(result) == 1
        assert result.iloc[0]["email"] == "a@example.com"

    def test_raises_when_missing_columns(self):
        df = pd.DataFrame({"email": ["a@example.com"]})
        with pytest.raises(ValueError):
            get_active_emails(df)


class TestLoadPlanningData:
    """Tests for load_planning_data."""

    def test_loads_data(self):
        mock_table = Mock()
        mock_table.scan.return_value = {
            "Items": [{"uid": "App/1", "area": "Newham"}]}
        mock_session = Mock()
        mock_session.resource.return_value.Table.return_value = mock_table

        df = load_planning_data(mock_session)

        assert len(df) == 1
        assert df.iloc[0]["uid"] == "App/1"

    def test_raises_on_error(self):
        mock_session = Mock()
        mock_session.resource.side_effect = Exception("boom")

        with pytest.raises(Exception):
            load_planning_data(mock_session)


class TestGroupUserEmails:
    """Tests for group_user_emails."""

    def test_groups_areas_by_email(self):
        df = pd.DataFrame({
            "email": ["a@example.com", "a@example.com", "b@example.com"],
            "area": ["Newham", "Croydon", "Barnet"],
        })
        result = group_user_emails(df)

        row_a = result.loc[result["email"] == "a@example.com"].iloc[0]
        row_b = result.loc[result["email"] == "b@example.com"].iloc[0]
        assert set(row_a["areas"]) == {"Newham", "Croydon"}
        assert row_b["areas"] == ["Barnet"]

    def test_raises_when_missing_columns(self):
        df = pd.DataFrame({"email": ["a@example.com"]})
        with pytest.raises(ValueError):
            group_user_emails(df)


class TestGetYesterdayData:
    """Tests for get_yesterday_data."""

    def test_filters_to_yesterday(self):
        yesterday = (date.today() - pd.Timedelta(days=1)
                     ).strftime("%Y-%m-%d %H:%M:%S")
        df = pd.DataFrame({
            "start_date": [yesterday, "2020-01-01 00:00:00"],
            "area": ["Newham", "Croydon"],
        })
        result = get_yesterday_data(df)

        assert len(result) == 1
        assert result.iloc[0]["area"] == "Newham"

    def test_returns_empty_when_no_match(self):
        df = pd.DataFrame({
            "start_date": ["2020-01-01 00:00:00"],
            "area": ["Croydon"],
        })
        result = get_yesterday_data(df)
        assert result.empty

    def test_raises_when_missing_start_date_column(self):
        df = pd.DataFrame({"area": ["Newham"]})
        with pytest.raises(ValueError):
            get_yesterday_data(df)


class TestMatchUsersToNewApplications:
    """Tests for match_users_to_new_applications."""

    def test_matches_user_areas_to_applications(self):
        grouped = pd.DataFrame({
            "email": ["a@example.com", "b@example.com"],
            "areas": [["Newham"], ["Croydon"]],
        })
        applications = pd.DataFrame({
            "area": ["Newham", "Barnet"],
            "uid": ["App/1", "App/2"],
        })

        matches = match_users_to_new_applications(grouped, applications)

        assert len(matches["a@example.com"]) == 1
        assert matches["a@example.com"].iloc[0]["uid"] == "App/1"

    def test_includes_users_with_no_matches(self):
        grouped = pd.DataFrame({
            "email": ["a@example.com"],
            "areas": [["Newham"]],
        })
        applications = pd.DataFrame({
            "area": ["Barnet"],
            "uid": ["App/2"],
        })

        matches = match_users_to_new_applications(grouped, applications)

        assert "a@example.com" in matches
        assert matches["a@example.com"].empty

    def test_raises_when_missing_area_column(self):
        grouped = pd.DataFrame(
            {"email": ["a@example.com"], "areas": [["Newham"]]})
        applications = pd.DataFrame({"uid": ["App/1"]})

        with pytest.raises(ValueError):
            match_users_to_new_applications(grouped, applications)


class TestDataframeToHtml:
    """Tests for dataframe_to_html."""

    def test_returns_message_for_empty_dataframe(self):
        result = dataframe_to_html(pd.DataFrame())
        assert "No new applications found" in result

    def test_renders_known_columns_only(self):
        df = pd.DataFrame({
            "area": ["Newham"],
            "uid": ["App/1"],
            "unrelated_column": ["ignore me"],
        })
        result = dataframe_to_html(df)

        assert "<table" in result
        assert "Newham" in result
        assert "unrelated_column" not in result


class TestCreateHtmlBody:
    """Tests for create_html_body."""

    def test_includes_recipient_and_table(self):
        df = pd.DataFrame({"area": ["Newham"], "uid": ["App/1"]})
        result = create_html_body("a@example.com", df)

        assert "a@example.com" in result
        assert "Newham" in result

    def test_includes_no_applications_message_when_empty(self):
        result = create_html_body("a@example.com", pd.DataFrame())
        assert "No new applications found" in result


class TestSendEmail:
    """Tests for send_email."""

    def test_sends_email_with_matches(self):
        mock_ses = Mock()
        mock_ses.send_email.return_value = {"MessageId": "msg-1"}
        df = pd.DataFrame({"area": ["Newham"], "uid": ["App/1"]})

        message_id = send_email(
            mock_ses, "sender@example.com", "recipient@example.com", df)

        assert message_id == "msg-1"
        call_kwargs = mock_ses.send_email.call_args.kwargs
        assert call_kwargs["Source"] == "sender@example.com"
        assert call_kwargs["Destination"] == {
            "ToAddresses": ["recipient@example.com"]}
        assert "1 new planning applications" in call_kwargs["Message"]["Subject"]["Data"]

    def test_sends_no_applications_subject_when_empty(self):
        mock_ses = Mock()
        mock_ses.send_email.return_value = {"MessageId": "msg-2"}

        send_email(mock_ses, "sender@example.com",
                   "recipient@example.com", pd.DataFrame())

        call_kwargs = mock_ses.send_email.call_args.kwargs
        assert call_kwargs["Message"]["Subject"]["Data"] == "No new planning applications found"


class TestSendAllEmails:
    """Tests for send_all_emails."""

    def test_sends_to_every_recipient(self):
        mock_ses = Mock()
        mock_ses.send_email.return_value = {"MessageId": "msg-1"}
        mock_session = Mock()
        mock_session.client.return_value = mock_ses

        matches = {
            "a@example.com": pd.DataFrame({"area": ["Newham"], "uid": ["App/1"]}),
            "b@example.com": pd.DataFrame(),
        }

        result = send_all_emails(mock_session, matches, "sender@example.com")

        assert result == {"a@example.com": "msg-1", "b@example.com": "msg-1"}
        assert mock_ses.send_email.call_count == 2

    def test_continues_after_one_failure(self):
        mock_ses = Mock()
        mock_ses.send_email.side_effect = [
            Exception("boom"), {"MessageId": "msg-2"}]
        mock_session = Mock()
        mock_session.client.return_value = mock_ses

        matches = {
            "a@example.com": pd.DataFrame({"area": ["Newham"], "uid": ["App/1"]}),
            "b@example.com": pd.DataFrame({"area": ["Croydon"], "uid": ["App/2"]}),
        }

        result = send_all_emails(mock_session, matches, "sender@example.com")

        assert "a@example.com" not in result
        assert result["b@example.com"] == "msg-2"


class TestLambdaHandler:
    """Tests for lambda_handler."""

    @patch("notification.main")
    def test_returns_200_on_success(self, mock_main):
        mock_main.return_value = {"a@example.com": "msg-1"}

        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        assert response["body"]["emails_sent"] == 1

    @patch("notification.main")
    def test_returns_500_on_failure(self, mock_main):
        mock_main.side_effect = Exception("boom")

        response = lambda_handler({}, None)

        assert response["statusCode"] == 500
        assert "boom" in response["body"]["message"]
