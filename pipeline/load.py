"""
Load planning application data from CSV files into DynamoDB.

Reads transformed CSV files from data/ directory and uploads to
DynamoDB table with partition key 'area' and sort key 'uid'.

Usage:
    python3 load.py
    python3 load.py --no-db
"""

import argparse
import logging
import boto3
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Tuple
from decimal import Decimal
from botocore.exceptions import ClientError

# Configuration
DATA_DIR = Path(__file__).parent / "data"
TABLE_NAME = "c25-planning-data-db"
PARTITION_KEY = "area"  # Maps to area_name
SORT_KEY = "uid"

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def initialize_dynamodb():
    """Initialize DynamoDB resource and client."""
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(TABLE_NAME)
        # Verify table exists
        table.load()
        logger.info(f"Connected to DynamoDB table: {TABLE_NAME}")
        return table
    except ClientError as e:
        logger.error(f"Failed to connect to DynamoDB: {e}")
        raise


def csv_row_to_dynamodb_item(row: pd.Series) -> Dict[str, Any]:
    """
    Convert a CSV row to a DynamoDB item.

    Handles type conversions and null values.
    """
    item = {}

    for col, value in row.items():
        # Skip NaN/null values
        if pd.isna(value):
            continue

        # Handle partition and sort keys
        if col == "area_name":
            item[PARTITION_KEY] = str(value)
        elif col == "uid":
            item[SORT_KEY] = str(value)
        else:
            # Convert numeric columns
            if col in ["area_id", "location_x", "location_y"]:
                try:
                    # Try to convert to number
                    if col == "area_id":
                        item[col] = int(value)
                    else:
                        # DynamoDB requires Decimal, not float
                        item[col] = Decimal(str(value))
                except (ValueError, TypeError):
                    item[col] = str(value)
            else:
                # Keep as string
                item[col] = str(value)

    # Ensure partition and sort keys exist
    if PARTITION_KEY not in item or SORT_KEY not in item:
        return None

    return item


def load_csv_file(table, csv_path: Path, no_db: bool = False) -> Tuple[int, int]:
    """
    Load a single CSV file into DynamoDB.

    Returns: (loaded_count, failed_count)
    """
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Loading {len(df)} records from {csv_path.name}")

        loaded_count = 0
        failed_count = 0

        for idx, row in df.iterrows():
            item = csv_row_to_dynamodb_item(row)

            if item is None:
                logger.warning(
                    f"Skipping row {idx + 1}: missing partition or sort key")
                failed_count += 1
                continue

            try:
                if not no_db:
                    table.put_item(Item=item)
                loaded_count += 1
            except ClientError as e:
                logger.error(f"Failed to load row {idx + 1}: {e}")
                failed_count += 1

        logger.info(f"  Loaded: {loaded_count}, Failed: {failed_count}")
        return loaded_count, failed_count

    except FileNotFoundError:
        logger.error(f"File not found: {csv_path}")
        return 0, 1
    except Exception as e:
        logger.error(f"Error loading {csv_path}: {e}")
        return 0, 1


def load_all_files(table, no_db: bool = False) -> Dict[str, Tuple[int, int]]:
    """
    Load all CSV files from data/ directory into DynamoDB.

    Returns: dict mapping filename to (loaded_count, failed_count)
    """
    results = {}

    if not DATA_DIR.exists():
        logger.error(f"Data directory not found: {DATA_DIR}")
        return results

    csv_files = sorted(DATA_DIR.glob("area_*.csv"))
    if not csv_files:
        logger.warning(f"No CSV files found in {DATA_DIR}")
        return results

    logger.info(f"Found {len(csv_files)} CSV files to load")

    if no_db:
        logger.info("Running in NO-DB mode - no data will be written")

    total_loaded = 0
    total_failed = 0

    for csv_path in csv_files:
        loaded, failed = load_csv_file(table, csv_path, no_db)
        results[csv_path.name] = (loaded, failed)
        total_loaded += loaded
        total_failed += failed

    logger.info(f"\nSummary:")
    logger.info(f"  Total loaded: {total_loaded}")
    logger.info(f"  Total failed: {total_failed}")

    return results


def main(no_db: bool = False):
    """Load all CSV data into DynamoDB."""
    logger.info(f"Loading planning data from {DATA_DIR} to {TABLE_NAME}")

    try:
        table = initialize_dynamodb()
        results = load_all_files(table, no_db)

        # Print summary
        if results:
            logger.info("\nLoad Summary by Area:")
            for filename, (loaded, failed) in results.items():
                logger.info(f"  {filename}: {loaded} loaded, {failed} failed")
        else:
            logger.warning("No files were processed")

    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load planning application data into DynamoDB")
    parser.add_argument("--no-db", action="store_true",
                        help="Simulate loading without writing to DynamoDB")
    args = parser.parse_args()

    main(no_db=args.no_db)
