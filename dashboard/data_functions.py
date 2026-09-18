"""Functions to load AWS data for dashboard."""

import math
import os
import logging
import pandas as pd
import streamlit as st
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from curl_cffi import requests
from requests.exceptions import HTTPError

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
def get_sites(latitude: float, longitude: float, radius: int) -> list:
    """Fetches heritage sites within the specified radius of the given latitude and longitude."""
    base_url = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/0/"
    query = f"query?f=json&geometry={longitude},{latitude}&geometryType=esriGeometryPoint&where=1%3D1&outSR=4326&inSR=4326&distance={radius}&outFields=Name,Grade,Hyperlink&returnGeometry=true"
    url = base_url + query
    try:
        heritage_sites_data = requests.get(
            impersonate="chrome124", url=url).json()
    except HTTPError as err:
        logger.error(f"HTTP Error fetching heritage sites: {err}")
        return []
    if "features" not in heritage_sites_data:
        logger.error("Invalid data format received for heritage sites.")
        return []
    if len(heritage_sites_data["features"]) == 0:
        logger.info("No heritage sites found within the specified radius")
        return []
    return heritage_sites_data["features"]


@st.cache_data
def get_conservation_areas(latitude: float, longitude: float, radius: int) -> list:
    """Fetches conservation areas within the specified radius of the given latitude and longitude."""
    base_url = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/Conservation_Areas/FeatureServer/0/"
    query = f"query?f=geojson&geometry={longitude},{latitude}&geometryType=esriGeometryPoint&inSR=4326&outSR=4326&distance={radius}&where=1%3D1&outFields=NAME&returnGeometry=true"
    url = base_url + query
    try:
        conservation_areas_data = requests.get(
            impersonate="chrome124", url=url).json()
    except HTTPError as err:
        logger.error(f"HTTP Error fetching conservation areas: {err}")
        return []
    if "features" not in conservation_areas_data:
        logger.error("Invalid data format received for conservation areas.")
        return []
    if len(conservation_areas_data["features"]) == 0:
        logger.info("No conservation areas found within the specified radius")
        return []
    return conservation_areas_data["features"]


@st.cache_data
def load_application_data(_session: boto3.Session) -> pd.DataFrame:
    """Load planning application data from DynamoDB."""
    table_name = os.getenv(
        "PLANNING_TABLE_NAME", "c25-planning-data-db")

    try:
        dynamodb = _session.resource("dynamodb")
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


def get_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Extracts coordinates from the planning application DataFrame."""
    if "location_x" in df.columns and "location_y" in df.columns:
        if isinstance(df["location_x"].iloc[0], (float)) and isinstance(df["location_y"].iloc[0], (float)):
            return df[["location_x", "location_y"]].copy()
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


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the distance in meters between two coordinates using the Haversine formula."""
    R = 6371000  # Earth's radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    diff_phi = math.radians(lat2 - lat1)
    diff_long = math.radians(lon2 - lon1)

    a = math.sin(diff_phi/2)**2 + math.cos(phi1) * \
        math.cos(phi2) * math.sin(diff_long/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c
