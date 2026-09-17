"""
Extract planning applications from the PlanIt API and save to CSV.

Usage:
    python3 extract.py [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--save-pdf]
"""

import argparse
import logging
from curl_cffi import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import time
import os
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import certifi
from requests.exceptions import HTTPError

# Configuration
API_BASE_URL = "https://www.planit.org.uk/api/applics/json"
AREA_CODES = {318: "area_318", 323: "area_323", 304: "area_304"}
FIELDS = ["address", "app_size", "app_state", "app_type", "area_id",
          "area_name", "location_x", "location_y", "postcode", "start_date", "uid", "url"]
DATA_DIR = Path(__file__).parent / "data"
DOCUMENTS_DIR = Path(__file__).parent / "documents"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (+https://github.com/gabi3737; trainee.gabriela.prefit@sigma-labs.co.uk)",
    "Accept": "application/pdf"
}

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
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


def create_session() -> requests.Session:
    """Create and return a new HTTP session with browser impersonation."""
    session = requests.Session(impersonate="chrome124")
    return session


def convert_url_to_documents_url(url: str) -> str:
    """Convert a planning application summary URL to its documents URL."""
    if "activeTab=summary" in url:
        return url.replace("activeTab=summary", "activeTab=documents")
    return url


def load_webpage(url: str, session: requests.Session) -> Optional[BeautifulSoup]:
    """Load the HTML content of a URL and return a BeautifulSoup object."""
    try:
        response = session.get(url, allow_redirects=True,
                               timeout=(5, 10), verify=certifi.where())
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return soup
    except HTTPError as e:
        logger.error(f"HTTP error loading webpage {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading webpage {url}: {e}")
        return None


def find_pdf_urls(soup: BeautifulSoup, url: str) -> List[Tuple[str, str]]:
    """Find and return all PDF URLs and their link text from the given BeautifulSoup object.

    Returns: List of tuples (full_url, link_text)
    """
    urls = []
    for link in soup.find_all("a", href=True):
        if link["href"].lower().endswith(".pdf"):
            full_url = urljoin(url, link["href"])
            link_text = link.get_text(strip=True)
            urls.append((full_url, link_text))
    return urls


def get_pdf(url: str, session: requests.Session) -> Optional[bytes]:
    """Download a PDF from the given URL and return its content."""
    try:
        response = session.get(url, allow_redirects=True, timeout=(
            5, 10), verify=certifi.where(), headers=HEADERS)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {e}")
        return None


def save_pdf_to_uid_folder(content: bytes, uid: str, filename: str) -> bool:
    """Save PDF content to a uid-specific subfolder. Returns True if successful."""
    try:
        safe_uid = uid.replace("/", "_")
        uid_folder = DOCUMENTS_DIR / safe_uid
        uid_folder.mkdir(parents=True, exist_ok=True)

        # Sanitize filename to remove any path separators
        safe_filename = filename.replace("/", "_")
        filepath = uid_folder / safe_filename
        with open(filepath, "wb") as f:
            f.write(content)
        logger.debug(f"    Saved PDF to {filepath}")
        return True
    except Exception as e:
        logger.error(f"    Error saving PDF for {uid}: {e}")
        return False


def download_documents(app_url: str, session: requests.Session, uid: str) -> bool:
    """Download the application form PDF for a planning application.

    Strategy: 
    1. Find all PDF links
    2. Prioritize PDFs with 'form' or 'applicationform' in link text
    3. Fall back to first PDF if no form found
    4. Return True if successfully downloaded, False otherwise
    """
    if not app_url:
        logger.debug(f"    No URL provided for {uid}")
        return False

    try:
        logger.debug(f"    Loading documents page for {uid}")
        docs_url = convert_url_to_documents_url(app_url)
        soup = load_webpage(docs_url, session)
        if not soup:
            logger.warning(f"    Could not load documents page for {uid}")
            return False

        # Get all PDF links with their text
        pdf_links = find_pdf_urls(soup, docs_url)
        if not pdf_links:
            logger.debug(f"    No PDFs found for {uid}")
            return False

        logger.debug(f"    Found {len(pdf_links)} PDF links for {uid}")

        # Try to find a form PDF
        selected_pdf_url = None
        selected_pdf_text = None

        for pdf_url, pdf_text in pdf_links:
            logger.debug(
                f"    ✓ Checking PDF link: URL: {pdf_url}")
            if "form" in pdf_url.lower() or "applicationform" in pdf_url.lower():
                selected_pdf_url = pdf_url
                selected_pdf_text = pdf_text
                logger.info(f"    ✓ Found form PDF: {pdf_url}")
                break

        # Fall back to first PDF if no form found
        if not selected_pdf_url:
            selected_pdf_url, selected_pdf_text = pdf_links[0]
            logger.info(
                f"    ✓ No form PDF found, using first: {selected_pdf_text}")

        # Download the selected PDF
        logger.debug(f"    Downloading {selected_pdf_text}...")
        pdf_content = get_pdf(selected_pdf_url, session)
        if not pdf_content:
            logger.warning(
                f"    Failed to download {selected_pdf_text} for {uid}")
            return False

        # Extract filename from URL, fallback to generic name
        filename = selected_pdf_url.split("/")[-1]
        if not filename or not filename.lower().endswith(".pdf"):
            filename = "Application_Form.pdf"

        # Save to uid-specific folder
        if save_pdf_to_uid_folder(pdf_content, uid, filename):
            logger.info(f"    ✓ Saved application form for {uid}")
            return True
        else:
            return False

    except Exception as e:
        logger.error(f"    Error downloading documents for {uid}: {e}")
        return False


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
        "url": app.get("url"),
        "location_x": app.get("location_x"),
        "location_y": app.get("location_y"),
    }

    return extracted if any(extracted.values()) else None


def fetch_applications(auth_code: int, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Fetch all applications for a given area and date range."""
    all_records = []
    page = 1

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    while True:
        try:
            params = {
                "auth": auth_code,
                "start_date": start_date,
                "end_date": end_date,
                "pg_sz": 10,
                "page": page,
            }

            # Use curl_cffi with browser impersonation to avoid being blocked
            response = requests.get(
                API_BASE_URL, params=params, headers=headers, timeout=10, impersonate="chrome101")
            response.raise_for_status()
            data = response.json()

            # API returns dict with 'records' key
            records = data.get("records", []) if isinstance(
                data, dict) else (data if isinstance(data, list) else [])
            if not records:
                break

            all_records.extend(records)
            logger.info(
                f"Auth {auth_code}: Fetched {len(records)} records from page {page}")
            page += 1

            # Add delay between requests to avoid rate limiting
            time.sleep(60)

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


def main(start_date: str = None, end_date: str = None, save_pdf: bool = False):
    """Extract planning applications for all areas.

    Args:
        start_date: Start date (YYYY-MM-DD) or None for last 7 days
        end_date: End date (YYYY-MM-DD) or None for last 7 days
        save_pdf: If True, download PDFs for each application
    """
    if not start_date or not end_date:
        start_date, end_date = calculate_date_range()

    logger.info(f"Extracting data for {start_date} to {end_date}")
    if save_pdf:
        logger.info("PDF download enabled")
        session = create_session()
    else:
        session = None

    for auth_code, area_name in AREA_CODES.items():
        logger.info(f"Processing {area_name} (auth={auth_code})")

        raw = fetch_applications(auth_code, start_date, end_date)
        logger.info(f"  Raw records fetched: {len(raw)}")

        extracted = [extract_from_record(app) for app in raw]
        extracted = [r for r in extracted if r is not None]
        logger.info(f"  Records extracted: {len(extracted)}")

        if extracted:
            save_to_csv(extracted, area_name)

            # Download application forms if enabled
            if save_pdf and session:
                logger.info(
                    f"  Downloading application forms for {len(extracted)} records...")
                forms_downloaded = 0
                forms_failed = 0

                for i, record in enumerate(extracted, 1):
                    if record.get("url"):
                        logger.debug(
                            f"  [{i}/{len(extracted)}] Processing {record['uid']}")
                        if download_documents(record["url"], session, record["uid"]):
                            forms_downloaded += 1
                        else:
                            forms_failed += 1
                        # Delay between each application's download to avoid rate limiting
                        time.sleep(5)
                    else:
                        logger.debug(
                            f"  [{i}/{len(extracted)}] Skipping {record['uid']} (no URL)")

                logger.info(
                    f"  Application forms for {area_name}: {forms_downloaded} downloaded, {forms_failed} failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract planning applications")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--save-pdf", action="store_true",
                        help="Download PDFs for each application")
    args = parser.parse_args()

    main(args.start_date, args.end_date, args.save_pdf)
