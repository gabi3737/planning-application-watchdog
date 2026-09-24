# Planning Application Watchdog Notifications

A scheduled AWS Lambda service that emails subscribed users a daily digest of new planning applications in their areas of interest (Tower Hamlets, Newham, and Greenwich).

## Features

- **Daily Digest**: Finds planning applications added today, yesterday, or the day before yesterday and matches them to subscribed users
- **Area Matching**: Groups subscribers by their areas of interest and filters applications accordingly
- **HTML Email Reports**: Renders matching applications as an HTML table in the email body
- **AWS SES Delivery**: Sends emails via Amazon SES
- **Lambda Entry Point**: Runs as a scheduled AWS Lambda function

## Quick Start

### Prerequisites

- Python 3.8+
- AWS credentials configured (for DynamoDB and SES access)
- `.env` file with required credentials

### Installation & Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run the notification job locally
python notification.py
```

### Docker Build

```bash
docker build -t planning-watchdog-notification .
docker run --env-file .env planning-watchdog-notification
```

## Environment Variables

Create a `.env` file in the notification directory with the following variables:

```
ACCESS_KEY_ID=<your_aws_access_key>
SECRET_ACCESS_KEY=<your_aws_secret_key>
AWS_REGION=<your_aws_region>
USER_TABLE_NAME=<dynamodb_subscribers_table_name>
PLANNING_TABLE_NAME=<dynamodb_planning_applications_table_name>
```

**Note**: Do not commit `.env` to version control. Use `.env.example` as a template.

## Data Sources

- **Subscribers**: AWS DynamoDB (populated via dashboard subscription form)
- **Planning Applications**: AWS DynamoDB (populated by pipeline)
- **Email Delivery**: Amazon SES

## Troubleshooting

- **No emails sent**: Check that subscribers exist with `active` set to `true` in DynamoDB
- **No matching applications found**: Verify planning data has a `start_date` within the last 3 days (today, yesterday, or the day before)
- **SES send failures**: Confirm the sender address is verified in Amazon SES and check IAM permissions

## Development

Run the test suite with:
```bash
pytest test_notification.py
```
