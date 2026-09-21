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
      },
      {
        Effect = "Allow"

        Action = [
          "ses:SendEmail"
        ]

        Resource = "*"
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


# Notification Lambda Schedule Role

data "aws_iam_policy_document" "notification_schedule_trust_policy_doc" {
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

data "aws_iam_policy_document" "notification_schedule_permissions_policy_doc" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:eu-west-2:${var.account_id}:*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "lambda:InvokeFunction"
    ]
    resources = [aws_lambda_function.notification_lambda.arn]
  }

  statement {
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.notification_schedule_role.arn]
    condition {
      test     = "StringLike"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "notification_schedule_role" {
  name               = "c25-planning-notification-schedule-role"
  assume_role_policy = data.aws_iam_policy_document.notification_schedule_trust_policy_doc.json
}

resource "aws_iam_policy" "notification_schedule_role_permissions_policy" {
  name   = "c25-planning-notification-schedule-permissions-policy"
  policy = data.aws_iam_policy_document.notification_schedule_permissions_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "notification_schedule_role_policy_connection" {
  role       = aws_iam_role.notification_schedule_role.name
  policy_arn = aws_iam_policy.notification_schedule_role_permissions_policy.arn
}

# EventBridge Schedule:

resource "aws_scheduler_schedule" "notification-schedule" {
  name                         = "c25-planning-notification-schedule"
  group_name                   = "default"
  schedule_expression          = "cron(0 8 * * ? *)"
  schedule_expression_timezone = "Europe/London"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.notification_lambda.arn
    role_arn = aws_iam_role.notification_schedule_role.arn
  }
}
