# Planning Application Watchdog Dashboard

An interactive Streamlit dashboard for monitoring planning applications across Tower Hamlets, Newham, and Greenwich London boroughs.

## Features

- **Interactive Map**: View all planning applications with marker clustering and layer controls
- **Real-time Filtering**: Filter by council area, application type, status, date range, and postcode proximity
- **AI Summaries**: Generate AI-powered summaries of planning applications
- **Heritage Integration**: View nearby heritage sites and conservation areas
- **Email Alerts**: Subscribe to notifications for planning applications in your area
- **Dark Theme**: Easy-on-the-eyes dark green theme

## Quick Start

### Prerequisites

- Python 3.8+
- AWS credentials configured (for DynamoDB access)
- `.env` file with required credentials

### Installation & Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure Streamlit (optional - already included in .streamlit/config.toml)
# The dark theme is pre-configured

# Run the dashboard
streamlit run dashboard_v2.py
```

### Docker Build

```bash
docker build -t planning-watchdog-dashboard .
docker run -p 8501:8501 --env-file .env planning-watchdog-dashboard
```

## Environment Variables

Create a `.env` file in the dashboard directory with the following variables:

```
AWS_ACCESS_KEY_ID=<your_aws_access_key>
AWS_SECRET_ACCESS_KEY=<your_aws_secret_key>
AWS_REGION=<your_aws_region>
OPENAI_API_KEY=<your_openai_api_key>
```

**Note**: Do not commit `.env` to version control. Use `.env.example` as a template.

## Data Sources

- **Planning Applications**: AWS DynamoDB (populated by pipeline)
- **Heritage Sites**: UK Heritage API
- **Conservation Areas**: UK Planning API
- **Postcode Coordinates**: UK Postcodes API
- **AI Summaries**: OpenAI GPT API

## Architecture

```
dashboard_v2.py          # Main Streamlit application
├── data_functions.py    # AWS DynamoDB and API interactions
├── ai_summary_functions.py  # OpenAI integration
└── dynamodb_functions.py    # Email subscription management
```

## Configuration

Dashboard theme settings are in `.streamlit/config.toml`:
- Primary Color: Green (#2e7d32)
- Background: Dark green (#0d1f12)
- Text: Light green (#e6f2e6)

## Troubleshooting

- **No applications loading**: Check AWS credentials in `.env` and DynamoDB connectivity
- **AI summaries not generating**: Verify OpenAI API key is valid
- **Postcode search failing**: Check UK Postcodes API key and rate limits

## Development

The dashboard supports live reloading during development:
```bash
streamlit run dashboard_v2.py --logger.level=debug
```
