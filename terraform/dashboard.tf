# ECR for Dashboard
resource "aws_ecr_repository" "dashboard_repo" {
  name                 = "c25-planning-dashboard-repo"
  image_tag_mutability = "MUTABLE"
}

# Dashboard ECS Role

data "aws_iam_policy_document" "ecs_dashboard_trust_policy_doc" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    actions = [
      "sts:AssumeRole"
    ]
  }
}


data "aws_iam_policy_document" "ecs_dashboard_permissions_policy_doc" {
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = ["${aws_s3_bucket.c25_planning_files_bucket.arn}/*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem"
    ]
    resources = [aws_dynamodb_table.c25_planning_data_db.arn]
  }

  statement {
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem"
    ]
    resources = [aws_dynamodb_table.c25_planning_user_db.arn]
  }
}

resource "aws_iam_role" "ecs_dashboard_role" {
  name               = "c25-planning-dashboard-ecs-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_dashboard_trust_policy_doc.json
}

resource "aws_iam_policy" "ecs_dashboard_role_permissions_policy" {
  name   = "c25-planning-dashboard-ecs-permissions-policy"
  policy = data.aws_iam_policy_document.ecs_dashboard_permissions_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "ecs_dashboard_role_policy_connection" {
  role       = aws_iam_role.ecs_dashboard_role.name
  policy_arn = aws_iam_policy.ecs_dashboard_role_permissions_policy.arn
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_dashboard_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy_attachment" "ecs_ecr_pull_policy" {
  role       = aws_iam_role.ecs_dashboard_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}
# Dashboard Security Group

resource "aws_security_group" "ecs_dashboard_sg" {
  name        = "c25-planning-dashboard-sg"
  description = "Allow inbound and outbound traffic on port 8501, 443."
  vpc_id      = data.aws_vpc.vpc.id

  # Inbound: Streamlit traffic
  ingress {
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Inbound: HTTPS (for internet access)
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound: HTTPS (S3, DynamoDB, general internet)
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound: HTTP (for general internet access)
  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound: DNS (required for name resolution)
  egress {
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Dashboard CloudWatch

resource "aws_cloudwatch_log_group" "ecs_dashboard_logs" {
  name              = "/ecs/c25-planning-dashboard"
  retention_in_days = 7
}

# Dashboard ECS Task Definition

resource "aws_ecs_task_definition" "ecs_dashboard_task" {
  family                   = "c25-planning-dashboard-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_dashboard_role.arn
  task_role_arn            = aws_iam_role.ecs_dashboard_role.arn

  container_definitions = jsonencode([
    {
      name      = "c25-planning-dashboard-repo"
      image     = "${aws_ecr_repository.dashboard_repo.repository_url}:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8501
          hostPort      = 8501
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_dashboard_logs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

# Dashboard ECS Service

resource "aws_ecs_service" "planning_dashboard" {
  name            = "c25-planning-dashboard"
  cluster         = data.aws_ecs_cluster.ecs_cluster.id
  task_definition = aws_ecs_task_definition.ecs_dashboard_task.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.public_subnets.ids
    security_groups  = [aws_security_group.ecs_dashboard_sg.id]
    assign_public_ip = true
  }
}
