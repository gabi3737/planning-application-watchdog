terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

data "aws_vpc" "vpc" {
    id = var.vpc_id
}

data "aws_ecs_cluster" "ecs_cluster" {
    cluster_name = var.ecs_cluster_name
}

data "aws_subnets" "public_subnets" {
    filter {
      name   = "vpc-id"
      values = [data.aws_vpc.vpc.id]
    }
}