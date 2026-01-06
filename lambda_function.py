"""
Simple Lambda Handler with Response Streaming
Streams a sentence word by word as JSON chunks
"""

import time
import json


def lambda_handler(event, context=None):
    """
    Stream sentence word by word as JSON objects

    Args:
        event: {"sentence": "your sentence here"}
        context: Lambda context (optional, not used)

    Yields:
        bytes: Each word as JSON-serialized bytes
    """
    sentence = event.get('sentence', 'Hello world')
    words = sentence.split()

    for index, word in enumerate(words):
        chunk = {
            "word": word,
            "index": index,
            "total": len(words)
        }
        yield (json.dumps(chunk) + '\n').encode('utf-8')
        time.sleep(0.5)
