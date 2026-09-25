"""Functions to load DynamoDB user data for notification system"""

import os

import boto3
import logging
from dotenv import load_dotenv
import pandas as pd
from datetime import date

EMAIL_HOST = "sl-coaches@proton.me"

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def create_boto3_session() -> boto3.Session:
    """Creates and returns a boto3 session using environment variables or Lambda role credentials."""
    region = os.getenv("AWS_REGION", "eu-west-2")
    key = os.getenv("ACCESS_KEY_ID")
    secret = os.getenv("SECRET_ACCESS_KEY")

    if key and secret:
        return boto3.Session(
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region,
        )

    # Fallback to instance/role credentials (used in Lambda)
    return boto3.Session(region_name=region)


def create_ses_session(session: boto3.Session) -> boto3.client:
    """Creates and returns an SES client using the provided boto3 session."""
    return session.client("ses")


def load_user_data(session: boto3.Session) -> pd.DataFrame:
    """Loads user data from DynamoDB and returns it as a pandas DataFrame."""
    user_data = os.getenv("USER_TABLE_NAME", "c25-planning-user-db")

    try:
        dynamodb = session.resource("dynamodb")
        table = dynamodb.Table(user_data)
        response = table.scan()
        data = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"])
            data.extend(response.get("Items", []))
        dataframe = pd.DataFrame(data)
        logging.info(f"Loaded {len(dataframe)} records from DynamoDB.")

        return dataframe

    except Exception as e:
        logging.error(f"Error loading user data from DynamoDB: {e}")
        raise


def get_active_emails(user_data_df: pd.DataFrame) -> pd.DataFrame:
    """Returns a dataframe of active user emails and area information."""
    if "email" not in user_data_df.columns or "active" not in user_data_df.columns or "area" not in user_data_df.columns:
        logging.error(
            "DataFrame must contain 'email', 'active', and 'area' columns.")
        raise ValueError(
            "DataFrame must contain 'email', 'active', and 'area' columns.")

    active_users_df = user_data_df.loc[user_data_df["active"] == True, [
        "email", "area"]]
    logging.info(f"Found {len(active_users_df)} active users.")

    return active_users_df


def load_planning_data(session: boto3.Session) -> pd.DataFrame:
    """Loads planning data from DynamoDB and returns it as a pandas DataFrame."""
    planning_data = os.getenv("PLANNING_TABLE_NAME", "c25-planning-data-db")

    try:
        dynamodb = session.resource("dynamodb")
        table = dynamodb.Table(planning_data)
        response = table.scan()
        data = response.get("Items", [])
        dataframe = pd.DataFrame(data)
        logging.info(f"Loaded {len(dataframe)} records from DynamoDB.")

        return dataframe

    except Exception as e:
        logging.error(f"Error loading planning data from DynamoDB: {e}")
        raise


def group_user_emails(active_emails_df: pd.DataFrame) -> pd.DataFrame:
    """Groups user emails by area and returns a dictionary with area as keys and list of emails as values."""
    if "email" not in active_emails_df.columns or "area" not in active_emails_df.columns:
        logging.error("DataFrame must contain 'email' and 'area' columns.")
        raise ValueError("DataFrame must contain 'email' and 'area' columns.")

    grouped_emails = active_emails_df.groupby(
        "email")["area"].apply(list).reset_index(name="areas")

    return grouped_emails


def get_recent_data(planning_data_df: pd.DataFrame) -> pd.DataFrame:
    """Returns a dataframe of planning data added today, yesterday, or the day before yesterday."""
    if "start_date" not in planning_data_df.columns:
        logging.error("DataFrame must contain 'start_date' column.")
        raise ValueError("DataFrame must contain 'start_date' column.")

    recent_dates = {date.today() - pd.Timedelta(days=offset)
                    for offset in range(3)}
    start_dates = pd.to_datetime(planning_data_df["start_date"]).dt.date
    recent_data_df = planning_data_df.loc[start_dates.isin(recent_dates)]
    logging.info(
        f"Found {len(recent_data_df)} records for today, yesterday, and the day before yesterday.")

    if recent_data_df.empty:
        logging.warning(
            "No planning data found for today, yesterday, and the day before yesterday.")

    return recent_data_df


def match_users_to_new_applications(grouped_emails_df: pd.DataFrame,
                                    recent_data_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Matches each user's areas of interest to recent new planning applications."""
    if "area" not in recent_data_df.columns:
        logging.error("DataFrame must contain 'area' column.")
        raise ValueError("DataFrame must contain 'area' column.")

    matches = {}
    for _, row in grouped_emails_df.iterrows():
        email = row["email"]
        areas = row["areas"]
        matching_applications = recent_data_df.loc[recent_data_df["area"].isin(
            areas)]
        matches[email] = matching_applications
        if not matching_applications.empty:
            logging.info(
                f"Found {len(matching_applications)} matching applications")
        else:
            logging.info(f"No matching applications found for {email}")

    return matches


def dataframe_to_html(application_df: pd.DataFrame) -> str:
    """Converts a DataFrame of applications to an HTML table."""
    if application_df.empty:
        return "<p>No new applications found.</p>"
    columns = [column for column in
               ['location_x', 'postcode', 'area', 'start_date', 'app_type', 'address',
                'location_y', 'url', 'uid', 'app_state', 'area_id', 'app_size']
               if column in application_df.columns]

    display_df = application_df[columns].copy()

    return display_df.to_html(index=False, escape=True, border=1)


def create_html_body(recipient: str, applications_df: pd.DataFrame) -> str:

    applications_html = dataframe_to_html(applications_df)
    return f"<p>Dear {recipient},</p><p>Here are the new planning applications matching your areas of interest:</p>{applications_html}"


def send_email(ses_client, sender: str, recipient: str, applications_df: pd.DataFrame) -> str:
    """"""
    if applications_df.empty:
        subject = "No new planning applications found"
    else:
        subject = (
            f"{len(applications_df)} new planning applications matching your areas of interest")

    html_body = create_html_body(recipient, applications_df)

    response = ses_client.send_email(
        Source=sender,
        Destination={'ToAddresses': [recipient]},
        Message={
            'Subject': {'Data': subject, 'Charset': 'UTF-8'},
            'Body': {'Html': {'Data': html_body, 'Charset': 'UTF-8'}},
        }
    )
    return response['MessageId']


def send_all_emails(session: boto3.session, matches: dict[str, pd.DataFrame], sender: str) -> dict[str, str]:

    ses_client = session.client('ses')
    message_ids = {}

    for recipient, applications_df in matches.items():
        try:
            message_id = send_email(
                ses_client, sender, recipient, applications_df)
            message_ids[recipient] = message_id
            logging.info(
                "Successfully sent email to %s with MessageId %s", recipient, message_id)
        except Exception as e:
            logging.error("Failed to send email to %s: %s", recipient, e)

    return message_ids


def main() -> dict[str, str]:
    session = create_boto3_session()

    user_data_df = load_user_data(session)
    active_users_df = get_active_emails(user_data_df)
    grouped_emails_df = group_user_emails(active_users_df)

    planning_data_df = load_planning_data(session)
    recent_data_df = get_recent_data(planning_data_df)

    notifications = match_users_to_new_applications(
        grouped_emails_df, recent_data_df)

    if not notifications:
        logging.info("No new planning applications to notify.")
        return {}
    return send_all_emails(session, notifications, sender=EMAIL_HOST)


def handler(event, context):
    """AWS Lambda entry point for the daily notification pipeline."""
    try:
        result = main()
        return {
            "statusCode": 200,
            "body": {
                "message": "Notifications sent successfully",
                "emails_sent": len(result),
            },
        }
    except Exception as e:
        logging.error("Notification pipeline failed: %s", e)
        return {
            "statusCode": 500,
            "body": {"message": str(e)},
        }


if __name__ == "__main__":

    main()
