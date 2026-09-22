"""
Load planning application data from DataFrames into DynamoDB.

Receives transformed DataFrames from transform.py and uploads to
DynamoDB table with partition key 'area' and sort key 'uid'.

PDFs are uploaded to S3 during extraction (extract.py).

Usage:
    python3 load.py (called from orchestration script)
    python3 load.py --local (testing mode with local CSV files)
    python3 load.py --no-db (dry run without DynamoDB writes)
"""

import argparse
import logging
import os
import boto3
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Tuple
from decimal import Decimal
from botocore.exceptions import ClientError

# Import pipeline modules for orchestration
try:
    from extract import extract_all_areas
    from transform import (
        transform_dataframes,
        get_boto3_session,
        get_openai_client,
        generate_record_summary,
    )
    import transform as transform_module
except ImportError:
    extract_all_areas = None
    transform_dataframes = None
    transform_module = None
    get_boto3_session = None
    get_openai_client = None
    generate_record_summary = None

# Configuration
DATA_DIR = Path(__file__).parent / "data"
DOCUMENTS_DIR = Path(__file__).parent / "documents"
TABLE_NAME = "c25-planning-data-db"
S3_BUCKET = "c25-planning-files-bucket"
S3_PREFIX = "documents"
PARTITION_KEY = "area"  # Maps to area_name
SORT_KEY = "uid"

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def initialize_dynamodb():
    """Initialize DynamoDB resource and client."""
    try:
        region = os.getenv('AWS_REGION', 'eu-west-2')
        dynamodb = boto3.resource('dynamodb', region_name=region)
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
        region = os.getenv('AWS_REGION', 'eu-west-2')
        s3_client = boto3.client('s3', region_name=region)
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


def has_data_changed(existing_item: Dict[str, Any], current_row: Dict[str, Any], uid: str) -> Tuple[bool, List[str]]:
    """
    Check if application status (app_state) has changed.

    Only regenerates summaries when the decision status changes, since that's the 
    most significant change to a planning application (e.g., Undecided → Permitted).

    Returns:
        (has_changed: bool, changed_fields: List[str])
    """
    current_app_state = str(current_row.get("app_state", ""))
    existing_app_state = str(existing_item.get("app_state", ""))

    has_changed = current_app_state != existing_app_state
    changed_fields = []

    if has_changed:
        changed_fields.append(
            f"app_state: '{existing_app_state}' → '{current_app_state}'")

    return has_changed, changed_fields


def load_dataframe(table, df: pd.DataFrame, area_name: str, no_db: bool = False) -> Tuple[int, int, int]:
    """
    Load a single DataFrame into DynamoDB with conditional summary generation.

    Summaries are generated ONLY for:
    - New records (not in DynamoDB yet)
    - Existing records where application data has changed

    Summaries are REUSED for:
    - Existing records with no data changes

    Returns: (created_count, updated_count, failed_count)
    """
    if df is None or df.empty:
        logger.warning(f"Skipping empty DataFrame for {area_name}")
        return 0, 0, 0

    logger.info(f"Loading {len(df)} records from {area_name}")

    # Initialize boto3 and OpenAI clients for conditional summary generation
    session = None
    openai_client = None
    try:
        if get_boto3_session is not None:
            session = get_boto3_session()
        if get_openai_client is not None:
            openai_client = get_openai_client()
    except Exception as e:
        logger.warning(
            f"Could not initialize AWS/OpenAI clients for summary generation: {e}")
        session = None
        openai_client = None

    created_count = 0
    updated_count = 0
    failed_count = 0
    summary_generated_count = 0
    summary_reused_count = 0

    for idx, row in df.iterrows():
        keys, attributes = csv_row_to_dynamodb_item(row)

        if keys is None:
            logger.warning(
                f"Skipping row {idx + 1}: missing partition or sort key")
            failed_count += 1
            continue

        try:
            uid = keys.get(SORT_KEY, "unknown")

            if not no_db:
                # Check if record already exists
                existing = table.get_item(Key=keys)
                is_update = "Item" in existing
                existing_item = existing.get("Item", {})

                if is_update:
                    # Existing record - check if data has changed
                    has_changed, changed_fields = has_data_changed(
                        existing_item, row.to_dict(), uid)

                    if not has_changed:
                        # No data changes - reuse existing summary
                        existing_summary = existing_item.get("summary", "")
                        if existing_summary:
                            attributes["summary"] = existing_summary
                            summary_reused_count += 1
                            logger.info(
                                f"  ✓ {uid} (no changes, reusing existing summary)")
                        else:
                            # No previous summary, keep current value
                            logger.info(
                                f"  ✓ {uid} (no changes, no previous summary)")
                    else:
                        # Data has changed - generate new summary if we have clients
                        logger.info(f"  ✓ {uid} (changes detected)")
                        for change in changed_fields:
                            logger.info(f"      • {change}")

                        if session and openai_client and "summary" in attributes:
                            logger.info(f"      Generating new summary...")
                            new_summary = generate_record_summary(
                                session, openai_client, row)
                            if new_summary:
                                attributes["summary"] = new_summary
                                summary_generated_count += 1
                            logger.info(
                                f"      Summary: {new_summary[:80]}...")
                else:
                    # New record - generate summary if we have clients
                    if session and openai_client and "summary" in attributes:
                        logger.info(f"  ✓ {uid} (new record)")
                        logger.info(f"      Generating summary...")
                        new_summary = generate_record_summary(
                            session, openai_client, row)
                        if new_summary:
                            attributes["summary"] = new_summary
                            summary_generated_count += 1
                        logger.info(f"      Summary: {new_summary[:80]}...")
                    else:
                        logger.info(
                            f"  ✓ {uid} (new record, no summary generation)")

                # Build update expression to set all attributes
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
                if is_update:
                    updated_count += 1
                else:
                    created_count += 1
        except ClientError as e:
            logger.error(f"Failed to load row {idx + 1}: {e}")
            failed_count += 1

    logger.info(
        f"  {area_name}: {created_count} created, {updated_count} updated, {failed_count} failed")
    if summary_generated_count > 0 or summary_reused_count > 0:
        logger.info(
            f"  Summaries: {summary_generated_count} generated, {summary_reused_count} reused")
    return created_count, updated_count, failed_count


def load_from_dataframes(table, dfs_dict: Dict[str, pd.DataFrame], no_db: bool = False) -> Tuple[int, int, int]:
    """
    Load all DataFrames into DynamoDB.

    Args:
        table: DynamoDB table resource
        dfs_dict: Dict mapping area_name to transformed DataFrame
        no_db: If True, simulate writes without actually updating DynamoDB

    Returns: (total_created, total_updated, total_failed)
    """
    total_created = 0
    total_updated = 0
    total_failed = 0

    for area_name, df in dfs_dict.items():
        created, updated, failed = load_dataframe(table, df, area_name, no_db)
        total_created += created
        total_updated += updated
        total_failed += failed

    logger.info(f"\nLoad Summary:")
    logger.info(f"  Total created: {total_created}")
    logger.info(f"  Total updated: {total_updated}")
    logger.info(f"  Total failed: {total_failed}")

    return total_created, total_updated, total_failed


def load_csv_file(table, csv_path: Path, no_db: bool = False) -> Tuple[int, int, int]:
    """
    Load a single CSV file into DynamoDB (for local testing).

    Returns: (created_count, updated_count, failed_count)
    """
    try:
        df = pd.read_csv(csv_path)
        area_name = csv_path.stem  # e.g., "area_318"
        return load_dataframe(table, df, area_name, no_db)
    except FileNotFoundError:
        logger.error(f"File not found: {csv_path}")
        return 0, 0, 1
    except Exception as e:
        logger.error(f"Error loading {csv_path}: {e}")
        return 0, 0, 1


def load_all_files(table, no_db: bool = False) -> Dict[str, Tuple[int, int, int]]:
    """
    Load all CSV files from data/ directory into DynamoDB (for local testing).

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
        logger.info(
            "Running in NO-DB mode - no data will be written to DynamoDB")

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
    logger.info(f"  Total created: {total_created}")
    logger.info(f"  Total updated: {total_updated}")
    logger.info(f"  Total failed: {total_failed}")

    return results


def upload_documents_to_s3(s3_client) -> Tuple[int, int]:
    """
    Upload all documents from documents/ subfolders to S3.

    Note: In the normal pipeline, documents are uploaded directly during extraction.
    This function is for handling documents from local testing.

    Structure: S3Bucket/documents/{uid}/{filename}

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
        pdf_files = list(uid_folder.glob("*.pdf")) + \
            list(uid_folder.glob("*.PDF"))

        if not pdf_files:
            logger.debug(f"  No PDFs found in {uid}")
            continue

        logger.debug(f"  Uploading {len(pdf_files)} file(s) for {uid}")

        for pdf_path in pdf_files:
            try:
                # Construct S3 key: documents/{uid}/{filename}
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
                logger.error(
                    f"    ✗ Failed to upload {uid}/{pdf_path.name}: {e}")
                failed_count += 1
            except Exception as e:
                logger.error(
                    f"    ✗ Unexpected error uploading {uid}/{pdf_path.name}: {e}")
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


def main_from_dataframes(dfs_dict: Dict[str, pd.DataFrame], no_db: bool = False) -> Tuple[int, int, int]:
    """Load DataFrames into DynamoDB.

    Args:
        dfs_dict: Dict mapping area_name to transformed DataFrame
        no_db: If True, simulate writes without actually updating DynamoDB

    Returns:
        (total_created, total_updated, total_failed)
    """
    logger.info(f"Loading {len(dfs_dict)} area datasets into {TABLE_NAME}")

    try:
        table = initialize_dynamodb()
        return load_from_dataframes(table, dfs_dict, no_db)
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        raise


def run_full_pipeline(start_date: str = None, end_date: str = None, no_db: bool = False,
                      local: bool = False, save_pdf: bool = False, skip_summary: bool = False) -> Tuple[int, int, int]:
    """Run the complete ETL pipeline: extract → transform → load.

    This orchestration function calls all three pipeline stages in sequence.

    Args:
        start_date: Start date for API extraction (YYYY-MM-DD)
        end_date: End date for API extraction (YYYY-MM-DD)
        no_db: If True, simulate DynamoDB writes without updating
        local: If True, use local disk mode (no AWS credentials needed)
        save_pdf: If True, save/upload PDFs during extraction
        skip_summary: If True, skip AI summary generation (useful for local testing)

    Returns:
        (total_created, total_updated, total_failed) - counts from DynamoDB load stage

    Raises:
        ImportError: If extract or transform modules cannot be imported
        Exception: If any stage of the pipeline fails
    """
    if extract_all_areas is None or transform_dataframes is None:
        raise ImportError("Could not import extract_all_areas or transform_dataframes. "
                          "Ensure extract.py and transform.py are in the same directory.")

    # Set USE_S3 flag in extract module if local mode
    if local:
        import extract as extract_module
        extract_module.USE_S3 = False
        logger.info("Running in LOCAL mode - PDFs will be saved to local disk")

    # Set SKIP_SUMMARY flag in transform module if requested
    if skip_summary and transform_module:
        transform_module.SKIP_SUMMARY = True
        logger.info(
            "Running with SKIP_SUMMARY=True - AI summaries will be skipped")

    try:
        # Stage 1: Extract from API → DataFrame dict
        logger.info("\n" + "="*60)
        logger.info("STAGE 1: EXTRACTION (PlanIt API → DataFrames)")
        logger.info("="*60)
        dfs = extract_all_areas(start_date=start_date,
                                end_date=end_date, save_pdf=save_pdf)
        logger.info(f"✓ Extracted {len(dfs)} area datasets")
        for area_name, df in dfs.items():
            logger.info(f"  {area_name}: {len(df)} records")

        # Stage 2: Transform → Validate & Standardize
        logger.info("\n" + "="*60)
        logger.info(
            "STAGE 2: TRANSFORMATION (Validate → Standardize → Typecast → Generate Summaries)")
        logger.info("="*60)
        transformed_dfs, reports = transform_dataframes(dfs)
        logger.info(f"✓ Transformed {len(transformed_dfs)} area datasets")
        for area_name, report in reports.items():
            logger.info(f"  {area_name}: {report}")

        # Stage 3: Load to DynamoDB
        logger.info("\n" + "="*60)
        logger.info("STAGE 3: LOADING (DataFrames → DynamoDB)")
        logger.info("="*60)
        created, updated, failed = main_from_dataframes(
            transformed_dfs, no_db=no_db)

        logger.info("\n" + "="*60)
        logger.info("PIPELINE COMPLETE")
        logger.info("="*60)
        logger.info(f"✓ Total created: {created}")
        logger.info(f"✓ Total updated: {updated}")
        logger.info(f"✓ Total failed: {failed}")
        logger.info("="*60 + "\n")

        return created, updated, failed

    except Exception as e:
        logger.error(f"\n❌ Pipeline failed at stage: {e}")
        raise


def main(no_db: bool = False):
    """Load all CSV data into DynamoDB (for local testing)."""
    logger.info(f"Loading planning data from {DATA_DIR} to {TABLE_NAME}")

    try:
        table = initialize_dynamodb()
        results = load_all_files(table, no_db)

        # Print DynamoDB summary
        if results:
            logger.info("\nLoad Summary by Area:")
            for filename, (created, updated, failed) in results.items():
                logger.info(
                    f"  {filename}: {created} created, {updated} updated, {failed} failed")
        else:
            logger.warning("No files were processed")

    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        raise

    # Upload documents to S3 (non-fatal error)
    try:
        logger.info("\nProcessing documents...")
        s3_client = initialize_s3()
        uploaded, failed = upload_documents_to_s3(s3_client)
    except Exception as e:
        logger.warning(f"Document processing failed (non-fatal): {e}")


def lambda_handler(event, context):
    """AWS Lambda handler for running the ETL pipeline.

    This function is invoked by AWS Lambda and runs the complete
    ETL pipeline (extract → transform → load) with PDF uploads.

    Args:
        event: Lambda event object (can contain optional parameters)
        context: Lambda context object with function metadata

    Returns:
        dict: Response object with statusCode and body
        {
            "statusCode": 200 or 500,
            "body": {
                "message": "Pipeline completed successfully" or error message,
                "created": int,
                "updated": int,
                "failed": int,
                "execution_time": float (seconds)
            }
        }

    Example event (optional parameters):
        {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "save_pdf": true,
            "no_db": false
        }
    """
    import time
    import json

    start_time = time.time()

    try:
        logger.info("=" * 60)
        logger.info("AWS Lambda: Starting ETL Pipeline")
        logger.info("=" * 60)

        # Extract optional parameters from event
        start_date = event.get("start_date") if event else None
        end_date = event.get("end_date") if event else None
        save_pdf = event.get("save_pdf", True) if event else True
        no_db = event.get("no_db", False) if event else False

        logger.info(f"Parameters:")
        logger.info(f"  start_date: {start_date}")
        logger.info(f"  end_date: {end_date}")
        logger.info(f"  save_pdf: {save_pdf}")
        logger.info(f"  no_db: {no_db}")

        # Run the pipeline
        created, updated, failed = run_full_pipeline(
            start_date=start_date,
            end_date=end_date,
            no_db=no_db,
            local=False,  # Lambda always uses AWS resources
            save_pdf=save_pdf,
            skip_summary=False  # Lambda uses full pipeline with summaries
        )

        execution_time = time.time() - start_time

        response = {
            "statusCode": 200,
            "body": {
                "message": "Pipeline completed successfully",
                "created": created,
                "updated": updated,
                "failed": failed,
                "execution_time": round(execution_time, 2)
            }
        }

        logger.info(f"\nLambda execution completed in {execution_time:.2f}s")
        logger.info(
            f"Results: {created} created, {updated} updated, {failed} failed")

        return response

    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"Pipeline failed: {str(e)}"

        logger.error(
            f"\n❌ Lambda execution failed after {execution_time:.2f}s")
        logger.error(error_msg, exc_info=True)

        return {
            "statusCode": 500,
            "body": {
                "message": error_msg,
                "created": 0,
                "updated": 0,
                "failed": 0,
                "execution_time": round(execution_time, 2)
            }
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load planning application data into DynamoDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline (extract → transform → load)
  python3 load.py --pipeline
  
  # Full pipeline with custom dates
  python3 load.py --pipeline --start-date 2024-01-01 --end-date 2024-12-31
  
  # Full pipeline, local testing mode (no AWS credentials needed)
  python3 load.py --pipeline --local --no-db
  
  # Load only from local CSV files (backward compatibility)
  python3 load.py --no-db
        """)

    parser.add_argument("--pipeline", action="store_true",
                        help="Run full ETL pipeline (extract → transform → load)")
    parser.add_argument("--start-date", type=str, default=None,
                        help="Start date for API extraction (YYYY-MM-DD). Only used with --pipeline")
    parser.add_argument("--end-date", type=str, default=None,
                        help="End date for API extraction (YYYY-MM-DD). Only used with --pipeline")
    parser.add_argument("--save-pdf", action="store_true",
                        help="Download and upload PDFs during extraction. Only used with --pipeline")
    parser.add_argument("--local", action="store_true",
                        help="Run in local mode (no AWS credentials needed). Only used with --pipeline")
    parser.add_argument("--skip-summary", action="store_true",
                        help="Skip AI summary generation (useful for local testing without OpenAI/AWS credentials)")
    parser.add_argument("--no-db", action="store_true",
                        help="Simulate loading without writing to DynamoDB")

    args = parser.parse_args()

    if args.pipeline:
        run_full_pipeline(start_date=args.start_date,
                          end_date=args.end_date,
                          no_db=args.no_db,
                          local=args.local,
                          save_pdf=args.save_pdf,
                          skip_summary=args.skip_summary)
    else:
        main(no_db=args.no_db)
