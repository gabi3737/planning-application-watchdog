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

## Testing

```bash
pytest tests/ -v --cov=extract --cov-report=term-missing
```

Expected: 60%+ coverage, all tests pass.
