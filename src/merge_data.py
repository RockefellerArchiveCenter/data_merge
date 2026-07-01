import json
import logging
import traceback
from os import getenv

import boto3
from requests.exceptions import ConnectionError
from urllib3.exceptions import ConnectTimeoutError, ProtocolError

from .mergers import (AgentMerger, ArchivalObjectMerger, ArrangementMapMerger,
                      ResourceMerger, SubjectMerger)

logger = logging.getLogger()
logger.setLevel(getenv('LOGGING_LEVEL', logging.INFO))

SERVICE_NAME = 'data_merge'
FULL_CONFIG_PATH = f"/{getenv('ENV')}/{getenv('APP_CONFIG_PATH')}"
MERGER_MAP = {
    "agent_corporate_entity": AgentMerger,
    "agent_family": AgentMerger,
    "agent_person": AgentMerger,
    "archival_object": ArchivalObjectMerger,
    "arrangement_map_component": ArrangementMapMerger,
    "resource": ResourceMerger,
    "subject": SubjectMerger,
}


def get_config(ssm_parameter_path):
    """Fetch config values from Parameter Store.

    Args:
        ssm_parameter_path (str): Path to parameters

    Returns:
        configuration (dict): all parameters found at the supplied path.
    """
    configuration = {}
    try:
        ssm_client = boto3.client(
            'ssm',
            region_name=getenv('AWS_DEFAULT_REGION', 'us-east-1'))

        param_details = ssm_client.get_parameters_by_path(
            Path=ssm_parameter_path,
            Recursive=False,
            WithDecryption=True)

        for param in param_details.get('Parameters', []):
            param_path_array = param.get('Name').split("/")
            section_position = len(param_path_array) - 1
            section_name = param_path_array[section_position]
            configuration[section_name] = param.get('Value')
    except BaseException:
        logging.error("Encountered an error loading config from SSM.")
        traceback.print_exc()
    finally:
        return configuration


def get_session_token(service, session_token_key):
    ssm_client = boto3.client(
        'ssm',
        region_name=getenv('AWS_DEFAULT_REGION', 'us-east-1'))
    response = ssm_client.get_parameter(Name=f"/{getenv('ENV')}/{service}/{session_token_key}")
    return response['Parameter']['Value']


def send_success_message(config, data, object_type):
    client = boto3.client('sns', region_name=getenv('AWS_DEFAULT_REGION', 'us-east-1'))
    client.publish(
        TopicArn=config['SNS_TOPIC'],
        MessageGroupId=f'{SERVICE_NAME}-{data["uri"]}',
        MessageDeduplicationId=f'{SERVICE_NAME}-{data["uri"]}-success',
        Message=json.dumps(data, default=str),
        MessageAttributes={
            'service': {
                'DataType': 'String',
                'StringValue': SERVICE_NAME,
            },
            'requested_action': {
                'DataType': 'String',
                'StringValue': 'transform',
            },
            'object_type': {
                'DataType': 'String',
                'StringValue': object_type,
            }
        })


def send_failure_message(config, data, object_type, exception):
    client = boto3.client('sns', region_name=getenv('AWS_DEFAULT_REGION', 'us-east-1'))
    tb = ''.join(traceback.format_exception(exception)[:-1])
    client.publish(
        TopicArn=config['SNS_TOPIC'],
        MessageGroupId=f'{SERVICE_NAME}-{data["uri"]}',
        MessageDeduplicationId=f'{SERVICE_NAME}-{data["uri"]}-failure',
        Message=tb,
        MessageAttributes={
            'service': {
                'DataType': 'String',
                'StringValue': SERVICE_NAME,
            },
            'object_status': {
                'DataType': 'String',
                'StringValue': 'updated',
            },
            'object_type': {
                'DataType': 'String',
                'StringValue': object_type,
            },
            'outcome': {
                'DataType': 'String',
                'StringValue': 'FAILURE',
            },
            'message': {
                'DataType': 'String',
                'StringValue': str(exception),
            }
        })


def lambda_handler(event, context):
    logger.info("Message batch received.")

    config = get_config(FULL_CONFIG_PATH)
    for record in event['Records']:
        try:
            object_data = json.loads(record['body'])
            attributes = record['messageAttributes']
            object_type = attributes['object_type']['stringValue']
            source_service = attributes['service']['stringValue']
            session_token_key = attributes['session_token_key']['stringValue']
            config['AS_SESSION_TOKEN'] = get_session_token(source_service, session_token_key)
            merger = MERGER_MAP[object_type]
            logging.debug(f"Starting merge with {object_data}")
            data, target_object_type = merger(config).merge(object_data)
            send_success_message(config, data, target_object_type)
            logging.debug(f"{object_type} object {data['uri']} merged")
        except (ConnectionError, ConnectTimeoutError, ProtocolError) as e:
            logging.error(e)
            raise Exception("Connection error, instance will be retried.")
        except Exception as e:
            logging.error(e)
            send_failure_message(config, object_data, object_type, e)
