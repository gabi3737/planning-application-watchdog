"""
Load planning application data from CSV files into DynamoDB and upload documents to S3.

Reads transformed CSV files from data/ directory and uploads to
DynamoDB table with partition key 'area' and sort key 'uid'.

Also uploads all PDF documents from documents/ subfolders to S3 bucket,
organized by UID: s3://c25-planning-files-bucket/Documents/{uid}/{filename}

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
DOCUMENTS_DIR = Path(__file__).parent / "documents"
TABLE_NAME = "c25-planning-data-db"
S3_BUCKET = "c25-planning-files-bucket"
S3_PREFIX = "Documents"
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


def initialize_s3():
    """Initialize S3 client."""
    try:
        s3_client = boto3.client('s3')
        # Verify bucket exists by listing objects (will throw error if bucket doesn't exist)
        s3_client.head_bucket(Bucket=S3_BUCKET)
        logger.info(f"Connected to S3 bucket: {S3_BUCKET}")
        return s3_client
    except ClientError as e:
        logger.error(f"Failed to connect to S3 bucket: {e}")
        raise


def csv_row_to_dynamodb_item(row: pd.Series) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Convert a CSV row to DynamoDB keys and attributes.

    Returns: (key_dict, attributes_dict) for use with update_item()
    key_dict contains partition and sort keys
    attributes_dict contains all other attributes
    """
    keys = {}
    attributes = {}

    for col, value in row.items():
        # Skip NaN/null values
        if pd.isna(value):
            continue

        # Handle partition and sort keys
        if col == "area_name":
            keys[PARTITION_KEY] = str(value)
        elif col == "uid":
            keys[SORT_KEY] = str(value)
        else:
            # Convert numeric columns
            if col in ["area_id", "location_x", "location_y"]:
                try:
                    # Try to convert to number
                    if col == "area_id":
                        attributes[col] = int(value)
                    else:
                        # DynamoDB requires Decimal, not float
                        attributes[col] = Decimal(str(value))
                except (ValueError, TypeError):
                    attributes[col] = str(value)
            else:
                # Keep as string
                attributes[col] = str(value)

    # Ensure partition and sort keys exist
    if PARTITION_KEY not in keys or SORT_KEY not in keys:
        return None, None

    return keys, attributes


def load_csv_file(table, csv_path: Path, no_db: bool = False) -> Tuple[int, int, int]:
    """
    Load a single CSV file into DynamoDB.

    Returns: (created_count, updated_count, failed_count)
    """
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Loading {len(df)} records from {csv_path.name}")

        created_count = 0
        updated_count = 0
        failed_count = 0

        for idx, row in df.iterrows():
            keys, attributes = csv_row_to_dynamodb_item(row)

            if keys is None:
                logger.warning(
                    f"Skipping row {idx + 1}: missing partition or sort key")
                failed_count += 1
                continue

            try:
                if not no_db:
                    # Check if record already exists
                    existing = table.get_item(Key=keys)
                    is_update = "Item" in existing

                    # Build update expression to set all attributes
                    # DynamoDB reserved keywords need to be mapped using ExpressionAttributeNames
                    update_parts = []
                    expr_values = {}
                    expr_names = {}
                    for i, (attr_name, attr_value) in enumerate(attributes.items()):
                        placeholder = f"#attr{i}"
                        update_parts.append(f"{placeholder} = :val{i}")
                        expr_values[f":val{i}"] = attr_value
                        expr_names[placeholder] = attr_name

                    if update_parts:
                        update_expr = "SET " + ", ".join(update_parts)
                        table.update_item(
                            Key=keys,
                            UpdateExpression=update_expr,
                            ExpressionAttributeNames=expr_names,
                            ExpressionAttributeValues=expr_values
                        )
                    else:
                        # No attributes to update, just ensure key exists
                        table.update_item(
                            Key=keys,
                            UpdateExpression="SET #pk = :pk",
                            ExpressionAttributeNames={"#pk": PARTITION_KEY},
                            ExpressionAttributeValues={
                                ":pk": keys[PARTITION_KEY]}
                        )

                    # Track whether it was a create or update
                    uid = keys.get(SORT_KEY, "unknown")
                    if is_update:
                        logger.info(f"  Updating {uid}")
                        updated_count += 1
                    else:
                        logger.info(f"  Creating {uid}")
                        created_count += 1
            except ClientError as e:
                logger.error(f"Failed to load row {idx + 1}: {e}")
                failed_count += 1

        logger.info(
            f"  {csv_path.name}: {created_count} uploaded, {updated_count} updated, {failed_count} failed")
        return created_count, updated_count, failed_count

    except FileNotFoundError:
        logger.error(f"File not found: {csv_path}")
        return 0, 1
    except Exception as e:
        logger.error(f"Error loading {csv_path}: {e}")
        return 0, 1


def upload_documents_to_s3(s3_client) -> Tuple[int, int]:
    """Upload all documents from documents/ subfolders to S3.
    
    Structure: S3Bucket/Documents/{uid}/{filename}
    
    Returns: (uploaded_count, failed_count)
    """
    if not DOCUMENTS_DIR.exists():
        logger.warning(f"Documents directory not found: {DOCUMENTS_DIR}")
        return 0, 0
    
    uploaded_count = 0
    failed_count = 0
    
    # Iterate through all uid subfolders in documents/
    uid_folders = [d for d in DOCUMENTS_DIR.iterdir() if d.is_dir()]
    if not uid_folders:
        logger.info("No documents to upload")
        return 0, 0
    
    logger.info(f"Uploading {len(uid_folders)} document folder(s) to S3...")
    
    for uid_folder in uid_folders:
        uid = uid_folder.name
        pdf_files = list(uid_folder.glob("*.pdf")) + list(uid_folder.glob("*.PDF"))
        
        if not pdf_files:
            logger.debug(f"  No PDFs found in {uid}")
            continue
        
        logger.debug(f"  Uploading {len(pdf_files)} file(s) for {uid}")
        
        for pdf_path in pdf_files:
            try:
                # Construct S3 key: Documents/{uid}/{filename}
                s3_key = f"{S3_PREFIX}/{uid}/{pdf_path.name}"
                
                logger.debug(f"    Uploading to s3://{S3_BUCKET}/{s3_key}")
                s3_client.upload_file(
                    str(pdf_path),
                    S3_BUCKET,
                    s3_key
                )
                logger.info(f"    ✓ Uploaded {uid}/{pdf_path.name}")
                uploaded_count += 1
                
            except ClientError as e:
                logger.error(f"    ✗ Failed to upload {uid}/{pdf_path.name}: {e}")
                failed_count += 1
            except Exception as e:
                logger.error(f"    ✗ Unexpected error uploading {uid}/{pdf_path.name}: {e}")
                failed_count += 1
    
    logger.info(f"\nS3 Upload Summary:")
    logger.info(f"  Total uploaded: {uploaded_count}")
    logger.info(f"  Total failed: {failed_count}")
    
    return uploaded_count, failed_count


def load_all_files(table, no_db: bool = False) -> Dict[str, Tuple[int, int, int]]:
    """
    Load all CSV files from data/ directory into DynamoDB.

    Returns: dict mapping filename to (created_count, updated_count, failed_count)
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

    total_created = 0
    total_updated = 0
    total_failed = 0

    for csv_path in csv_files:
        created, updated, failed = load_csv_file(table, csv_path, no_db)
        results[csv_path.name] = (created, updated, failed)
        total_created += created
        total_updated += updated
        total_failed += failed

    logger.info(f"\nSummary:")
    logger.info(f"  Total uploaded: {total_created}")
    logger.info(f"  Total updated: {total_updated}")
    logger.info(f"  Total failed: {total_failed}")

    return results


def main(no_db: bool = False):
    """Load all CSV data into DynamoDB and upload documents to S3."""
    logger.info(f"Loading planning data from {DATA_DIR} to {TABLE_NAME}")

    try:
        table = initialize_dynamodb()
        results = load_all_files(table, no_db)

        # Print DynamoDB summary
        if results:
            logger.info("\nLoad Summary by Area:")
            for filename, (created, updated, failed) in results.items():
                logger.info(
                    f"  {filename}: {created} uploaded, {updated} updated, {failed} failed")
        else:
            logger.warning("No files were processed")

    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        raise

    # Upload documents to S3 (non-fatal error)
    try:
        logger.info("\nStarting S3 document upload...")
        s3_client = initialize_s3()
        uploaded, failed = upload_documents_to_s3(s3_client)
    except Exception as e:
        logger.warning(f"S3 upload failed (non-fatal): {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load planning application data into DynamoDB")
    parser.add_argument("--no-db", action="store_true",
                        help="Simulate loading without writing to DynamoDB")
    args = parser.parse_args()

    main(no_db=args.no_db)
