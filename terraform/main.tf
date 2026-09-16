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

# ETL Lambda function and roles/policies

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
        "s3:DeleteObject"
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
          "dynamodb:DeleteItem"
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
          "dynamodb:DeleteItem"
        ]

        Resource = aws_dynamodb_table.c25_planning_user_db.arn
      }
    ]
  })
}

resource "aws_lambda_function" "etl_lambda" {
  function_name = "c25-planning-etl"
  role          = aws_iam_role.etl_lambda_role.arn
  package_type  = "Image"
  image_uri     = var.etl_image_uri # Note: We currently don't have a URI

  memory_size = 512
  timeout     = 60
}
