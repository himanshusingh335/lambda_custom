#!/usr/bin/env python3
"""
AWS Lambda Custom Runtime for Response Streaming

This module implements the Lambda Runtime API client that enables
response streaming using HTTP chunked transfer encoding.
"""

import os
import sys
import json
import time
import traceback
import logging
from http.client import HTTPConnection
from urllib.parse import urlparse
from lambda_function import lambda_handler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s - %(message)s'
)
logger = logging.getLogger()

# Lambda Runtime API endpoint (provided by Lambda environment)
RUNTIME_API = os.environ.get('AWS_LAMBDA_RUNTIME_API')

# Runtime API URLs
NEXT_INVOCATION_URL = f"http://{RUNTIME_API}/2018-06-01/runtime/invocation/next"
RESPONSE_URL_TEMPLATE = "http://{runtime_api}/2018-06-01/runtime/invocation/{request_id}/response"
ERROR_URL_TEMPLATE = "http://{runtime_api}/2018-06-01/runtime/invocation/{request_id}/error"


class LambdaContext:
    """Lambda context object passed to handler function"""

    def __init__(self, headers):
        self.aws_request_id = headers.get('Lambda-Runtime-Aws-Request-Id', '')
        self.invoked_function_arn = headers.get('Lambda-Runtime-Invoked-Function-Arn', '')
        self.deadline_ms = headers.get('Lambda-Runtime-Deadline-Ms', '0')
        self.function_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', '')
        self.memory_limit_in_mb = os.environ.get('AWS_LAMBDA_FUNCTION_MEMORY_SIZE', '')
        self.version = os.environ.get('AWS_LAMBDA_FUNCTION_VERSION', '')
        self.log_group_name = os.environ.get('AWS_LAMBDA_LOG_GROUP_NAME', '')
        self.log_stream_name = os.environ.get('AWS_LAMBDA_LOG_STREAM_NAME', '')

    def get_remaining_time_in_millis(self):
        """Get remaining execution time in milliseconds"""
        return int(self.deadline_ms) - int(time.time() * 1000)


def stream_response(url, generator):
    """
    Stream generator output using HTTP chunked transfer encoding

    Args:
        url: Response URL for the Lambda invocation
        generator: Generator yielding byte chunks
    """
    parsed = urlparse(url)
    conn = HTTPConnection(parsed.netloc)

    try:
        # Send HTTP request with streaming headers
        conn.putrequest('POST', parsed.path)
        conn.putheader('Lambda-Runtime-Function-Response-Mode', 'streaming')
        conn.putheader('Transfer-Encoding', 'chunked')
        conn.endheaders()

        # Stream chunks using HTTP/1.1 chunked encoding format
        chunk_count = 0
        for chunk in generator:
            # Ensure chunk is bytes
            if isinstance(chunk, str):
                chunk = chunk.encode('utf-8')

            # Send chunk in format: {size_hex}\r\n{data}\r\n
            chunk_size = len(chunk)
            conn.send(f"{chunk_size:X}\r\n".encode())
            conn.send(chunk)
            conn.send(b"\r\n")
            chunk_count += 1

            logger.info(f"Sent chunk {chunk_count}, size: {chunk_size} bytes")

        # Send final chunk (0\r\n\r\n indicates end of stream)
        conn.send(b"0\r\n\r\n")
        logger.info(f"Streaming complete. Total chunks: {chunk_count}")

        # Read response from Lambda
        response = conn.getresponse()
        response_body = response.read()

        if response.status != 202:
            logger.error(f"Unexpected response status: {response.status}")
            logger.error(f"Response body: {response_body}")

    except Exception as e:
        logger.error(f"Error during streaming: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        conn.close()


def send_error(request_id, error):
    """
    Send error information to Lambda Runtime API

    Args:
        request_id: Lambda request ID
        error: Exception object
    """
    error_url = ERROR_URL_TEMPLATE.format(
        runtime_api=RUNTIME_API,
        request_id=request_id
    )

    error_data = {
        "errorMessage": str(error),
        "errorType": type(error).__name__,
        "stackTrace": traceback.format_exc().split('\n')
    }

    parsed = urlparse(error_url)
    conn = HTTPConnection(parsed.netloc)

    try:
        error_json = json.dumps(error_data)
        conn.request(
            'POST',
            parsed.path,
            body=error_json,
            headers={'Content-Type': 'application/json'}
        )
        response = conn.getresponse()
        response.read()

        logger.error(f"Error sent to Lambda: {error_data['errorType']} - {error_data['errorMessage']}")
    except Exception as e:
        logger.error(f"Failed to send error to Lambda: {str(e)}")
    finally:
        conn.close()


def get_next_invocation():
    """
    Poll for next Lambda invocation from Runtime API

    Returns:
        tuple: (event_data, request_id, context_headers)
    """
    parsed = urlparse(NEXT_INVOCATION_URL)
    conn = HTTPConnection(parsed.netloc)

    try:
        conn.request('GET', parsed.path)
        response = conn.getresponse()
        event_data = response.read()
        headers = dict(response.headers)

        # Parse event JSON
        event = json.loads(event_data) if event_data else {}
        request_id = headers.get('Lambda-Runtime-Aws-Request-Id', '')

        logger.info(f"Received invocation: {request_id}")

        return event, request_id, headers
    finally:
        conn.close()


def main():
    """
    Main runtime loop

    Continuously polls for invocations and processes them with streaming responses.
    """
    logger.info("Lambda custom runtime starting...")
    logger.info(f"Runtime API: {RUNTIME_API}")

    if not RUNTIME_API:
        logger.error("AWS_LAMBDA_RUNTIME_API environment variable not set")
        sys.exit(1)

    # Main event loop
    while True:
        request_id = None
        try:
            # 1. Get next invocation
            event, request_id, headers = get_next_invocation()

            # 2. Create context object (not passed to handler)
            context = LambdaContext(headers)

            # 3. Invoke handler (returns generator)
            logger.info(f"Invoking handler for request: {request_id}")
            result_generator = lambda_handler(event)

            # 4. Stream response using chunked encoding
            response_url = RESPONSE_URL_TEMPLATE.format(
                runtime_api=RUNTIME_API,
                request_id=request_id
            )

            stream_response(response_url, result_generator)
            logger.info(f"Successfully completed request: {request_id}")

        except Exception as e:
            logger.error(f"Error processing invocation: {str(e)}")
            logger.error(traceback.format_exc())

            if request_id:
                send_error(request_id, e)

            # Continue processing (don't exit runtime)
            continue


if __name__ == "__main__":
    main()
