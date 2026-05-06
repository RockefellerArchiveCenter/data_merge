import json
from os import environ
from unittest.mock import ANY, call, patch

import boto3
from moto import mock_aws
from moto.core import DEFAULT_ACCOUNT_ID

from src.merge_data import (get_session_token, lambda_handler,
                            send_failure_message, send_success_message)

DEFAULT_CONFIG = {
    "AS_BASEURL": "https://as.rockarch.org/api",
    "AS_SESSION_TOKEN": "mysecretsessiontoken",
    "CARTOGRAPHER_BASEURL": "https://cartographer.rockarch.org",
    "CARTOGRAPHER_HEALTH_CHECK_PATH": "/status",
    "SNS_TOPIC": "sns-topic"
}


def set_up_sns():
    client = boto3.client('sns', region_name='us-east-1')
    topic_arn = client.create_topic(Name='test-topic.fifo', Attributes={'FifoTopic': 'true'})['TopicArn']
    DEFAULT_CONFIG['SNS_TOPIC'] = topic_arn
    sqs_conn = boto3.resource('sqs', region_name='us-east-1')
    sqs_conn.create_queue(QueueName="test-queue")
    client.subscribe(
        TopicArn=topic_arn,
        Protocol="sqs",
        Endpoint=f"arn:aws:sqs:us-east-1:{DEFAULT_ACCOUNT_ID}:test-queue",
    )
    queue = sqs_conn.get_queue_by_name(QueueName="test-queue")
    return queue


@patch('src.merge_data.get_config')
@patch('src.merge_data.get_session_token')
@patch('src.mergers.ArchivalObjectMerger.__init__')
@patch('src.mergers.ArchivalObjectMerger.merge')
@patch('src.merge_data.send_success_message')
@patch('src.merge_data.send_failure_message')
def test_lambda_handler(mock_failure_message, mock_success_message, mock_merge, mock_init, mock_session_token, mock_config):
    mock_config.return_value = DEFAULT_CONFIG
    mock_session_token.return_value = "mysecretsessiontoken"
    mock_init.return_value = None
    mock_merge.return_value = {"data": "merged"}, "object"
    records = [
        {
            'body': '{"uri": "/repositories/2/archival_objects/1"}',
            'messageAttributes': {
                'object_type': {'stringValue': 'archival_object'},
                'service': {'stringValue': 'data_fetch'},
                'session_token_key': {'stringValue': 'AS_SESSION_TOKEN_ARCHIVAL_OBJECT_UPDATED'}
            }
        },
        {
            'body': '{"uri": "/repositories/2/archival_objects/2"}',
            'messageAttributes': {
                'object_type': {'stringValue': 'archival_object'},
                'service': {'stringValue': 'data_fetch'},
                'session_token_key': {'stringValue': 'AS_SESSION_TOKEN_ARCHIVAL_OBJECT_UPDATED'}
            }
        }
    ]

    lambda_handler({'Records': records}, None)

    mock_config.assert_called_once()
    mock_session_token.assert_has_calls([
        call('data_fetch', 'AS_SESSION_TOKEN_ARCHIVAL_OBJECT_UPDATED'),
        call('data_fetch', 'AS_SESSION_TOKEN_ARCHIVAL_OBJECT_UPDATED')])
    mock_init.assert_called_with(DEFAULT_CONFIG)
    assert mock_init.call_count == 2
    mock_merge.assert_has_calls([
        call({"uri": "/repositories/2/archival_objects/1"}),
        call({"uri": "/repositories/2/archival_objects/2"})])
    mock_success_message.assert_called_with(DEFAULT_CONFIG, {"data": "merged"}, "object")
    assert mock_success_message.call_count == 2
    mock_failure_message.assert_not_called()


@patch('src.merge_data.get_config')
@patch('src.merge_data.get_session_token')
@patch('src.mergers.ArchivalObjectMerger.__init__')
@patch('src.mergers.ArchivalObjectMerger.merge')
@patch('src.merge_data.send_success_message')
@patch('src.merge_data.send_failure_message')
def test_lambda_handler_with_exception(mock_failure_message, mock_success_message, mock_merge, mock_init, mock_session_token, mock_config):
    mock_config.return_value = DEFAULT_CONFIG
    mock_session_token.return_value = "mysecretsessiontoken"
    mock_init.return_value = None
    mock_merge.side_effect = Exception("foo")
    records = [
        {
            'body': '{"uri": "/repositories/2/archival_objects/1"}',
            'messageAttributes': {
                'object_type': {'stringValue': 'archival_object'},
                'service': {'stringValue': 'data_fetch'},
                'session_token_key': {'stringValue': 'AS_SESSION_TOKEN_ARCHIVAL_OBJECT_UPDATED'}
            }
        }]

    lambda_handler({'Records': records}, None)

    mock_success_message.assert_not_called()
    mock_failure_message.assert_called_once_with(
        DEFAULT_CONFIG,
        {'uri': '/repositories/2/archival_objects/1'},
        'archival_object',
        ANY)


@mock_aws
@patch.dict(environ, {"ENV": "dev"}, clear=False)
def test_get_session_token():
    session_token_key = "AS_SESSION_TOKEN_ARCHIVAL_OBJECT_UPDATED"
    source_service = "data_fetch"
    token_value = "mysecretsessiontoken"
    client = boto3.client('ssm', region_name='us-east-1')
    client.put_parameter(
        Name=f"/dev/{source_service}/{session_token_key}",
        Value=token_value,
        Type="String")
    output = get_session_token(source_service, session_token_key)
    assert output == token_value


@mock_aws
def test_success_message():
    queue = set_up_sns()
    send_success_message(DEFAULT_CONFIG, {"uri": "/repositories/2/archival_objects/1"}, "object")
    messages = queue.receive_messages(MaxNumberOfMessages=1)
    message_body = json.loads(messages[0].body)
    assert message_body['Message'] == '{"uri": "/repositories/2/archival_objects/1"}'
    assert message_body['MessageAttributes'] == {
        'service': {
            'Type': 'String',
            'Value': 'data_merge',
        },
        'requested_action': {
            'Type': 'String',
            'Value': 'transform',
        },
        'object_type': {
            'Type': 'String',
            'Value': 'object',
        }
    }


@mock_aws
def test_failure_message():
    queue = set_up_sns()
    send_failure_message(DEFAULT_CONFIG, {"uri": "/repositories/2/archival_objects/1"}, 'archival_object', Exception('foo'))
    messages = queue.receive_messages(MaxNumberOfMessages=1)
    message_body = json.loads(messages[0].body)
    assert message_body['Message'] == ''
    assert message_body['MessageAttributes'] == {
        'service': {
            'Type': 'String',
            'Value': 'data_merge',
        },
        'object_status': {
            'Type': 'String',
            'Value': 'updated',
        },
        'object_type': {
            'Type': 'String',
            'Value': 'archival_object',
        },
        'outcome': {
            'Type': 'String',
            'Value': 'FAILURE',
        },
        'message': {
            'Type': 'String',
            'Value': 'foo',
        }
    }
