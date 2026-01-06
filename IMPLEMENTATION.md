# Custom AWS Lambda Runtime Implementation Guide

## Overview

This document explains how we implemented a custom AWS Lambda runtime with response streaming support using Python 3.11 on Amazon Linux 2023.

---

## Table of Contents

1. [The Challenge](#the-challenge)
2. [Architecture](#architecture)
3. [Implementation Steps](#implementation-steps)
4. [Technical Details](#technical-details)
5. [Testing](#testing)
6. [Troubleshooting](#troubleshooting)

---

## The Challenge

**Problem**: AWS Lambda's managed Python runtimes (python3.11, python3.12) do not support response streaming.

**Solution**: Build a custom runtime using `provided.al2023` (Amazon Linux 2023) that:
- Implements the Lambda Runtime API
- Supports HTTP/1.1 chunked transfer encoding
- Streams responses progressively (not buffering)

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│  AWS Lambda (provided.al2023 runtime)                   │
│  ┌───────────────────────────────────────────────────┐  │
│  │  1. bootstrap (shell script)                      │  │
│  │     - Entry point Lambda invokes                  │  │
│  │     - Configures Python environment               │  │
│  │     - Executes runtime.py                         │  │
│  └───────────────────────────────────────────────────┘  │
│                         ↓                                │
│  ┌───────────────────────────────────────────────────┐  │
│  │  2. Python 3.11 Layer (/opt)                      │  │
│  │     - Python 3.11 binaries                        │  │
│  │     - Standard library                            │  │
│  │     - Compiled modules (.so files)                │  │
│  └───────────────────────────────────────────────────┘  │
│                         ↓                                │
│  ┌───────────────────────────────────────────────────┐  │
│  │  3. runtime.py (Custom Runtime API Client)        │  │
│  │     - Polls Runtime API for invocations           │  │
│  │     - Creates LambdaContext                       │  │
│  │     - Invokes handler generator                   │  │
│  │     - Streams chunks via HTTP/1.1                 │  │
│  └───────────────────────────────────────────────────┘  │
│                         ↓                                │
│  ┌───────────────────────────────────────────────────┐  │
│  │  4. lambda_function.py (Handler)                  │  │
│  │     - Generator function (uses yield)             │  │
│  │     - Yields bytes (JSON chunks)                  │  │
│  │     - Each word sent with 0.5s delay              │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ↓
              HTTP Response Stream
                   (chunked)
                         ↓
                      Client
```

### File Structure

```
lambda_custom/
├── bootstrap              # Lambda entry point (executable)
├── runtime.py            # Custom Runtime API client
├── lambda_function.py    # Handler function (generator)
├── test_streaming.py     # boto3 test client
├── function.zip          # Deployment package
├── python-layer/         # Python 3.11 extracted files
├── python311-layer-x86.zip  # Layer deployment package
└── IMPLEMENTATION.md     # This file
```

---

## Implementation Steps

### Step 1: Create the Bootstrap File

**Purpose**: Lambda entry point that AWS invokes to start the runtime.

**File**: `bootstrap`

```bash
#!/bin/sh
# AWS Lambda Custom Runtime Bootstrap

cd $LAMBDA_TASK_ROOT

# Configure Python from Lambda Layer (extracted to /opt)
export PYTHONHOME=/opt
export LD_LIBRARY_PATH=/opt/lib:/var/lang/lib:$LD_LIBRARY_PATH
export PYTHONPATH=/opt/lib/python3.11:/opt/lib/python3.11/lib-dynload:$PYTHONPATH

if [ -x /opt/bin/python3.11 ]; then
    exec /opt/bin/python3.11 runtime.py
else
    echo "ERROR: Python 3.11 not found in layer" >&2
    exit 127
fi
```

**Key Requirements**:
- Must be executable (`chmod +x bootstrap`)
- Must set `PYTHONHOME` to `/opt` (where layer extracts)
- Must set `LD_LIBRARY_PATH` for shared libraries
- Must set `PYTHONPATH` for Python modules

**Critical**: Execute permissions must be set BEFORE creating the zip file!

---

### Step 2: Build the Python 3.11 Layer

**Challenge**: `provided.al2023` is a minimal OS without any language runtimes.

**Solution**: Extract Python 3.11 from Amazon Linux 2023 Docker image.

#### Extract Python from Docker

```bash
# Create output directory
mkdir -p python-layer

# Extract Python from AL2023 image (x86_64 architecture)
docker run --rm --platform linux/amd64 --entrypoint="" \
  -v $(pwd)/python-layer:/output \
  public.ecr.aws/lambda/provided:al2023 \
  sh -c "
    dnf install -y python3.11 python3.11-libs && \
    mkdir -p /output/bin /output/lib && \
    cp -P /usr/bin/python3.11 /output/bin/ && \
    cp -rP /usr/lib64/python3.11 /output/lib/ && \
    cp -P /usr/lib64/libpython3.11.so* /output/lib/
  "
```

**Important Notes**:
- Use `--platform linux/amd64` for x86_64 (Lambda default architecture)
- Use `--platform linux/arm64` for ARM64 (Graviton)
- Must match your Lambda function's architecture!

#### Create Layer Zip

```bash
cd python-layer
zip -r ../python311-layer-x86.zip bin/ lib/
cd ..
```

**Layer Structure**:
```
python311-layer-x86.zip
├── bin/
│   └── python3.11        # Python executable
└── lib/
    ├── libpython3.11.so.1.0  # Shared library
    └── python3.11/       # Standard library
        ├── encodings/
        ├── lib-dynload/  # Compiled modules (.so)
        └── ... (all stdlib modules)
```

#### Publish Layer to AWS

```bash
aws lambda publish-layer-version \
  --layer-name python311-al2023 \
  --description "Python 3.11 for Amazon Linux 2023 (x86_64)" \
  --compatible-runtimes provided.al2023 \
  --compatible-architectures x86_64 \
  --zip-file fileb://python311-layer-x86.zip \
  --region us-east-1
```

**Output**: You'll get a Layer ARN like:
```
arn:aws:lambda:us-east-1:ACCOUNT_ID:layer:python311-al2023:VERSION
```

---

### Step 3: Implement the Custom Runtime (runtime.py)

**Purpose**: Poll Lambda Runtime API, invoke handler, stream responses.

#### Key Components

##### 3.1 LambdaContext Class

Provides execution context to the handler function.

```python
class LambdaContext:
    def __init__(self, request_id, deadline_ms, invoked_function_arn, trace_id):
        self.aws_request_id = request_id
        self.deadline_ms = int(deadline_ms)
        self.invoked_function_arn = invoked_function_arn
        self.trace_id = trace_id

        # Read from environment
        self.function_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
        self.function_version = os.environ.get('AWS_LAMBDA_FUNCTION_VERSION')
        # ... other attributes

    def get_remaining_time_in_millis(self):
        """Return remaining execution time"""
        remaining = self.deadline_ms - int(time.time() * 1000)
        return max(0, remaining)
```

##### 3.2 Get Next Invocation

Polls the Runtime API for the next event.

```python
def get_next_invocation(runtime_api):
    """Poll Runtime API for next invocation"""
    url = f"http://{runtime_api}/2018-06-01/runtime/invocation/next"

    conn = HTTPConnection(runtime_api)
    conn.request('GET', '/2018-06-01/runtime/invocation/next')
    response = conn.getresponse()

    # Extract headers
    request_id = response.getheader('Lambda-Runtime-Aws-Request-Id')
    deadline_ms = response.getheader('Lambda-Runtime-Deadline-Ms')
    invoked_function_arn = response.getheader('Lambda-Runtime-Invoked-Function-Arn')
    trace_id = response.getheader('Lambda-Runtime-Trace-Id')

    # Set X-Ray trace ID
    if trace_id:
        os.environ['_X_AMZN_TRACE_ID'] = trace_id

    # Parse event
    event_data = response.read().decode('utf-8')
    event = json.loads(event_data)

    # Create context
    context = LambdaContext(request_id, deadline_ms, invoked_function_arn, trace_id)

    conn.close()
    return request_id, event, context
```

**Runtime API Endpoints**:
- **Next Invocation**: `GET http://{RUNTIME_API}/2018-06-01/runtime/invocation/next`
  - Blocks until event available
  - Returns event JSON + headers with metadata

##### 3.3 Stream Response with HTTP Chunked Encoding

**Critical Implementation**: This is the core streaming logic.

```python
def stream_response(runtime_api, request_id, generator):
    """Stream response using HTTP/1.1 chunked transfer encoding"""
    url = f"http://{runtime_api}/2018-06-01/runtime/invocation/{request_id}/response"

    parsed = urlparse(url)
    conn = HTTPConnection(parsed.netloc)

    # Send HTTP request with streaming headers
    conn.putrequest('POST', parsed.path)
    conn.putheader('Lambda-Runtime-Function-Response-Mode', 'streaming')  # REQUIRED
    conn.putheader('Transfer-Encoding', 'chunked')                        # REQUIRED
    conn.endheaders()

    # Stream each chunk from the generator
    for chunk in generator:
        # Ensure chunk is bytes
        if isinstance(chunk, str):
            chunk = chunk.encode('utf-8')

        chunk_size = len(chunk)

        # HTTP/1.1 chunked format: {size_hex}\r\n{data}\r\n
        conn.send(f"{chunk_size:X}\r\n".encode())  # Hex size + CRLF
        conn.send(chunk)                            # Data
        conn.send(b"\r\n")                          # CRLF

    # Send terminating chunk
    conn.send(b"0\r\n\r\n")

    # Read Lambda's acknowledgment
    response = conn.getresponse()
    response.read()

    conn.close()
```

**HTTP Chunked Encoding Format**:
```
1A\r\n
{"word":"Hello","index":0}\n\r\n
1B\r\n
{"word":"world","index":1}\n\r\n
0\r\n
\r\n
```

**Required Headers**:
1. `Lambda-Runtime-Function-Response-Mode: streaming` - Tells Lambda we're streaming
2. `Transfer-Encoding: chunked` - Enables HTTP/1.1 chunked encoding

##### 3.4 Error Handling

```python
def send_error(runtime_api, request_id, error):
    """Send error to Runtime API"""
    url = f"http://{runtime_api}/2018-06-01/runtime/invocation/{request_id}/error"

    error_dict = {
        "errorMessage": str(error),
        "errorType": type(error).__name__,
        "stackTrace": traceback.format_exception(...)
    }

    conn = HTTPConnection(runtime_api)
    body = json.dumps(error_dict).encode('utf-8')
    conn.request('POST', parsed.path, body, {'Content-Type': 'application/json'})

    response = conn.getresponse()
    response.read()
    conn.close()
```

##### 3.5 Main Event Loop

```python
def main():
    """Main runtime event loop"""
    runtime_api = os.environ.get('AWS_LAMBDA_RUNTIME_API')

    # Import handler
    from lambda_function import lambda_handler

    # Infinite event loop
    while True:
        try:
            # Get next invocation
            request_id, event, context = get_next_invocation(runtime_api)

            # Invoke handler (returns generator)
            result = lambda_handler(event, context)

            # Stream the response
            stream_response(runtime_api, request_id, result)

        except Exception as e:
            logger.error(f"Error: {e}")
            send_error(runtime_api, request_id, e)
            # Continue processing - don't exit!
```

**Important**: Never exit the loop - Lambda reuses the runtime for multiple invocations.

---

### Step 4: Handler Function (lambda_function.py)

**Purpose**: Business logic that yields chunks as bytes.

```python
import json
import time

def lambda_handler(event, context=None):
    """
    Stream sentence word by word as JSON objects

    Args:
        event: {"sentence": "your sentence here"}
        context: Lambda context (optional)

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
        # MUST yield bytes, not strings
        yield (json.dumps(chunk) + '\n').encode('utf-8')
        time.sleep(0.5)  # Simulate processing delay
```

**Key Requirements**:
- MUST be a generator (use `yield`)
- MUST yield bytes (not strings)
- Accept `(event, context)` parameters

---

### Step 5: Create Deployment Package

```bash
# Ensure bootstrap is executable
chmod +x bootstrap

# Verify permissions
ls -la bootstrap  # Should show -rwxr-xr-x

# Create zip with required files
zip function.zip bootstrap runtime.py lambda_function.py

# Verify structure (files must be in root, not subdirectory)
unzip -l function.zip
```

**Critical Files**:
- `bootstrap` (executable)
- `runtime.py`
- `lambda_function.py`

**Do NOT include**:
- `main.py` (local testing only)
- `test_streaming.py` (local testing only)
- `python-layer/` (deployed as separate layer)

---

### Step 6: Deploy to AWS Lambda

#### Update Function Code

```bash
aws lambda update-function-code \
  --function-name streaming-demo \
  --zip-file fileb://function.zip \
  --region us-east-1
```

#### Update Runtime and Attach Layer

```bash
aws lambda update-function-configuration \
  --function-name streaming-demo \
  --runtime provided.al2023 \
  --layers arn:aws:lambda:us-east-1:ACCOUNT_ID:layer:python311-al2023:VERSION \
  --region us-east-1
```

#### Verify Function URL Configuration

```bash
aws lambda get-function-url-config \
  --function-name streaming-demo \
  --region us-east-1
```

**Required**: `InvokeMode` MUST be `RESPONSE_STREAM`

If not configured:
```bash
aws lambda create-function-url-config \
  --function-name streaming-demo \
  --auth-type NONE \
  --invoke-mode RESPONSE_STREAM \
  --region us-east-1
```

---

## Technical Details

### Why provided.al2023 Instead of Python Runtime?

| Feature | Managed Python (python3.11) | Custom Runtime (provided.al2023) |
|---------|----------------------------|----------------------------------|
| Response Streaming | ❌ Not supported | ✅ Full control via Runtime API |
| Python Version | Fixed by AWS | ✅ Any version you bundle |
| Startup Time | Faster (pre-installed) | Slower (layer extraction) |
| Complexity | Simple | More complex |
| Size | ~109 MB (AL2) | < 40 MB (AL2023 base) |

### Amazon Linux 2023 vs Amazon Linux 2

| Feature | AL2 (provided.al2) | AL2023 (provided.al2023) |
|---------|-------------------|-------------------------|
| Base Image Size | ~109 MB | < 40 MB |
| glibc Version | 2.26 | 2.34 |
| Package Manager | yum | dnf/microdnf |
| Python Availability | ❌ Not included | ❌ Not included |
| Use Case | Older, stable | Modern, optimized |

### HTTP/1.1 Chunked Transfer Encoding

**Format**:
```
{chunk_size_in_hex}\r\n
{chunk_data}\r\n
{next_chunk_size_in_hex}\r\n
{next_chunk_data}\r\n
...
0\r\n
\r\n
```

**Example with actual data**:
```
2A\r\n
{"word":"Hello","index":0,"total":2}\n\r\n
2A\r\n
{"word":"world","index":1,"total":2}\n\r\n
0\r\n
\r\n
```

**Explanation**:
- `2A` = 42 in hexadecimal (size of JSON + newline)
- `\r\n` = CRLF (carriage return + line feed)
- `0\r\n\r\n` = Terminating chunk (size 0, double CRLF)

### Lambda Runtime API Flow

```
┌──────────────┐
│   Runtime    │
│   Startup    │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────┐
│ Infinite Loop:                       │
│                                      │
│  1. GET /invocation/next (blocks)   │
│     ↓                                │
│  2. Parse event + headers           │
│     ↓                                │
│  3. Create LambdaContext            │
│     ↓                                │
│  4. Invoke handler(event, context)  │
│     ↓                                │
│  5. Stream response chunks          │
│     ↓                                │
│  6. POST /invocation/{id}/response  │
│     ↓                                │
│  7. Loop back to step 1             │
└──────────────────────────────────────┘
```

### Environment Variables Used

**Provided by Lambda**:
- `AWS_LAMBDA_RUNTIME_API` - Runtime API endpoint (e.g., "127.0.0.1:9001")
- `AWS_LAMBDA_FUNCTION_NAME` - Function name
- `AWS_LAMBDA_FUNCTION_VERSION` - Version ($LATEST or number)
- `AWS_LAMBDA_FUNCTION_MEMORY_SIZE` - Memory in MB
- `AWS_LAMBDA_LOG_GROUP_NAME` - CloudWatch log group
- `AWS_LAMBDA_LOG_STREAM_NAME` - CloudWatch log stream
- `LAMBDA_TASK_ROOT` - Task directory (/var/task)

**Set by Bootstrap**:
- `PYTHONHOME` - Python installation root (/opt)
- `LD_LIBRARY_PATH` - Shared library search path
- `PYTHONPATH` - Python module search path
- `_X_AMZN_TRACE_ID` - X-Ray trace ID (if tracing enabled)

---

## Testing

### Local Testing (Without Lambda)

```bash
# Test handler in isolation
python3 main.py
```

This runs the generator locally and prints output.

### Remote Testing with curl

```bash
curl -X POST https://YOUR-FUNCTION-URL/ \
  -H "Content-Type: application/json" \
  -d '{"sentence": "Test one two three"}' \
  --no-buffer
```

**Critical**: Use `--no-buffer` flag to see progressive streaming!

**Expected Output**:
```json
{"word": "Test", "index": 0, "total": 4}
{"word": "one", "index": 1, "total": 4}
{"word": "two", "index": 2, "total": 4}
{"word": "three", "index": 3, "total": 4}
```

Each line appears with a 0.5-second delay (not all at once).

### Remote Testing with boto3

```python
import boto3
import json

client = boto3.client('lambda', region_name='us-east-1')

event = {"sentence": "Hello streaming world"}

response = client.invoke_with_response_stream(
    FunctionName='streaming-demo',
    Payload=json.dumps(event)
)

# Read event stream
for event in response['EventStream']:
    if 'PayloadChunk' in event:
        chunk = event['PayloadChunk']['Payload'].decode('utf-8')
        print(chunk, end='', flush=True)
    elif 'InvokeComplete' in event:
        print(f"\n\nComplete: {event['InvokeComplete']}")
```

### Viewing CloudWatch Logs

```bash
# Tail logs in real-time
aws logs tail /aws/lambda/streaming-demo --follow --region us-east-1

# View recent logs
aws logs tail /aws/lambda/streaming-demo --since 5m --region us-east-1
```

**Expected Log Output**:
```
[INFO] Lambda custom runtime starting...
[INFO] Runtime API: 127.0.0.1:9001
[INFO] Handler imported successfully
[INFO] Received invocation: abc-123-def
[INFO] Invoking handler for abc-123-def
[INFO] Sent chunk 1: 42 bytes
[INFO] Sent chunk 2: 42 bytes
[INFO] Stream complete: 2 chunks, 84 bytes
```

---

## Troubleshooting

### Common Issues

#### Issue 1: Runtime.ExitError - Exit Status 127

**Error**: `Runtime exited with error: exit status 127`

**Cause**: `bootstrap` file not executable

**Solution**:
```bash
chmod +x bootstrap
zip function.zip bootstrap runtime.py lambda_function.py
aws lambda update-function-code --function-name streaming-demo --zip-file fileb://function.zip
```

#### Issue 2: Python Not Found

**Error**: `/var/task/bootstrap: line X: /opt/bin/python3.11: No such file or directory`

**Cause**: Layer not attached to function

**Solution**:
```bash
aws lambda update-function-configuration \
  --function-name streaming-demo \
  --layers arn:aws:lambda:us-east-1:ACCOUNT_ID:layer:python311-al2023:VERSION
```

#### Issue 3: Cannot Execute Binary File (Exec Format Error)

**Error**: `cannot execute binary file: Exec format error`

**Cause**: Architecture mismatch (ARM64 layer on x86_64 function or vice versa)

**Solution**: Rebuild layer with correct architecture:
```bash
# For x86_64
docker run --rm --platform linux/amd64 ...

# For ARM64 (Graviton)
docker run --rm --platform linux/arm64 ...
```

#### Issue 4: ModuleNotFoundError: No module named 'binascii'

**Error**: Python can't find compiled modules

**Cause**: `PYTHONHOME` or `PYTHONPATH` not set correctly

**Solution**: Update bootstrap:
```bash
export PYTHONHOME=/opt
export LD_LIBRARY_PATH=/opt/lib:/var/lang/lib:$LD_LIBRARY_PATH
export PYTHONPATH=/opt/lib/python3.11:/opt/lib/python3.11/lib-dynload:$PYTHONPATH
```

#### Issue 5: Output Appears All At Once (Not Streaming)

**Error**: All chunks appear simultaneously instead of progressively

**Causes**:
1. Function URL not configured with `RESPONSE_STREAM` mode
2. Using Lambda console (doesn't support streaming visualization)
3. curl without `--no-buffer` flag

**Solution**:
```bash
# Verify Function URL mode
aws lambda get-function-url-config --function-name streaming-demo

# If wrong, update:
aws lambda create-function-url-config \
  --function-name streaming-demo \
  --invoke-mode RESPONSE_STREAM

# Test with curl properly:
curl --no-buffer ...
```

#### Issue 6: 400 Bad Request on Streaming

**Error**: Lambda returns 400 error

**Cause**: Incorrect chunked encoding format

**Check**:
- Chunk size in uppercase hex: `f"{size:X}"`
- CRLF after size: `\r\n`
- CRLF after data: `\r\n`
- Terminating chunk: `0\r\n\r\n`

---

## Performance Considerations

### Cold Start Time

**Components**:
- Runtime extraction: ~200-300 ms
- Python layer loading: ~100-200 ms
- Handler import: ~50-100 ms
- **Total**: ~400-600 ms

**Optimization**: Use provisioned concurrency for latency-sensitive applications.

### Memory Usage

- **Base runtime**: ~30-40 MB
- **Python layer**: ~20 MB extracted
- **Application code**: Varies
- **Recommended**: 128 MB minimum, 256 MB for production

### Streaming Performance

- **Latency**: Each chunk sent immediately (true streaming)
- **Throughput**: Limited by handler processing time
- **Memory**: Constant (generator pattern - no buffering)

---

## Best Practices

### 1. Error Handling

Always wrap handler invocation:
```python
try:
    result = lambda_handler(event, context)
    stream_response(runtime_api, request_id, result)
except Exception as e:
    send_error(runtime_api, request_id, e)
    # Continue loop - don't exit
```

### 2. Logging

Use structured logging:
```python
logger.info(f"Received invocation: {request_id}")
logger.info(f"Sent chunk {count}: {size} bytes")
logger.error(f"Error: {e}", exc_info=True)
```

### 3. Generator Best Practices

```python
def lambda_handler(event, context):
    # Always yield bytes
    yield data.encode('utf-8')  # ✅ Good

    # Don't yield strings
    # yield data  # ❌ Bad

    # Handle errors gracefully
    try:
        for item in process_data():
            yield item
    except Exception as e:
        # Log and re-raise
        logger.error(f"Processing error: {e}")
        raise
```

### 4. Testing Strategy

1. **Local**: Test handler in isolation with `main.py`
2. **Staging**: Deploy to test function, verify with curl
3. **Production**: Use boto3 integration tests
4. **Monitoring**: Set up CloudWatch alarms for errors

---

## References

- [AWS Lambda Response Streaming](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html)
- [Building Custom Runtimes](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-custom.html)
- [Lambda Runtime API](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-api.html)
- [Amazon Linux 2023](https://docs.aws.amazon.com/linux/al2023/ug/lambda.html)
- [HTTP/1.1 Chunked Transfer Encoding](https://datatracker.ietf.org/doc/html/rfc7230#section-4.1)

---

## Summary

This implementation demonstrates:

✅ Custom runtime on Amazon Linux 2023
✅ Python 3.11 bundled as Lambda Layer
✅ HTTP/1.1 chunked transfer encoding
✅ True streaming (not buffering)
✅ Full Runtime API compliance
✅ Production-ready error handling

The architecture is:
- **Modular**: Easy to swap handler logic
- **Scalable**: Standard Lambda scaling applies
- **Observable**: Full CloudWatch integration
- **Maintainable**: Clear separation of concerns
