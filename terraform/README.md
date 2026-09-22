# Terraform Infrastructure

This directory contains the Terraform configuration for the Planning Application Watchdog infrastructure on AWS. The infrastructure is divided into several modules that work together to provide a complete monitoring and notification system.

## Overview

The Terraform configuration deploys the following key components:

1. **Dashboard** - A Streamlit-based web interface for viewing planning application data
2. **ETL Pipeline** - Lambda function that extracts, transforms, and loads planning data
3. **Notification System** - Lambda function that sends email notifications to users
4. **Data Storage** - DynamoDB tables and S3 buckets for data persistence

## Architecture Files

### main.tf
Core AWS provider configuration and global resources:
- **AWS Provider** - Configured for eu-west-2 (London region)
- **Terraform Backend** - S3 bucket (`c25-planning-terraform-config`) for remote state storage with encryption
- **VPC Data Source** - References existing VPC
- **ECS Cluster Data Source** - References existing ECS cluster (`c25-ecs-cluster`)
- **Public Subnets Data Source** - Retrieves public subnets from the VPC

### dashboard.tf
Dashboard application infrastructure using ECS Fargate:
- **ECR Repository** - `c25-planning-dashboard-repo` for dashboard container images
- **IAM Role** - `c25-planning-dashboard-ecs-role` with permissions for:
  - Reading from S3 bucket
  - Writing logs to CloudWatch
  - Accessing DynamoDB tables (read and write)
- **Security Group** - `c25-planning-dashboard-sg` allowing:
  - Inbound: Port 8501 (Streamlit), port 443 (HTTPS)
  - Outbound: Ports 80, 443 (HTTP/HTTPS), 53 (DNS)
- **CloudWatch Log Group** - `/ecs/c25-planning-dashboard` with 7-day retention
- **ECS Task Definition** - `c25-planning-dashboard-task` configured with:
  - 1 CPU (1024 units)
  - 2 GB memory
  - Fargate launch type
  - Container port 8501 exposed
- **ECS Service** - `c25-planning-dashboard` running 1 task in the ECS cluster with public IP assignment

### pipeline.tf
Extract, Transform, Load (ETL) pipeline infrastructure:
- **DynamoDB Tables**:
  - `c25-planning-data-db` - Stores planning application data with partition key `area` and sort key `uid`
  - `c25-planning-user-db` - Stores user subscriptions with partition key `area` and sort key `email`
  - Both use pay-per-request billing
- **S3 Bucket** - `c25-planning-files-bucket` for storing planning documents with public access blocked
- **ECR Repository** - `c25-planning-etl-repo` for ETL Lambda container images
- **Lambda Function** - `c25-planning-etl` configured with:
  - 512 MB memory
  - 600 second timeout
  - Permissions for S3 operations and DynamoDB access
- **EventBridge Schedule** - `c25-planning-etl-schedule` triggering Lambda daily at 2:00 AM (GMT)
- **IAM Roles and Policies** - `c25-planning-etl-lambda-role` and `c25-planning-schedule-etl-role` with appropriate permissions

### notification.tf
Notification system infrastructure:
- **ECR Repository** - `c25-planning-notification-repo` for notification Lambda container images
- **Lambda Function** - `c25-planning-notification` configured with:
  - 256 MB memory
  - 60 second timeout
  - Permissions for DynamoDB access and SES email sending
- **EventBridge Schedule** - Triggers notification Lambda on a schedule
- **IAM Roles and Policies** - `c25-planning-notification-lambda-role` and `c25-planning-notification-schedule-role` with permissions for logging, DynamoDB queries, and SES email operations

### variables.tf
Configuration variables:
- `aws_region` - AWS region (default: `eu-west-2`)
- `aws_access_key` - AWS access key ID
- `aws_secret_key` - AWS secret access key
- `vpc_id` - VPC identifier
- `ecs_cluster_name` - ECS cluster name (default: `c25-ecs-cluster`)
- `subnet_group_name` - Subnet group name (default: `c25-public-subnet`)
- `account_id` - AWS account ID (default: `129033205317`)

### terraform.tfvars
Contains variable values for the Terraform deployment (not tracked in version control for security).

## Deployment Prerequisites

- AWS account with appropriate credentials
- Existing VPC and ECS cluster
- AWS CLI configured
- Terraform CLI installed (version ~> 1.0)

## Resource Costs

Estimated monthly costs:

- **ECS Service (Fargate)** - Runs dashboard with 1 CPU and 2 GB memory: ~£41.45
- **Lambda Functions** - Both ETL and notification functions: £0 (free tier)
- **EventBridge Schedules** - Two schedules for ETL and notification triggers: £0 (free tier)
- **DynamoDB Tables** - For 1,000 application reads per day and 100 user accesses daily: <£0.50
- **S3 Bucket** - Storage for planning documents at £0.018/GB/month (currently ~30 MB): ~£0
- **ECR Repositories** - Three repositories for dashboard, ETL, and notification images: £0 (under 50 GB is free)
- **SES Email Service** - For 100 subscribers with 2-3 areas receiving notifications daily: <£1.00
- **Total estimated monthly cost**: ~£43.00

## Deployment

1. Configure `terraform.tfvars` with your AWS credentials and environment values
2. Run `terraform init` to initialise the backend
3. Run `terraform plan` to review changes
4. Run `terraform apply` to deploy resources

## Notes

- All resources follow the naming convention `c25-planning-*`
- DynamoDB tables use pay-per-request billing for flexibility
- Dashboard is publicly accessible via port 8501
- Logs are retained for 7 days
- ETL pipeline runs daily at 2:00 AM GMT
- Email notifications are sent via AWS SES