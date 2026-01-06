#!/usr/bin/env python3
"""
AWS Lambda Custom Runtime with Response Streaming Support
Implements HTTP/1.1 chunked transfer encoding for streaming responses
"""

import json
import logging
import os
import sys
import time
import traceback
from http.client import HTTPConnection
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger()


class LambdaContext:
    """Lambda execution context object"""

    def __init__(self, request_id, deadline_ms, invoked_function_arn, trace_id):
        self.aws_request_id = request_id
        self.deadline_ms = int(deadline_ms)
        self.invoked_function_arn = invoked_function_arn
        self.trace_id = trace_id

        # Read from environment variables
        self.function_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'unknown')
        self.function_version = os.environ.get('AWS_LAMBDA_FUNCTION_VERSION', '$LATEST')
        self.memory_limit_in_mb = os.environ.get('AWS_LAMBDA_FUNCTION_MEMORY_SIZE', '128')
        self.log_group_name = os.environ.get('AWS_LAMBDA_LOG_GROUP_NAME', '')
        self.log_stream_name = os.environ.get('AWS_LAMBDA_LOG_STREAM_NAME', '')

    def get_remaining_time_in_millis(self):
        """Return remaining execution time in milliseconds"""
        remaining = self.deadline_ms - int(time.time() * 1000)
        return max(0, remaining)  # Never return negative


def get_next_invocation(runtime_api):
    """
    Poll the Runtime API for the next invocation event

    Returns:
        tuple: (request_id, event_dict, context)
    """
    url = f"http://{runtime_api}/2018-06-01/runtime/invocation/next"

    try:
        parsed = urlparse(url)
        conn = HTTPConnection(parsed.netloc)
        conn.request('GET', parsed.path)

        response = conn.getresponse()

        if response.status != 200:
            logger.error(f"Error getting next invocation: {response.status}")
            return None, None, None

        # Extract headers
        request_id = response.getheader('Lambda-Runtime-Aws-Request-Id')
        deadline_ms = response.getheader('Lambda-Runtime-Deadline-Ms')
        invoked_function_arn = response.getheader('Lambda-Runtime-Invoked-Function-Arn')
        trace_id = response.getheader('Lambda-Runtime-Trace-Id')

        # Set X-Ray trace ID
        if trace_id:
            os.environ['_X_AMZN_TRACE_ID'] = trace_id

        # Read event data
        event_data = response.read().decode('utf-8')
        event = json.loads(event_data) if event_data else {}

        # Create context
        context = LambdaContext(request_id, deadline_ms, invoked_function_arn, trace_id)

        conn.close()

        logger.info(f"Received invocation: {request_id}")
        return request_id, event, context

    except Exception as e:
        logger.error(f"Error in get_next_invocation: {e}")
        logger.error(traceback.format_exc())
        return None, None, None


def stream_response(runtime_api, request_id, generator):
    """
    Stream response using HTTP/1.1 chunked transfer encoding

    Args:
        runtime_api: Runtime API endpoint
        request_id: Request ID from Lambda
        generator: Generator that yields bytes
    """
    url = f"http://{runtime_api}/2018-06-01/runtime/invocation/{request_id}/response"

    try:
        parsed = urlparse(url)
        conn = HTTPConnection(parsed.netloc)

        # Send HTTP request with streaming headers
        conn.putrequest('POST', parsed.path)
        conn.putheader('Lambda-Runtime-Function-Response-Mode', 'streaming')
        conn.putheader('Transfer-Encoding', 'chunked')
        conn.endheaders()

        chunk_count = 0
        total_bytes = 0

        # Stream each chunk from the generator
        for chunk in generator:
            # Ensure chunk is bytes
            if isinstance(chunk, str):
                chunk = chunk.encode('utf-8')

            chunk_size = len(chunk)
            total_bytes += chunk_size
            chunk_count += 1

            # Send chunk in HTTP/1.1 chunked format
            # Format: {size_in_hex}\r\n{data}\r\n
            conn.send(f"{chunk_size:X}\r\n".encode())
            conn.send(chunk)
            conn.send(b"\r\n")

            logger.info(f"Sent chunk {chunk_count}: {chunk_size} bytes")

        # Send terminating chunk
        conn.send(b"0\r\n\r\n")

        # Read Lambda's acknowledgment
        response = conn.getresponse()
        response.read()

        if response.status == 202:
            logger.info(f"Stream complete: {chunk_count} chunks, {total_bytes} bytes")
        else:
            logger.error(f"Unexpected response status: {response.status}")

        conn.close()

    except Exception as e:
        logger.error(f"Error streaming response: {e}")
        logger.error(traceback.format_exc())
        raise


def send_error(runtime_api, request_id, error):
    """
    Send error response to Lambda Runtime API

    Args:
        runtime_api: Runtime API endpoint
        request_id: Request ID from Lambda
        error: Exception object
    """
    url = f"http://{runtime_api}/2018-06-01/runtime/invocation/{request_id}/error"

    try:
        error_dict = {
            "errorMessage": str(error),
            "errorType": type(error).__name__,
            "stackTrace": traceback.format_exception(type(error), error, error.__traceback__)
        }

        parsed = urlparse(url)
        conn = HTTPConnection(parsed.netloc)

        headers = {'Content-Type': 'application/json'}
        body = json.dumps(error_dict).encode('utf-8')

        conn.request('POST', parsed.path, body, headers)
        response = conn.getresponse()
        response.read()
        conn.close()

        logger.error(f"Error reported for {request_id}: {error}")

    except Exception as e:
        logger.error(f"Failed to send error: {e}")


def main():
    """Main runtime event loop"""

    # Get Runtime API endpoint from environment
    runtime_api = os.environ.get('AWS_LAMBDA_RUNTIME_API')

    if not runtime_api:
        logger.error("AWS_LAMBDA_RUNTIME_API environment variable not set")
        sys.exit(1)

    logger.info(f"Lambda custom runtime starting...")
    logger.info(f"Runtime API: {runtime_api}")
    logger.info(f"Function: {os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'unknown')}")

    # Import the handler function
    try:
        from lambda_function import lambda_handler
        logger.info("Handler imported successfully")
    except Exception as e:
        logger.error(f"Failed to import handler: {e}")
        sys.exit(1)

    # Main event loop - process invocations indefinitely
    while True:
        try:
            # Get next invocation
            request_id, event, context = get_next_invocation(runtime_api)

            if not request_id:
                logger.warning("No request_id received, retrying...")
                time.sleep(1)
                continue

            try:
                # Invoke the handler (returns generator)
                logger.info(f"Invoking handler for {request_id}")
                result = lambda_handler(event, context)

                # Stream the response
                stream_response(runtime_api, request_id, result)

            except Exception as handler_error:
                # Handler failed - report error
                logger.error(f"Handler error: {handler_error}")
                logger.error(traceback.format_exc())
                send_error(runtime_api, request_id, handler_error)

        except KeyboardInterrupt:
            logger.info("Runtime interrupted")
            break

        except Exception as e:
            logger.error(f"Runtime error: {e}")
            logger.error(traceback.format_exc())
            # Continue processing - don't exit on errors
            time.sleep(1)


if __name__ == '__main__':
    main()
