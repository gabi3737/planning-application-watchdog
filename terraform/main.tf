# DynamoDB Tables

resource "aws_dynamodb_table" "c25-planning-data-db" {
  name         = "c25-planning-data-db"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "area"
  range_key    = "UID"

  attribute {
    name = "area"
    type = "S"
  }

  attribute {
    name = "UID"
    type = "S"
  }

} # Maybe add GSI for postcode


resource "aws_dynamodb_table" "c25-planning-user-db" {
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

# S3 terraform here:

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

      Resource = "" # future s3 resource here
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

        Resource = aws_dynamodb_table.c25-planning-data-db.arn
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

        Resource = aws_dynamodb_table.c25-planning-user-db.arn
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
