# Data Extraction Pipeline

Extracts planning applications from the PlanIt API for areas 304, 318, 323 and processes them through a three-stage ETL pipeline: **Extract → Transform → Load** with in-memory DataFrames and AWS S3/DynamoDB integration.

## Architecture Overview

The pipeline processes data through three stages:

1. **Extract** (`extract.py`) — Fetches from PlanIt API, uploads PDFs to S3 (or local disk), returns DataFrames
2. **Transform** (`transform.py`) — Validates, standardizes, and type-casts DataFrame data in-memory
3. **Load** (`load.py`) — Loads transformed DataFrames to DynamoDB with upsert deduplication

**Key Features:**
- Metadata stored in **in-memory DataFrames** (no CSV intermediate files)
- PDFs uploaded directly to **S3** during extraction (or saved locally with `--local`)
- **DynamoDB** table `c25-planning-data-db` as final data store
- Support for **local testing mode** (`--local`) without AWS credentials
- Can run all three stages from a **single command** via load.py orchestration

## Setup

```bash
pip3 install -r requirements.txt
```

### AWS Configuration (Optional)

If using S3/DynamoDB (default mode):
```bash
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export S3_BUCKET="c25-planning-files-bucket"  # Optional, uses default if not set
```

For local testing mode, AWS credentials are **not required** — use `--local` flag.

## Quick Start

### Run Complete Pipeline (All 3 Stages)

```bash
# Full pipeline with S3 uploads
python3 load.py --pipeline --save-pdf

# Full pipeline, local testing (no AWS needed)
python3 load.py --pipeline --local --no-db

# Custom date range
python3 load.py --pipeline --start-date 2024-01-01 --end-date 2024-12-31 --save-pdf
```

### Run Individual Stages

```bash
# Extract only
python3 extract.py --save-pdf

# Transform only (from local CSVs)
python3 transform.py --local

# Load only (from local CSVs)
python3 load.py --no-db
```

## Detailed Usage

### extract.py — API Extraction & PDF Upload

Fetches planning applications from PlanIt API for areas 304, 318, 323.

**Options:**
- `--start-date YYYY-MM-DD` — Start date (default: 7 days ago)
- `--end-date YYYY-MM-DD` — End date (default: today)
- `--save-pdf` — Download and upload PDFs (default: skip PDFs)
- `--local` — Save PDFs locally instead of S3 (for testing)

**Examples:**

```bash
# Last 7 days, no PDFs
python3 extract.py

# Custom date range with PDFs to S3
python3 extract.py --start-date 2024-01-01 --end-date 2024-01-31 --save-pdf

# Local testing mode (PDFs saved to documents/ folder)
python3 extract.py --local --save-pdf --start-date 2024-01-01

# Python usage
from extract import extract_all_areas
dfs = extract_all_areas(start_date="2024-01-01", end_date="2024-01-31", save_pdf=True)
```

**Output:**
- **DataFrames** (in-memory, returned as dict): `{area_name: DataFrame}`
  - `area_304`: Records for area 304
  - `area_318`: Records for area 318
  - `area_323`: Records for area 323
- **PDFs** (S3 or local): `s3://c25-planning-files-bucket/documents/{uid}/{filename}` or `documents/{uid}/{filename}`

**Targets (API Areas):**
- **Area 304** (Greenwich)
- **Area 318** (Newham)
- **Area 323** (Tower Hamlets)

---

### transform.py — Validation & Standardization

Validates and transforms planning application data in-memory. Handles:
- Null value standardization → "N/A"
- Type casting (int, float, datetime, string)
- Required field validation
- Coordinate range validation (UK bounds)

**Options:**
- `--local` — Read from local `data/` CSV files (for testing without extract stage)

**Examples:**

```bash
# Local testing (transform CSVs from data/)
python3 transform.py --local

# Python usage
from transform import transform_dataframes
dfs = {
    "area_304": df_304,
    "area_318": df_318,
    "area_323": df_323
}
transformed_dfs, reports = transform_dataframes(dfs)
```

**Output:**
- **Transformed DataFrames** (dict): Cleaned and validated data
- **Reports** (dict): Validation summary for each area

---

### load.py — DynamoDB Loading & Pipeline Orchestration

Loads transformed data into DynamoDB. Can also orchestrate the entire pipeline.

**Options (for `--pipeline` mode):**
- `--pipeline` — Run full ETL pipeline (extract → transform → load)
- `--start-date YYYY-MM-DD` — Start date for extraction (default: 7 days ago)
- `--end-date YYYY-MM-DD` — End date for extraction (default: today)
- `--save-pdf` — Download PDFs during extraction
- `--local` — Local testing mode (no AWS credentials needed)
- `--no-db` — Dry-run mode (verify logic without writing to DynamoDB)

**Options (for CSV loading mode):**
- `--no-db` — Dry-run mode

**Examples:**

```bash
# Full pipeline with S3 uploads
python3 load.py --pipeline --save-pdf

# Full pipeline, local testing (no AWS)
python3 load.py --pipeline --local --no-db

# Custom date range
python3 load.py --pipeline --start-date 2024-01-01 --end-date 2024-12-31 --save-pdf

# Load from local CSVs only
python3 load.py

# Dry-run (no DynamoDB writes)
python3 load.py --no-db

# Python usage (full pipeline)
from load import run_full_pipeline
created, updated, failed = run_full_pipeline(save_pdf=True, no_db=False)
print(f"Created: {created}, Updated: {updated}, Failed: {failed}")

# Python usage (load from DataFrames)
from load import main_from_dataframes
created, updated, failed = main_from_dataframes(transformed_dfs)
```

**Output:**
- **DynamoDB summary**: Records created, updated, failed
- **Error logs**: Any failed rows with details

**DynamoDB Table Schema:**
- Table name: `c25-planning-data-db`
- Partition key: `area` (string) — maps to area_name
- Sort key: `uid` (string) — unique application ID
- Attributes: address, app_size, app_state, app_type, location_x, location_y, postcode, start_date, url

---

## Mode Comparison

| Mode | Command | AWS Required | PDF Storage | Use Case |
|------|---------|--------------|-------------|----------|
| **Full Pipeline (S3)** | `load.py --pipeline --save-pdf` | Yes | S3 | Production |
| **Full Pipeline (Local)** | `load.py --pipeline --local --no-db` | No | Local disk | Testing |
| **Extract Only** | `extract.py --save-pdf` | Yes | S3 | Debugging extraction |
| **Transform Only** | `transform.py --local` | No | N/A | Testing validation logic |
| **Load Only** | `load.py` | Yes | N/A | Reloading existing CSVs |
| **Dry-Run** | `load.py --pipeline --no-db` | Yes | S3 | Verify pipeline without writing |

---

## Data Targets (Covered Areas)

The pipeline monitors three London boroughs for planning applications:

| Area Code | Borough | API Base URL |
|-----------|---------|--------------|
| 304 | Greenwich | planit.org.uk |
| 318 | Newham | planit.org.uk |
| 323 | Tower Hamlets | planit.org.uk |

Each area produces a separate DataFrame/table with the same schema.

---

## Testing

```bash
# Run all tests
pytest tests/ -v --cov=extract --cov=transform --cov-report=term-missing

# Test extraction only
pytest tests/test_extract.py -v

# Test transformation only
pytest tests/test_transform.py -v

# Test with local mode
python3 load.py --pipeline --local --no-db
```

---

## Troubleshooting

**Missing AWS credentials?**
```bash
python3 load.py --pipeline --local --no-db
```

**Want to verify pipeline logic without DynamoDB writes?**
```bash
python3 load.py --pipeline --no-db
```

**Need to inspect extraction data?**
```bash
python3 extract.py --local --save-pdf
# Check documents/ folder for PDFs
```

**Test transformation independently?**
```bash
python3 transform.py --local
# Reads CSVs from data/ folder
```

Expected: 60%+ coverage, all tests pass.
