# Data Extraction Pipeline

Extracts planning applications from the PlanIt API for areas 318, 323, 305 and saves to CSV.

## Setup

```bash
pip3 install -r requirements.txt
```

## Usage

Extract last 7 days:
```bash
python3 extract.py
```

Custom date range:
```bash
python3 extract.py --start-date 2026-09-01 --end-date 2026-09-15
```

Output files are saved to `data/` as `area_318.csv`, `area_323.csv`, `area_305.csv`.

## Testing

```bash
pytest tests/ -v --cov=extract --cov-report=term-missing
```

Expected: 60%+ coverage, all tests pass.
