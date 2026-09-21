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
  name                 = "c25-planning-etl-repo"
  image_tag_mutability = "MUTABLE"
}

# ETL Pipeline Lambda Role

resource "aws_iam_role" "etl_lambda_role" {
  name = "c25-planning-etl-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [{
      Effect = "Allow"

      Principal = {
        Service = "lambda.amazonaws.com"
      }

      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_etl_policy" {
  role = aws_iam_role.etl_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [{
      Effect = "Allow"

      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]

      Resource = "${aws_s3_bucket.c25_planning_files_bucket.arn}/*"
      },
      {
        Effect = "Allow"

        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]

        Resource = "*"
      },
      {
        Effect = "Allow"

        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable"
        ]

        Resource = aws_dynamodb_table.c25_planning_data_db.arn
      },
      {
        Effect = "Allow"

        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable"
        ]

        Resource = aws_dynamodb_table.c25_planning_user_db.arn
      }
    ]
  })
}

# Lambda Function:

resource "aws_lambda_function" "etl_lambda" {
  function_name = "c25-planning-etl"
  role          = aws_iam_role.etl_lambda_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.pipeline_image_repo.repository_url}:latest"

  memory_size = 512
  timeout     = 600
}

# ETL Lambda Schedule Role

data "aws_iam_policy_document" "schedule_etl_trust_policy_doc" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    actions = [
      "sts:AssumeRole"
    ]
  }
}

data "aws_iam_policy_document" "schedule_etl_permissions_policy_doc" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:eu-west-2:129033205317:*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "lambda:InvokeFunction"
    ]
    resources = [aws_lambda_function.etl_lambda.arn]
  }

  statement {
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.schedule_etl_role.arn]
    condition {
      test     = "StringLike"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "schedule_etl_role" {
  name               = "c25-planning-schedule-etl-role"
  assume_role_policy = data.aws_iam_policy_document.schedule_etl_trust_policy_doc.json
}

resource "aws_iam_policy" "schedule_etl_role_permissions_policy" {
  name   = "c25-planning-schedule-etl-permissions-policy"
  policy = data.aws_iam_policy_document.schedule_etl_permissions_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "schedule_etl_role_policy_connection" {
  role       = aws_iam_role.schedule_etl_role.name
  policy_arn = aws_iam_policy.schedule_etl_role_permissions_policy.arn
}

# EventBridge Schedule:

resource "aws_scheduler_schedule" "etl-schedule" {
  name                         = "c25-planning-etl-schedule"
  group_name                   = "default"
  schedule_expression          = "cron(0 2 * * ? *)"
  schedule_expression_timezone = "Europe/London"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.etl_lambda.arn
    role_arn = aws_iam_role.schedule_etl_role.arn
  }
}
