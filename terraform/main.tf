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

