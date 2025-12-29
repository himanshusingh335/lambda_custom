#!/usr/bin/env python3
"""
Simple local test for Lambda streaming function
"""

import time
from lambda_function import lambda_handler





# Test event
event = {
    "sentence": "Hello this is a streaming Lambda function"
}

# Run handler (no context needed)
result = lambda_handler(event)

# Print streamed output
for chunk in result:
    print(chunk.decode('utf-8'), end='', flush=True)

print()  # Final newline
