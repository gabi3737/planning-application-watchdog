"""
Validate and transform planning application data.

Handles:
- Accepting DataFrames from extract.py
- Standardizing null values to "N/A"
- Type casting columns to appropriate data types
- Validating data integrity
- Returning transformed DataFrames
"""

import pandas as pd
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime
import os
import io
import time
import boto3
from botocore.exceptions import ClientError
from openai import OpenAI
import pdfplumber
from dotenv import load_dotenv
load_dotenv()


DATA_DIR = Path(__file__).parent / "data"

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define expected schema with data types
SCHEMA = {
    "uid": "string",
    "address": "string",
    "postcode": "string",
    "app_type": "string",
    "app_state": "string",
    "app_size": "string",
    "area_id": "int",
    "area_name": "string",
    "start_date": "datetime",
    "url": "string",
    "location_x": "float",
    "location_y": "float",
    "summary": "string",
}

# Columns that should not be empty (besides app_state which can be N/A)
REQUIRED_COLUMNS = {"uid", "address",
                    "area_id", "area_name", "start_date", "url"}

# AWS Configuration
S3_BUCKET = os.getenv("PLANNING_FILES_BUCKET", "c25-planning-files-bucket")
AWS_REGION = os.getenv("AWS_REGION", "eu-west-2")

# Global clients (lazy-loaded)
_s3_session = None
_openai_client = None

# Note: Summary generation functions moved to load.py for deferred execution
# This allows summaries to be generated only after comparing with existing records
# to avoid unnecessary API calls


def get_boto3_session() -> boto3.Session:
    """Creates and returns a boto3 session using environment variables."""
    global _s3_session
    if _s3_session is not None:
        return _s3_session

    if not os.getenv("ACCESS_KEY_ID") or not os.getenv("SECRET_ACCESS_KEY"):
        logger.error(
            "ACCESS_KEY_ID and SECRET_ACCESS_KEY must be set in the environment.")
        raise ValueError(
            "ACCESS_KEY_ID and SECRET_ACCESS_KEY must be set in the environment.")

    _s3_session = boto3.Session(
        aws_access_key_id=os.getenv("ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("SECRET_ACCESS_KEY"),
        region_name=AWS_REGION
    )
    logger.info("Initialized boto3 session for S3 access")
    return _s3_session


def get_openai_client() -> OpenAI:
    """Create and return an OpenAI client using the API key from environment variables."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY must be set in the environment.")
        raise ValueError("OPENAI_API_KEY must be set in the environment.")

    _openai_client = OpenAI(
        api_key=api_key, base_url="https://api.openai.com/v1")
    logger.info("Initialized OpenAI client")
    return _openai_client


def fetch_pdf_from_s3(session: boto3.Session, uid: str) -> Optional[bytes]:
    """Fetch a PDF document from S3 using the UID.

    Args:
        session: boto3 Session
        uid: Application UID (e.g., "Greenwich_26_2646_SD")

    Returns:
        PDF content as bytes, or None if not found
    """
    s3_client = session.client("s3", region_name=AWS_REGION)
    try:
        # List objects with prefix matching the UID
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=S3_BUCKET,
            Prefix=f"documents/{uid}/"
        )

        for page in pages:
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".pdf") or obj["Key"].endswith(".PDF"):
                    logger.debug(f"Found PDF in S3: {obj['Key']}")
                    response = s3_client.get_object(
                        Bucket=S3_BUCKET, Key=obj["Key"])
                    pdf_content = response["Body"].read()
                    logger.info(f"Successfully fetched PDF for {uid} from S3")
                    return pdf_content

        logger.debug(f"No PDF found in S3 for {uid}")
        return None
    except ClientError as e:
        logger.warning(f"Error fetching PDF from S3 for {uid}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error fetching PDF for {uid}: {e}")
        return None


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF file represented as bytes.

    Args:
        pdf_bytes: PDF content as bytes

    Returns:
        Extracted text as string
    """
    try:
        extracted = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    extracted.append(text)
        result = "\n".join(extracted)
        logger.debug(f"Extracted {len(result)} characters from PDF")
        return result
    except Exception as e:
        logger.warning(f"Error extracting text from PDF: {e}")
        return ""


def generate_summary(openai_client: OpenAI, pdf_text: str, metadata_dict: dict) -> str:
    """Generate an AI summary of the planning application.

    Args:
        openai_client: OpenAI client
        pdf_text: Extracted PDF text (can be empty string)
        metadata_dict: Dictionary with application metadata

    Returns:
        Summary string (or empty string on error)
    """
    try:
        system_role = """
        You are a precise AI assistant which intakes both general information
        and PDF documents on planning applications. You provide a clear plain-English
        summary of the information based on the prompt given."""

        prompt = f"""
        Analyze the following text from a PDF document and related information. Then create
         a concise summary of what is being proposed and why it might matter. The summary
         should use clear, simple language, stay under 100 words, and contain no links.
         Do not add any bias on what you say, just factually summarise what the application is about.

        The information is stored as a dictionary with keys:
        - "address": The address of the planning application.
        - "app_size": Size of the planning application.
            - Large: Major, large scale developments
            - Medium: Other applications involving multiple dwellings
            - Small: All others
        - "app_state": Decision status for the application.
            - Undecided: The application is currently active, no decision has been made
            - Permitted: The application was approved
            - Conditions: The application was approved, but conditions were imposed
            - Rejected: The application was refused
            - Withdrawn: The application was withdrawn before a decision was taken
            - Referred: The application was referred to government or to another authority
            - Unresolved: The application is no longer active but no decision was made eg split decision
            - Other: Status not known
        - "app_type": Type of the planning application.
            - Full: Full and householder planning applications
            - Outline: Proposals prior to a full application, including assessments, scoping opinions, outline applications etc
            - Amendment: Amendments or alterations arising from existing or previous applications
            - Conditions: Discharge of conditions imposed on existing applications
            - Heritage: Conservation issues and listed buildings
            - Trees: Tree and hedge works
            - Advertising: Advertising and signs
            - Telecoms: Telecommunications including phone masts
            - Other: All other types eg agricultural, electrical
        - "area": The area where the planning application is located.
        - "url": The URL where more information about the planning application can be found.
    
        Application Information:
        {metadata_dict}

        PDF File:
        {pdf_text}
        """

        response = openai_client.beta.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": system_role
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        summary = response.choices[0].message.content
        logger.info(f"🤖 OpenAI Response: {summary}")
        return summary
    except Exception as e:
        logger.warning(f"Error generating summary with OpenAI: {e}")
        return ""


def generate_record_summary(session: boto3.Session, openai_client: OpenAI, row_data: pd.Series) -> str:
    """Generate a summary for a single planning application record.

    Fetches PDF from S3, extracts text, and calls OpenAI API.
    Falls back to metadata-only summary if PDF not found.

    Args:
        session: boto3 Session
        openai_client: OpenAI client
        row_data: Series containing row data with uid, address, app_type, etc.

    Returns:
        Summary string (or empty string on error)
    """
    try:
        # Build metadata dictionary from row
        metadata_dict = {
            "address": str(row_data.get("address", "N/A")),
            "app_type": str(row_data.get("app_type", "N/A")),
            "app_state": str(row_data.get("app_state", "N/A")),
            "app_size": str(row_data.get("app_size", "N/A")),
            "area": str(row_data.get("area_name", "N/A")),
            "url": str(row_data.get("url", "N/A")),
        }

        # Attempt to fetch PDF from S3
        uid = str(row_data.get("uid", ""))
        pdf_text = ""

        if uid and uid != "N/A":
            pdf_bytes = fetch_pdf_from_s3(session, uid)
            if pdf_bytes:
                pdf_text = extract_pdf_text(pdf_bytes)

        # Generate summary (works with or without PDF text)
        summary = generate_summary(openai_client, pdf_text, metadata_dict)
        return summary

    except Exception as e:
        logger.error(f"Error generating record summary: {e}")
        return ""


def load_csv_data(csv_path: Path) -> Optional[pd.DataFrame]:
    """Load CSV data from file (for local testing only)."""
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded {len(df)} records from {csv_path}")
        return df
    except FileNotFoundError:
        logger.error(f"File not found: {csv_path}")
        return None
    except Exception as e:
        logger.error(f"Error loading CSV {csv_path}: {e}")
        return None


def transform_dataframe(df: pd.DataFrame, area_name: str) -> Tuple[pd.DataFrame, dict]:
    """
    Transform a single DataFrame through validation pipeline.

    Returns: (transformed_df, report)
    """
    if df is None or df.empty:
        logger.error(f"Cannot transform empty dataframe for {area_name}")
        return df, {"error": "Empty dataframe"}

    logger.info(f"Starting transformation for {area_name} ({len(df)} records)")

    # Standardize nulls
    df = standardize_nulls(df)
    # Ensure sequential index for safe column assignment
    df = df.reset_index(drop=True)

    # Initialize summary column with empty strings (will be populated later)
    if "summary" not in df.columns:
        df["summary"] = ""
        logger.debug("Initialized summary column with empty strings")

    # Type cast
    df, casting_errors = typecast_columns(df)

    # Validate (summary will be generated later in load stage if needed)
    df, validation_report = validate_data(df)

    report = {
        "area_name": area_name,
        "rows_processed": len(df),
        "type_casting_errors": casting_errors,
        "summary_errors": 0,  # Summaries generated in load stage
        "validation_report": validation_report,
    }

    logger.info(f"Transformation complete for {area_name}")
    return df, report


def transform_dataframes(dfs_dict: Dict[str, pd.DataFrame]) -> Tuple[Dict[str, pd.DataFrame], Dict[str, dict]]:
    """
    Transform all DataFrames through validation pipeline.

    Args:
        dfs_dict: Dictionary mapping area_name to DataFrame

    Returns:
        (transformed_dfs_dict, reports_dict)
    """
    transformed_dfs = {}
    reports = {}

    for area_name, df in dfs_dict.items():
        transformed_df, report = transform_dataframe(df, area_name)
        transformed_dfs[area_name] = transformed_df
        reports[area_name] = report

    return transformed_dfs, reports


def standardize_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Replace null/empty values with 'N/A' in all columns."""
    df = df.copy()
    df = df.fillna("N/A")
    # Also handle empty strings and whitespace-only strings
    for col in df.columns:
        # Handle both object and string dtypes
        if df[col].dtype in ["object", "string"]:
            df[col] = df[col].astype(str).apply(
                lambda x: "N/A" if x.strip() == "" else x
            )
    logger.info("Standardized null values to 'N/A'")
    return df


def typecast_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, list]:
    """
    Type cast columns to appropriate data types.
    Returns: (transformed_df, list_of_errors)
    """
    errors = []
    df = df.copy()

    for col, dtype in SCHEMA.items():
        if col not in df.columns:
            errors.append(f"Missing column: {col}")
            continue

        try:
            if dtype == "int":
                df[col] = pd.to_numeric(
                    df[col], errors="coerce").fillna(-1).astype("int")
            elif dtype == "float":
                df[col] = pd.to_numeric(
                    df[col], errors="coerce").fillna(0.0).astype("float")
            elif dtype == "datetime":
                df[col] = pd.to_datetime(df[col], errors="coerce")
                # Fill NaT (Not a Time) with a default date string and convert back to datetime
                df.loc[df[col].isna(), col] = pd.Timestamp("1970-01-01")
            elif dtype == "string":
                df[col] = df[col].astype("string")
        except Exception as e:
            errors.append(f"Error casting column {col} to {dtype}: {e}")

    if errors:
        logger.warning(f"Type casting errors: {errors}")
    else:
        logger.info("All columns successfully type cast")

    return df, errors


def validate_required_fields(df: pd.DataFrame) -> list:
    """
    Validate that required fields are not null/N/A.
    Returns: list of validation errors
    """
    errors = []

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            errors.append(f"Missing required column: {col}")
            continue

        null_count = (df[col] == "N/A").sum()
        if null_count > 0:
            error_msg = f"Column '{col}' has {null_count} missing values (marked as N/A)"
            errors.append(error_msg)
            logger.warning(error_msg)

    return errors


def validate_coordinate_ranges(df: pd.DataFrame) -> list:
    """
    Validate that location coordinates are within reasonable ranges.
    Returns: list of validation errors
    """
    errors = []

    # UK coordinates range approximately: -8 to 2 (longitude), 50 to 59 (latitude)
    if "location_x" in df.columns:
        invalid_x = df[(df["location_x"] != 0.0) & (
            (df["location_x"] < -8) | (df["location_x"] > 2))]
        if len(invalid_x) > 0:
            error_msg = f"Column 'location_x' has {len(invalid_x)} values outside UK range"
            errors.append(error_msg)
            logger.warning(error_msg)

    if "location_y" in df.columns:
        invalid_y = df[(df["location_y"] != 0.0) & (
            (df["location_y"] < 50) | (df["location_y"] > 59))]
        if len(invalid_y) > 0:
            error_msg = f"Column 'location_y' has {len(invalid_y)} values outside UK range"
            errors.append(error_msg)
            logger.warning(error_msg)

    return errors


def validate_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """
    Run all validation checks on the dataframe.
    Returns: (validated_df, validation_report)
    """
    if df is None or df.empty:
        logger.error("Cannot validate empty dataframe")
        return df, {"total_errors": 1, "error_details": ["Empty dataframe"]}

    validation_report = {
        "total_rows": len(df),
        "required_field_errors": validate_required_fields(df),
        "coordinate_errors": validate_coordinate_ranges(df),
    }

    total_errors = (
        len(validation_report["required_field_errors"]) +
        len(validation_report["coordinate_errors"])
    )

    validation_report["total_errors"] = total_errors

    if total_errors == 0:
        logger.info(f"Validation passed for {len(df)} records")
    else:
        logger.warning(
            f"Validation found {total_errors} issues in {len(df)} records")

    return df, validation_report


def generate_summaries_for_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """
    Generate AI summaries for all records in a DataFrame.

    Args:
        df: DataFrame with planning application data

    Returns:
        (df_with_summaries, error_count)
    """
    if df is None or df.empty:
        logger.warning("Cannot generate summaries for empty dataframe")
        return df, 0

    # Check if summary generation is disabled
    if SKIP_SUMMARY:
        logger.info(
            "Summary generation disabled (SKIP_SUMMARY=True). Using empty summaries.")
        df["summary"] = ""
        return df, 0

    try:
        session = get_boto3_session()
        openai_client = get_openai_client()
    except ValueError as e:
        logger.error(f"Cannot initialize clients for summary generation: {e}")
        # Add empty summary column and return
        df["summary"] = ""
        return df, len(df)

    summaries_dict = {}
    error_count = 0
    start_time = time.time()
    record_num = 0

    for idx, row in df.iterrows():
        record_num += 1
        try:
            uid = str(row.get("uid", ""))
            logger.info(
                f"  [{record_num}/{len(df)}] Generating summary for {uid}...")

            summary = generate_record_summary(session, openai_client, row)
            summaries_dict[idx] = summary
            logger.info(
                f"      ✅ Summary stored for index {idx}: {summary[:80]}...")

        except Exception as e:
            logger.error(f"Error generating summary for row {idx}: {e}")
            summaries_dict[idx] = ""
            error_count += 1

    elapsed = time.time() - start_time

    # Map summaries to dataframe using index to ensure correct alignment
    df["summary"] = df.index.map(lambda idx: summaries_dict.get(idx, ""))
    # Re-cast to string dtype to match SCHEMA and prevent silent skipping in load stage
    df["summary"] = df["summary"].astype("string")

    # Validate summary column integrity before passing to load stage
    assert "summary" in df.columns, "Summary column missing after generation"
    assert df["summary"].dtype == "string", f"Summary dtype is {df['summary'].dtype}, expected 'string'"
    null_count = df["summary"].isna().sum()
    assert null_count == 0, f"Summary column has {null_count} NaN/pd.NA values"

    logger.info(
        f"Summary generation complete: {len(df)} records in {elapsed:.1f}s ({error_count} errors)")
    logger.info(
        f"✓ Summary column validated: {len(df)} rows, all non-null, dtype=string")

    return df, error_count


def transform_all_files() -> Dict[str, Tuple[pd.DataFrame, dict]]:
    """Transform all CSV files in data/ directory (for local testing only)."""
    results = {}

    if not DATA_DIR.exists():
        logger.error(f"Data directory not found: {DATA_DIR}")
        return results

    csv_files = list(DATA_DIR.glob("area_*.csv"))
    logger.info(f"Found {len(csv_files)} CSV files to transform")

    for csv_path in csv_files:
        df = load_csv_data(csv_path)
        if df is not None:
            area_name = csv_path.stem  # e.g., "area_318"
            transformed_df, report = transform_dataframe(df, area_name)
            results[csv_path.name] = (transformed_df, report)

    return results


if __name__ == "__main__":
    # Example: Transform all files
    results = transform_all_files()
    for filename, (df, report) in results.items():
        print(f"\n{filename}:")
        print(f"  Rows processed: {report['rows_processed']}")
        print(f"  Total errors: {report['validation_report']['total_errors']}")
        if report['validation_report']['total_errors'] > 0:
            print(f"  Errors: {report['validation_report']}")
