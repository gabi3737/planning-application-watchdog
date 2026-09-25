terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = "c25-planning-terraform-config"
    key    = "state"
    region = "eu-west-2"
    encrypt = true
  }
}

provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
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