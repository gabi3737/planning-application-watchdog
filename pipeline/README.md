# Data Extraction Pipeline

Extracts planning applications from the PlanIt API for areas 318, 323, 305 and saves to CSV. Includes data transformation and validation.

## Setup

```bash
pip3 install -r requirements.txt
```

## Scripts

### extract.py

Fetches planning applications from the PlanIt API and saves to CSV files.

**Usage:**

Extract last 7 days (default):
```bash
python3 extract.py
```

Custom date range:
```bash
python3 extract.py --start-date 2026-09-01 --end-date 2026-09-15
```

Extract with PDF downloads:
```bash
python3 extract.py --save-pdf
```

Combine options:
```bash
python3 extract.py --start-date 2026-09-01 --end-date 2026-09-15 --save-pdf
```

**Options:**
- `--start-date YYYY-MM-DD` — Start date (default: 7 days ago)
- `--end-date YYYY-MM-DD` — End date (default: today)
- `--save-pdf` — Download PDF documents for each application (optional)

**Output:**
- CSV files: `data/area_318.csv`, `data/area_323.csv`, `data/area_304.csv`
- PDFs (if `--save-pdf`): `documents/{uid}_{filename}.pdf`

### transform.py

Validates and transforms planning application CSV data. Handles:
- Null value standardization (→ "N/A")
- Type casting (int, float, datetime, string)
- Required field validation
- Coordinate range validation (UK bounds)

**Usage:**

Transform a single file:
```python
from transform import transform
df, report = transform(Path("data/area_318.csv"))
print(f"Rows processed: {report['rows_processed']}")
print(f"Validation errors: {report['validation_report']['total_errors']}")
```

Transform all files:
```python
from transform import transform_all_files
results = transform_all_files()
for filename, (df, report) in results.items():
    print(f"{filename}: {report['rows_processed']} rows")
```

Or from command line:
```bash
python3 transform.py
```

**Output:**
Validation report showing:
- Rows processed
- Type casting errors
- Required field violations
- Coordinate boundary violations

### load.py

Loads transformed CSV data from `data/` directory into AWS DynamoDB table `c25-planning-data-db`.

**Usage:**

Load all CSV files to DynamoDB:
```bash
python3 load.py
```

Dry-run mode (verify logic without writing):
```bash
python3 load.py --no-db
```

**Options:**
- `--dry-run` — Simulate loading without writing to DynamoDB (optional)

**Requirements:**
- AWS credentials configured (via environment variables, credentials file, or IAM role)
- DynamoDB table `c25-planning-data-db` exists with:
  - Partition key: `area` (string)
  - Sort key: `uid` (string)

**Output:**
- Per-file loading summary (record count, errors)
- Total records loaded across all files
- Error logs for any failed rows

## Testing

```bash
pytest tests/ -v --cov=extract --cov-report=term-missing
```

Expected: 60%+ coverage, all tests pass.
