variable "aws_region" {
  type        = string
  description = "AWS region for the resources"
  default = "eu-west-2"
}

variable "aws_access_key" {
  type        = string
  description = "AWS access key"
}

variable "aws_secret_key" {
  type        = string
  description = "AWS secret key"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "ecs_cluster_name" {
  type        = string
  description = "ECS cluster name"
  default = "c25-ecs-cluster"
}

variable "subnet_group_name" {
  type        = string
  description = "Subnet group name"
  default = "c25-public-subnet"
}

variable "account_id" {
  type        = string
  description = "AWS account ID"
  default = "129033205317"
}