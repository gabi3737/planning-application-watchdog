# ECR for Lambda:

resource "aws_ecr_repository" "notification_image_repo" {
  name                 = "c25-planning-notification-repo"
  image_tag_mutability = "MUTABLE"
}

# Notification System Lambda Role

resource "aws_iam_role" "notification_lambda_role" {
  name = "c25-planning-notification-lambda-role"

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

resource "aws_iam_role_policy" "notification_lambda_policy" {
  role = aws_iam_role.notification_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [{
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
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:DescribeTable"
        ]

        Resource = aws_dynamodb_table.c25_planning_data_db.arn
      },
      {
        Effect = "Allow"

        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:DescribeTable"
        ]

        Resource = aws_dynamodb_table.c25_planning_user_db.arn
      }
    ]
  })
}

# Lambda Function:

resource "aws_lambda_function" "notification_lambda" {
  function_name = "c25-planning-notification"
  role          = aws_iam_role.notification_lambda_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.notification_image_repo.repository_url}:latest"

  memory_size = 256
  timeout     = 60
}
