"""
Extract planning applications from the PlanIt API and save to CSV.

Usage:
    python3 extract.py [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
"""

import argparse
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path

# Configuration
API_BASE_URL = "https://www.planit.org.uk/api/applics/json"
AREA_CODES = {318: "area_318", 323: "area_323", 305: "area_305"}
FIELDS = ["address", "app_size", "app_state", "app_type", "area_id", 
          "area_name", "location_x", "location_y", "postcode", "start_date", "uid", "url"]
DATA_DIR = Path(__file__).parent / "data"

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def calculate_date_range() -> Tuple[str, str]:
    """Calculate last 7 days."""
    end = datetime.now()
    start = end - timedelta(days=7)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def flatten_location(location: Optional[Dict]) -> Tuple[Optional[float], Optional[float]]:
    """Extract x, y from location object."""
    if not location or not isinstance(location, dict):
        return None, None
    
    if "x" in location and "y" in location:
        return location.get("x"), location.get("y")
    
    if "coordinates" in location:
        coords = location["coordinates"]
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            return coords[0], coords[1]
    
    if "geometry" in location:
        coords = location.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            return coords[0], coords[1]
    
    return None, None


def extract_from_record(app: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract required fields from application record."""
    other = app.get("other_fields", {})
    
    extracted = {
        "uid": app.get("name"),  # e.g., "Newham/26/01919/CLP"
        "address": app.get("address"),
        "postcode": other.get("postcode") or other.get("agent_address", "").split()[-1] if other.get("agent_address") else None,
        "app_type": app.get("app_type"),
        "app_state": app.get("app_state"),
        "app_size": app.get("app_size"),
        "area_id": app.get("area_id"),
        "area_name": app.get("area_name"),
        "start_date": other.get("date_received") or app.get("last_changed", "").split("T")[0],
        "url": app.get("link"),
        "location_x": app.get("location_x"),
        "location_y": app.get("location_y"),
    }
    
    return extracted if any(extracted.values()) else None


def fetch_applications(auth_code: int, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Fetch all applications for a given area and date range."""
    all_records = []
    page = 1
    
    while True:
        try:
            params = {
                "auth": auth_code,
                "start_date": start_date,
                "end_date": end_date,
                "pg_sz": 10,
                "page": page,
            }
            
            response = requests.get(API_BASE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # API returns dict with 'records' key
            records = data.get("records", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if not records:
                break
            
            all_records.extend(records)
            logger.info(f"Auth {auth_code}: Fetched {len(records)} records from page {page}")
            page += 1
            
        except Exception as e:
            logger.error(f"Auth {auth_code}: Error fetching page {page}: {e}")
            break
    
    return all_records


def save_to_csv(records: List[Dict], area_name: str) -> Path:
    """Save records to CSV file."""
    if not records:
        logger.warning(f"No records for {area_name}")
        return None
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DATA_DIR / f"{area_name}.csv"
    
    df = pd.DataFrame(records)
    df.to_csv(csv_path, index=False)
    logger.info(f"Saved {len(records)} records to {csv_path}")
    
    return csv_path


def main(start_date: str = None, end_date: str = None):
    """Extract planning applications for all areas."""
    if not start_date or not end_date:
        start_date, end_date = calculate_date_range()
    
    logger.info(f"Extracting data for {start_date} to {end_date}")
    
    for auth_code, area_name in AREA_CODES.items():
        logger.info(f"Processing {area_name} (auth={auth_code})")
        
        raw = fetch_applications(auth_code, start_date, end_date)
        logger.info(f"  Raw records fetched: {len(raw)}")
        
        extracted = [extract_from_record(app) for app in raw]
        extracted = [r for r in extracted if r is not None]
        logger.info(f"  Records extracted: {len(extracted)}")
        
        if extracted:
            save_to_csv(extracted, area_name)
        else:
            logger.warning(f"No data extracted for {area_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract planning applications")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    main(args.start_date, args.end_date)
