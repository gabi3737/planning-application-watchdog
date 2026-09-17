# DynamoDB Tables

resource "aws_dynamodb_table" "c25_planning_data_db" {
  name         = "c25-planning-data-db"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "area"
  range_key    = "uid"

  attribute {
    name = "area"
    type = "S"
  }

  attribute {
    name = "uid"
    type = "S"
  }

} # Maybe add GSI for postcode


resource "aws_dynamodb_table" "c25_planning_user_db" {
  name         = "c25-planning-user-db"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "area"
  range_key    = "email"

  attribute {
    name = "area"
    type = "S"
  }

  attribute {
    name = "email"
    type = "S"
  }

}

# S3 bucket:

resource "aws_s3_bucket" "c25_planning_files_bucket" {
  bucket = "c25-planning-files-bucket"
}

resource "aws_s3_bucket_public_access_block" "c25_planning_files_bucket" {
  bucket = aws_s3_bucket.c25_planning_files_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ECR for Lambda:

resource "aws_ecr_repository" "pipeline_image_repo" {
  name = "c25-planning-etl-repo"
  image_tag_mutability = "MUTABLE"
}

# Lambda Function:

resource "aws_lambda_function" "etl_lambda" {
  function_name = "c25-planning-etl"
  role          = aws_iam_role.etl_lambda_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.pipeline_image_repo.repository_url}:latest"

  memory_size = 512
  timeout     = 60
}

# EventBridge Schedule:

resource "aws_scheduler_schedule" "etl-schedule" {
  name                         = "c25-planning-etl-schedule"
  group_name = "default"
  schedule_expression          = "cron(0 10 * * ? *)"
  schedule_expression_timezone = "Europe/London"
  
  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.etl_lambda.arn
    role_arn = aws_iam_role.schedule_etl_role.arn
  }
}
