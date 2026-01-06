#!/usr/bin/env python3
"""
Test AWS Lambda streaming function using boto3's invoke_with_response_stream
Tests the deployed streaming-demo Lambda function in us-east-1
"""

import boto3
import json
import sys


def test_streaming_lambda():
    """Test Lambda function with response streaming"""

    print("Testing Lambda streaming function...")
    print("=" * 60)

    # Create Lambda client
    client = boto3.client('lambda', region_name='us-east-1')

    # Test event
    event = {
        "sentence": "Hello this is a streaming test from boto3"
    }

    print(f"\nSending event: {event}")
    print("\nStreaming response:\n")

    try:
        # Invoke with streaming
        response = client.invoke_with_response_stream(
            FunctionName='streaming-demo',
            Payload=json.dumps(event)
        )

        # Read event stream
        chunk_count = 0
        for event_item in response['EventStream']:
            if 'PayloadChunk' in event_item:
                # Decode and print chunk
                chunk = event_item['PayloadChunk']['Payload'].decode('utf-8')
                print(chunk, end='\n', flush=True)
                chunk_count += 1

            elif 'InvokeComplete' in event_item:
                # Stream complete
                complete_info = event_item['InvokeComplete']
                print(f"\n\n{'=' * 60}")
                print(f"Stream complete!")
                print(f"Chunks received: {chunk_count}")

                if 'ErrorCode' in complete_info:
                    print(f"Error: {complete_info.get('ErrorCode')}")
                    print(f"Error Details: {complete_info.get('ErrorDetails')}")
                    return False
                else:
                    print("Status: Success")
                    return True

    except Exception as e:
        print(f"\n\nError invoking Lambda: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_custom_sentence(sentence):
    """Test with a custom sentence"""

    print(f"\nTesting with custom sentence...")
    print("=" * 60)

    client = boto3.client('lambda', region_name='us-east-1')

    event = {"sentence": sentence}

    print(f"\nSending event: {event}")
    print("\nStreaming response:\n")

    try:
        response = client.invoke_with_response_stream(
            FunctionName='streaming-demo',
            Payload=json.dumps(event)
        )

        for event_item in response['EventStream']:
            if 'PayloadChunk' in event_item:
                chunk = event_item['PayloadChunk']['Payload'].decode('utf-8')
                print(chunk, end='', flush=True)

            elif 'InvokeComplete' in event_item:
                print(f"\n\n{'=' * 60}")
                print("Stream complete!")
                complete_info = event_item['InvokeComplete']
                if 'ErrorCode' not in complete_info:
                    print("Status: Success")
                    return True

    except Exception as e:
        print(f"\n\nError: {e}")
        return False


if __name__ == '__main__':
    # Run default test
    success = test_streaming_lambda()

    # If custom sentence provided as argument, test it
    if len(sys.argv) > 1:
        custom_sentence = ' '.join(sys.argv[1:])
        test_custom_sentence(custom_sentence)

    sys.exit(0 if success else 1)
