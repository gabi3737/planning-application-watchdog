"""Pipeline for saving documents from planning application websites."""

import os
import io
import logging
from urllib.parse import urljoin
from pypdf import PdfReader
from bs4 import BeautifulSoup
from curl_cffi import requests
import certifi
from requests.exceptions import HTTPError

# Area - Area Code
# Newham - 318
# Tower Hamlets - 323
# Hackney - 305

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")

# Newham
NEWHAM_URL = "https://pa.newham.gov.uk/online-applications/applicationDetails.do?keyVal=TKQFJUJYHR000&activeTab=summary"
# Tower Hamlets
TOWER_HAMLETS_URL = "https://development.towerhamlets.gov.uk/online-applications/applicationDetails.do?keyVal=DCAPR_151446&activeTab=summary"


HEADERS = {
    "Referer": URL,
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/pdf"
}


def create_session() -> requests.Session:
    """Create and return a new HTTP session with impersonation."""
    session = requests.Session(impersonate="chrome124")
    return session


def convert_url_to_documents_url(url: str) -> str:
    """Convert a planning application summary URL to its corresponding documents URL."""
    if "activeTab=summary" in url:
        # Confirmed to work with Tower Hamlets and Newham Application Websites
        return url.replace("activeTab=summary", "activeTab=documents")
    return url


def load_webpage(url: str, session: requests.Session) -> BeautifulSoup:
    """Load the HTML content of a URL and return a BeautifulSoup object."""
    try:
        response = session.get(url,
                               allow_redirects=True, timeout=(5, 10), verify=certifi.where())
        response.raise_for_status()
    except HTTPError as e:
        logging.error(f"HTTP error loading webpage {url}: {e}")
        return None
    try:
        soup = BeautifulSoup(response.text, "html.parser")
        return soup
    except Exception as e:
        logging.error(f"Error loading html content from webpage {url}: {e}")
        return None


def find_pdf_urls(soup: BeautifulSoup, url: str):
    """Find and return all PDF URLs from the given BeautifulSoup object and base URL."""
    urls = []
    for link in soup.find_all("a", href=True):
        if link["href"].lower().endswith(".pdf"):
            full_url = urljoin(url, link["href"])
            urls.append(full_url)
    return urls


def get_pdf(url: str, session: requests.Session) -> bytes:
    """Download a PDF from the given URL using the provided session and return its content."""
    pdf = session.get(url,
                      allow_redirects=True, timeout=(5, 10),
                      verify=certifi.where(), headers=HEADERS)
    pdf.raise_for_status()
    return pdf.content


def save_pdf(content: bytes, filename: str):
    """Save the given PDF content as a PDF file in the 'documents' directory."""
    try:
        with open(os.path.join("documents", filename), "wb") as f:
            f.write(content)
    except PermissionError:
        logging.error(f"Permission denied: Unable to save {filename}")
    except OSError as e:
        logging.error(f"OS Error when saving {filename}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error when saving {filename}: {e}")


def read_pdf(content: bytes) -> None:
    """Read the given PDF content and print its text content."""
    with io.BytesIO(content) as pdf_file:
        print("PDF Reader")
        pdf_reader = PdfReader(pdf_file)
        for page in pdf_reader.pages:
            print(page.extract_text())


if __name__ == "__main__":
    session = create_session()
    url = convert_url_to_documents_url(TOWER_HAMLETS_URL)
    url = convert_url_to_documents_url(url)
    html_content = load_webpage(url, session)
    if html_content:
        pdf_urls = find_pdf_urls(html_content, url)
        pdf_url = pdf_urls[0]
        pdf_content = get_pdf(pdf_url, session)
        os.makedirs("documents", exist_ok=True)
        save_pdf(pdf_content, pdf_url.split("/")[-1])
        read_pdf(pdf_content)
