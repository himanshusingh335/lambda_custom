"""
Simple Lambda Handler with Response Streaming
Streams a sentence word by word
"""

import time


def lambda_handler(event, context=None):
    """
    Stream sentence word by word

    Args:
        event: {"sentence": "your sentence here"}
        context: Lambda context (optional, not used)

    Yields:
        bytes: Each word as bytes
    """
    sentence = event.get('sentence', 'Hello world')
    words = sentence.split()

    for word in words:
        yield (word + ' ').encode('utf-8')
        time.sleep(0.5)
