"""Functions to summarise documents using AI for Dashboard."""

import io
import os
import logging
import boto3
from botocore.exceptions import ClientError
from openai import OpenAI
from dotenv import load_dotenv
import pdfplumber
import streamlit as st

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")

logger = logging.getLogger(__name__)


def create_boto3_session() -> boto3.Session:
    """Creates and returns a boto3 session using environment variables."""
    if not os.getenv("ACCESS_KEY_ID") or not os.getenv("SECRET_ACCESS_KEY"):
        logger.error(
            "ACCESS_KEY_ID and SECRET_ACCESS_KEY must be set in the environment.")
        raise ValueError(
            "ACCESS_KEY_ID and SECRET_ACCESS_KEY must be set in the environment.")
    return boto3.Session(
        aws_access_key_id=os.getenv("ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "eu-west-2")
    )


@st.cache_data
def load_documents(_session: boto3.Session) -> dict:
    """Load all documents from the S3 bucket."""
    s3_client = _session.client("s3")

    bucket_name = os.getenv("PLANNING_FILES_BUCKET",
                            "c25-planning-files-bucket")
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        objects = {"Contents": [
            obj
            for page in paginator.paginate(
                Bucket=bucket_name, Prefix=f"documents/")
            for obj in page.get("Contents", [])
        ]}
    except ClientError as e:
        logger.error(f"Error loading documents from bucket {bucket_name}: {e}")
        return {}
    if not objects.get("Contents"):
        logger.warning(f"No documents found in bucket {bucket_name}.")
        return {}
    return objects


def find_document_by_uid(session: boto3.Session, objects: dict, uid: str) -> bytes:
    """Find a document from the S3 bucket using its UID."""
    s3_client = session.client("s3")
    bucket_name = os.getenv("PLANNING_FILES_BUCKET",
                            "c25-planning-files-bucket")
    for obj in objects.get("Contents", []):
        if uid in obj["Key"]:
            logger.info(
                f"Application document with UID {uid} found successfully.")
            response = s3_client.get_object(
                Bucket=bucket_name, Key=obj["Key"])
            pdf_content = response["Body"].read()
            return pdf_content
    logger.warning(f"Application document with UID {uid} not found.")
    return None


def save_pdf(uid: str, pdf_content: bytes) -> None:
    """Save the PDF content to a file named after the UID."""
    filename = f"{uid}.pdf"
    with open(filename, "wb") as f:
        f.write(pdf_content)
        logger.info(f"Document saved as {filename}")


def load_data_by_uid(session: boto3.Session, uid: str) -> dict:
    """Loads metadata associated to a planning application from its UID."""
    uid = uid.replace("_", "/")
    dynamodb_client = session.client("dynamodb")
    table_name = os.getenv("PLANNING_TABLE_NAME", "c25-planning-data-db")
    area = uid.split("/", 1)[0]
    try:
        response = dynamodb_client.get_item(
            TableName=table_name,
            Key={"area": {"S": area},
                 "uid": {"S": uid}}
        )
    except ClientError:
        logger.error(f"Table {table_name} does not exist.")
        return {}
    item = response.get("Item")
    if not item:
        logger.warning(f"No metadata found for UID {uid}")
        return {}
    return item


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF file represented as bytes."""
    logger.info(
        f"📄 Starting PDF text extraction (PDF size: {len(pdf_bytes)} bytes)")
    extracted = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            logger.info(f"📖 PDF has {len(pdf.pages)} pages")
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    logger.debug(
                        f"  Page {page_num}: extracted {len(text)} characters")
                    extracted.append(text)
                else:
                    logger.debug(f"  Page {page_num}: no text extracted")
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        return ""

    result = "\n".join(extracted)
    logger.info(
        f"✅ PDF extraction complete: {len(result)} total characters extracted")
    if len(result) == 0:
        logger.warning("⚠️  WARNING: PDF extraction returned empty text!")
    return result


def create_openai_client() -> OpenAI:
    """Create and return an OpenAI client using the API key from environment variables."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY must be set in the environment.")
        raise ValueError("OPENAI_API_KEY must be set in the environment.")

    client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
    return client


def summarise_document(openai_client: OpenAI, document_text: str, application_data: dict = {}) -> str:
    """Summarise the given document content using the OpenAI client."""
    uid = application_data.get("uid", "unknown")
    logger.info(f"🤖 [UID: {uid}] Generating summary...")
    logger.info(
        f"   PDF Text Status: {'✅ Present' if document_text else '❌ EMPTY'} ({len(document_text)} chars)")

    if not document_text:
        logger.error("No document content provided for summarisation.")
        return ""

    if document_text:
        logger.debug(f"   PDF Text Preview: {document_text[:200]}...")
    logger.debug(f"   Application Data: {application_data}")

    try:
        system_role = """
        You are a precise AI assistant which intakes both general information
        and PDF documents on planning applications. You provide a clear plain-English
        summary of the information based on the prompt given."""
        prompt = f"""
        Analyze the following text from a PDF document and related information. Then create
         a concise summary of what is being proposed and why it might matter. The summary
         should use clear, simple language, stay under 100 words, and contain no links.
         Do not add any bias on what you say, just factually summarise what the application is about.

        The information is stored as a dictionary with keys:
        - "address": The address of the planning application.
        - "app_size": Size of the planning application.
            - Large: Major, large scale developments
            - Medium: Other applications involving multiple dwellings
            - Small: All others
        - "app_state": Decision status for the application.
            - Undecided: The application is currently active, no decision has been made
            - Permitted: The application was approved
            - Conditions: The application was approved, but conditions were imposed
            - Rejected: The application was refused
            - Withdrawn: The application was withdrawn before a decision was taken
            - Referred: The application was referred to government or to another authority
            - Unresolved: The application is no longer active but no decision was made eg split decision
            - Other: Status not known
        - "app_type": Type of the planning application.
            - Full: Full and householder planning applications
            - Outline: Proposals prior to a full application, including assessments, scoping opinions, outline applications etc
            - Amendment: Amendments or alterations arising from existing or previous applications
            - Conditions: Discharge of conditions imposed on existing applications
            - Heritage: Conservation issues and listed buildings
            - Trees: Tree and hedge works
            - Advertising: Advertising and signs
            - Telecoms: Telecommunications including phone masts
            - Other: All other types eg agricultural, electrical
        - "area": The area where the planning application is located.
        - "url": The URL where more information about the planning application can be found.
    
        Application Information:
        {application_data}

        PDF File:
        {document_text}
        """
        logger.debug(f"   Calling OpenAI API...")
        response = openai_client.beta.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": system_role
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        summary = response.choices[0].message.content
        logger.info(f"✅ [UID: {uid}] OpenAI Response: {summary}")
        return summary
    except Exception as e:
        logger.error(f"Error summarising document: {e}")
        return ""


@st.cache_data
def get_ai_summary(_session: boto3.Session, data: dict, documents: dict) -> str:
    uid = data.get("uid")
    uid = uid.replace("/", "_")
    logger.info(f"\n📋 Starting summary generation for: {uid}")

    logger.info(f"  Step 1: Finding document in S3...")
    document = find_document_by_uid(_session, documents, uid)
    if document:
        logger.info(f"  ✅ Document found: {len(document)} bytes")
        logger.info(f"  Step 2: Extracting text from PDF...")
        pdf_text = extract_pdf_text(document)
        logger.info(f"  Step 3: Generating summary with OpenAI...")
        openai_client = create_openai_client()
        summary = summarise_document(openai_client, pdf_text, data)
        logger.info(f"  ✅ Summary generation complete for {uid}\n")
        return summary
    else:
        logger.error(f"  ❌ Document not found for {uid}.")
        return ""


if __name__ == "__main__":
    session = create_boto3_session()
    uid = "Greenwich_26_2646_SD"
    metadata = load_data_by_uid(session, uid)
    if metadata:
        logger.info("Metadata loaded successfully")
        data = {
            "address": metadata["address"],
            "app_size": metadata["app_size"],
            "app_state": metadata["app_state"],
            "app_type": metadata["app_type"],
            "area": metadata["area"],
            "url": metadata["url"]
        }
    else:
        logger.error("Metadata not found.")
        data = {}
    documents = load_documents(session)
    document = find_document_by_uid(session, documents, uid)
    save_pdf(uid, document)
    if document:
        logger.info(f"Document loaded successfully")
        pdf_text = extract_pdf_text(document)
        openai_client = create_openai_client()
        summary = summarise_document(openai_client, pdf_text, data)
        logger.info(f"Document summary: {summary}")
    else:
        logger.error("Document not found.")
