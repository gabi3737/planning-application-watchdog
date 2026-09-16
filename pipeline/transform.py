"""
Validate and transform planning application data.

Handles:
- Loading CSV data from data/ directory
- Standardizing null values to "N/A"
- Type casting columns to appropriate data types
- Validating data integrity
"""

import pandas as pd
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime

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
}

# Columns that should not be empty (besides app_state which can be N/A)
REQUIRED_COLUMNS = {"uid", "address",
                    "area_id", "area_name", "start_date", "url"}


def load_csv_data(csv_path: Path) -> Optional[pd.DataFrame]:
    """Load CSV data from file."""
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


def transform(csv_path: Path) -> Tuple[Optional[pd.DataFrame], dict]:
    """
    Complete transformation pipeline:
    1. Load CSV
    2. Standardize nulls
    3. Type cast columns
    4. Validate data

    Returns: (transformed_df, transformation_report)
    """
    logger.info(f"Starting transformation for {csv_path}")

    # Load
    df = load_csv_data(csv_path)
    if df is None:
        return None, {"error": "Failed to load CSV"}

    # Standardize nulls
    df = standardize_nulls(df)

    # Type cast
    df, casting_errors = typecast_columns(df)

    # Validate
    df, validation_report = validate_data(df)

    report = {
        "file": str(csv_path),
        "rows_processed": len(df),
        "type_casting_errors": casting_errors,
        "validation_report": validation_report,
    }

    logger.info(f"Transformation complete for {csv_path}")
    return df, report


def transform_all_files() -> Dict[str, Tuple[pd.DataFrame, dict]]:
    """Transform all CSV files in data/ directory."""
    results = {}

    if not DATA_DIR.exists():
        logger.error(f"Data directory not found: {DATA_DIR}")
        return results

    csv_files = list(DATA_DIR.glob("area_*.csv"))
    logger.info(f"Found {len(csv_files)} CSV files to transform")

    for csv_path in csv_files:
        df, report = transform(csv_path)
        results[csv_path.name] = (df, report)

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
