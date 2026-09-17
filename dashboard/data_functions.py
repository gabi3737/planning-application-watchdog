"""Functions to load AWS data for dashboard."""

import os
import logging
import pandas as pd
import streamlit as st
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")

logger = logging.getLogger(__name__)


def create_boto3_session() -> boto3.Session:
    """Creates and returns a boto3 session using environment variables for AWS credentials and region."""
    if not os.getenv("ACCESS_KEY_ID") or not os.getenv("SECRET_ACCESS_KEY"):
        logging.error(
            "ACCESS_KEY_ID and SECRET_ACCESS_KEY must be set in the environment.")
        raise ValueError(
            "ACCESS_KEY_ID and SECRET_ACCESS_KEY must be set in the environment.")
    return boto3.Session(
        aws_access_key_id=os.getenv("ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "eu-west-2")
    )


@st.cache_data
def load_application_data(session: boto3.Session) -> pd.DataFrame:
    """Load planning application data from DynamoDB."""
    table_name = os.getenv(
        "PLANNING_TABLE_NAME", "c25-planning-data-db")

    try:
        dynamodb = session.resource("dynamodb")
        table = dynamodb.Table(table_name)

        response = table.scan()
        items = response.get("Items", [])

        # Ensures all data from DynamoDB is retrieved for scans exceeding 1MB
        while "LastEvaluatedKey" in response:
            response = table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        if not items:
            st.info("⚠️ No planning applications found in the database.")
            return pd.DataFrame()

        df = pd.DataFrame(items)

        # Convert numeric object/Decimal types from DynamoDB to standard float64
        numeric_cols = ["area_id", "location_x", "location_y"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["start_date"] = pd.to_datetime(
            df["start_date"],
            errors="coerce")

        return df

    except (ClientError, BotoCoreError) as aws_err:
        logger.error(f"AWS DynamoDB fetch error: {aws_err}")
        st.error(
            "⚠️ Unable to load data from AWS DynamoDB. Please verify network connectivity and IAM task permissions."
        )
        return pd.DataFrame()

    except Exception as err:
        logger.error(f"Unexpected error loading dashboard data: {err}")
        st.error(
            "⚠️ An unexpected error occurred while processing planning application data.")
        return pd.DataFrame()


def set_s3_client(session: boto3.Session) -> boto3.client:
    """Sets up the S3 client using credentials from the provided boto3 session."""
    s3 = session.client(
        "s3")
    return s3


def load_application_documents(s3_client: boto3.client, bucket_name: str, uid: str) -> None:
    """Downloads documents from a specific application UID in the S3 Bucket."""
    # Very likely to not work
    objects = s3_client.list_objects(Bucket=bucket_name)
    file_found = False
    for folder in objects.get("Contents", []):
        if folder["Key"].endswith(uid):
            s3_client.download_file(
                bucket_name, folder["Key"], f"./documents/{folder['Key']}")
            file_found = True

    if not file_found:
        raise FileNotFoundError(
            f"No documents found for application UID '{uid}' in bucket '{bucket_name}'.")


def load_csv_data() -> pd.DataFrame:
    # Postcode column for CSV data remains invalid
    ...
