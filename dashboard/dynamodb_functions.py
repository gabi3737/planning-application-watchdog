"""DynamoDB functions for managing subscribers."""
import logging
import os
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Initialize DynamoDB resource
dynamodb = boto3.resource(
    'dynamodb', region_name=os.getenv('AWS_REGION', 'eu-west-2'))


def subscribe_user(area: str, email: str) -> dict:
    """
    Subscribe a user to planning application alerts for a specific area.

    Args:
        area: The area to subscribe to (Tower Hamlets, Newham, or Greenwich)
        email: The user's email address

    Returns:
        A dictionary with 'success' boolean and 'message' string
    """
    try:
        table_name = os.getenv(
            'DYNAMODB_SUBSCRIBERS_TABLE', 'c25-planning-user-db')
        table = dynamodb.Table(table_name)

        # Put item in DynamoDB
        table.put_item(
            Item={
                'email': email,
                'area': area,
                'subscribed_at': datetime.now().isoformat(),
                'active': True
            }
        )

        logger.info(f"User {email} subscribed to {area} alerts")
        return {
            'success': True,
            'message': f"Successfully subscribed {email} to {area} alerts!"
        }

    except ClientError as e:
        error_message = f"Error subscribing user: {e.response['Error']['Message']}"
        logger.error(error_message)
        return {
            'success': False,
            'message': error_message
        }
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message)
        return {
            'success': False,
            'message': error_message
        }


def get_subscribers(area: str = None) -> list:
    """
    Retrieve subscribers, optionally filtered by area.

    Args:
        area: Optional area filter

    Returns:
        List of subscriber dictionaries
    """
    try:
        table_name = os.getenv(
            'DYNAMODB_SUBSCRIBERS_TABLE', 'planning-app-subscribers')
        table = dynamodb.Table(table_name)

        if area:
            # Query by area (GSI required in DynamoDB)
            response = table.scan(
                FilterExpression='#area = :area AND #active = :active',
                ExpressionAttributeNames={
                    '#area': 'area',
                    '#active': 'active'
                },
                ExpressionAttributeValues={
                    ':area': area,
                    ':active': True
                }
            )
        else:
            # Get all active subscribers
            response = table.scan(
                FilterExpression='#active = :active',
                ExpressionAttributeNames={
                    '#active': 'active'
                },
                ExpressionAttributeValues={
                    ':active': True
                }
            )

        return response.get('Items', [])

    except ClientError as e:
        logger.error(
            f"Error retrieving subscribers: {e.response['Error']['Message']}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error retrieving subscribers: {str(e)}")
        return []


def unsubscribe_user(email: str) -> dict:
    """
    Unsubscribe a user from alerts.

    Args:
        email: The user's email address

    Returns:
        A dictionary with 'success' boolean and 'message' string
    """
    try:
        table_name = os.getenv(
            'DYNAMODB_SUBSCRIBERS_TABLE', 'planning-app-subscribers')
        table = dynamodb.Table(table_name)

        # Update the active status
        table.update_item(
            Key={'email': email},
            UpdateExpression='SET #active = :active',
            ExpressionAttributeNames={'#active': 'active'},
            ExpressionAttributeValues={':active': False}
        )

        logger.info(f"User {email} unsubscribed from alerts")
        return {
            'success': True,
            'message': f"Successfully unsubscribed {email} from alerts"
        }

    except ClientError as e:
        error_message = f"Error unsubscribing user: {e.response['Error']['Message']}"
        logger.error(error_message)
        return {
            'success': False,
            'message': error_message
        }
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message)
        return {
            'success': False,
            'message': error_message
        }
