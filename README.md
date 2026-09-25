# Planning Application Watchdog

A comprehensive system for monitoring planning applications across Tower Hamlets, Newham, and Greenwich London boroughs (for an MVP). This repository contains an ETL data pipeline, interactive web dashboard, email notification service, and infrastructure-as-code for AWS deployment.

## Repository Structure

### 📊 [`dashboard/`](dashboard/)
**Interactive Streamlit web application for viewing and analyzing planning applications.**

- Real-time filtering by council area, application type, status, and date range
- Interactive folium map with marker clustering and layer controls
- Heritage sites and conservation areas visualization
- Email subscription management for planning alerts
- Dark green theme UI with responsive charts and analytics
- **Tech Stack**: Streamlit, Folium, Altair, Pandas, AWS DynamoDB, OpenAI API

**Key Files:**
- `dashboard.py` / `dashboard_v2.py` — Main Streamlit application
- `data_functions.py` — DynamoDB and API data loading
- `dynamodb_functions.py` — Email subscription management
- `requirements.txt` — Python dependencies
- `Dockerfile` — Container build for cloud deployment

---

### 📧 [`notification/`](notification/)
**Scheduled AWS Lambda service that sends daily email digests of new planning applications.**

- Runs daily to identify planning applications added in the last 3 days
- Matches subscribers to relevant applications by council area
- Sends HTML email reports via Amazon SES
- Can run locally or as a Lambda function
- **Tech Stack**: Python, Pandas, AWS DynamoDB, AWS SES, AWS Lambda

**Key Files:**
- `notification.py` — Core notification logic and Lambda entry point
- `requirements.txt` — Python dependencies (boto3, pandas, python-dotenv)
- `Dockerfile` — Container build for AWS Lambda runtime

---

### 🔄 [`pipeline/`](pipeline/)
**ETL (Extract → Transform → Load) data pipeline for planning applications.**

Extracts planning application data from the PlanIt API, transforms and validates the data, and loads it into AWS DynamoDB.

- **Extract** (`extract.py`) — Fetches from PlanIt API for respective areas; optionally downloads and uploads PDFs to S3
- **Transform** (`transform.py`) — Validates, standardizes, and type-casts DataFrame data in-memory
- **Load** (`load.py`) — Loads transformed data to DynamoDB; can orchestrate full pipeline

**Tech Stack**: Python, Pandas, Requests, AWS S3, AWS DynamoDB

**Key Features:**
- Supports date range filtering (`--start-date`, `--end-date`)
- Optional PDF document upload to S3
- Local testing mode (`--local`) without AWS credentials
- Deduplication by UID in DynamoDB

**Example Usage:**
```bash
# Full pipeline with PDF uploads
python3 load.py --pipeline --save-pdf

# Local testing mode (no AWS needed)
python3 load.py --pipeline --local --no-db
```

---

### 🏗️ [`terraform/`](terraform/)
**Infrastructure-as-code (IaC) for AWS deployment.**

Defines and manages all cloud resources using Terraform:
- **DynamoDB tables** for planning applications and user subscriptions
- **S3 buckets** for document storage
- **Lambda functions** for daily notifications
- **SES configuration** for email delivery
- **IAM roles and policies** for service permissions
- **Environment configuration** (terraform.tfvars)

**Tech Stack**: Terraform, AWS services (DynamoDB, S3, Lambda, SES, IAM)

---

## Quick Start

### Run Dashboard Locally

```bash
cd dashboard
pip install -r requirements.txt
streamlit run dashboard_v2.py
```

### Run Notification Service Locally

```bash
cd notification
pip install -r requirements.txt
python3 notification.py
```

### Run Data Pipeline

```bash
cd pipeline
pip install -r requirements.txt
python3 load.py --pipeline --save-pdf
```

### Deploy to AWS

```bash
cd terraform
terraform init
terraform plan
terraform apply
```
