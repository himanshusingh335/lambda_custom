"""
Simple Lambda Handler with Response Streaming
Streams a sentence word by word as JSON chunks
"""

import time
import json
import random


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
        print(word, end="", flush=True)  # Log to CloudWatch (CloudWatch issue - to be fixed)
        yield (json.dumps(chunk) + '\n').encode('utf-8')
        # 80% chance of 0.5s, 20% chance of random between 0.5-2s
        sleep_duration = 0.5 if random.random() < 0.8 else random.uniform(0.5, 2.0)
        time.sleep(sleep_duration)
