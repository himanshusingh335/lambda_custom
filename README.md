# AWS Lambda Response Streaming Function (Python Custom Runtime)

A simple AWS Lambda function demonstrating response streaming using Python with a custom runtime. The function streams a dummy sentence word-by-word using HTTP chunked transfer encoding.

## Files Overview

```
lambda_custom/
├── bootstrap              # Lambda runtime entry point (executable)
├── runtime.py            # Custom Runtime API client with streaming support
├── lambda_function.py    # Handler function that yields word chunks
├── main.py               # Local testing script (no AWS required)
├── requirements.txt      # Python dependencies (none required)
└── README.md            # This file
```

## How It Works

1. **bootstrap** - Lambda invokes this executable to start the custom runtime
2. **runtime.py** - Polls Lambda Runtime API for events, invokes handler, streams response using HTTP chunked encoding
3. **lambda_function.py** - Generator function that yields words from a sentence with configurable delays

## Local Testing (No AWS Required)

Before deploying to AWS, you can test the Lambda handler locally using `main.py`:

### Quick Start

```bash
# Default test (JSON format, 0.5s delay)
python3 main.py

# Fast streaming (0.1s delay)
python3 main.py --delay 0.1

# Plain text format
python3 main.py --format text

# Custom sentence
python3 main.py --sentence "The quick brown fox jumps over the lazy dog"

# Combination of options
python3 main.py --delay 1 --format json --sentence "Custom test message"

# View all options
python3 main.py --help
```

### Example Output

**JSON format**:
```json
{"status":"start","request_id":"local-test-1767009748","word_count":8}
{"type":"word","data":"Hello","sequence":1,"total":8,"timestamp":1767009748.27}
{"type":"word","data":"this","sequence":2,"total":8,"timestamp":1767009748.47}
...
{"status":"complete","word_count":8}
```

**Text format**:
```
Hello this is a streaming Lambda function response
```

### Available Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--delay` | float | 0.5 | Seconds between words |
| `--format` | string | json | Output format: "json" or "text" |
| `--sentence` | string | (built-in) | Custom sentence to stream |

---

## Deployment Instructions

### Step 1: Create Deployment Package

```bash
# Navigate to project directory
cd /Users/himanshusingh/Developer/lambda_custom

# Verify bootstrap is executable
ls -la bootstrap
# Should show: -rwx--x--x (executable permissions)

# Create deployment zip (all files must be in root, not subdirectory)
zip -r function.zip bootstrap runtime.py lambda_function.py requirements.txt

# Verify package contents
unzip -l function.zip
```

### Step 2: Create Lambda Function via AWS CLI

```bash
# Create execution role (if you don't have one)
aws iam create-role \
  --role-name lambda-streaming-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach basic execution policy
aws iam attach-role-policy \
  --role-name lambda-streaming-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Create Lambda function
aws lambda create-function \
  --function-name streaming-demo \
  --runtime provided.al2 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/lambda-streaming-role \
  --handler not.used.in.custom.runtime \
  --zip-file fileb://function.zip \
  --timeout 30 \
  --memory-size 128
```

### Step 3: Create Function URL with Response Streaming

```bash
# Create Function URL with RESPONSE_STREAM invoke mode
aws lambda create-function-url-config \
  --function-name streaming-demo \
  --auth-type NONE \
  --invoke-mode RESPONSE_STREAM

# Get the Function URL
aws lambda get-function-url-config \
  --function-name streaming-demo
```

**Important**: The Function URL will look like:
```
https://abc123xyz.lambda-url.us-east-1.on.aws/
```

### Alternative: Deploy via AWS Console

1. Go to AWS Lambda Console
2. Click **Create function**
3. Choose **Author from scratch**
4. Function name: `streaming-demo`
5. Runtime: **Custom runtime on Amazon Linux 2** (`provided.al2`)
6. Architecture: **x86_64**
7. Click **Create function**
8. Under **Code source**, click **Upload from** → **.zip file**
9. Upload `function.zip`
10. Under **Configuration** → **Function URL**:
    - Click **Create function URL**
    - Auth type: **NONE** (or AWS_IAM for production)
    - **Invoke mode**: **RESPONSE_STREAM** ⚠️ (Critical!)
    - Click **Save**

## Testing the Function

### Test with curl

```bash
# Basic test (JSON format with default 0.5s delay)
curl -X POST https://YOUR-FUNCTION-URL.lambda-url.REGION.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{}' \
  --no-buffer

# Custom delay (1 second between words)
curl -X POST https://YOUR-FUNCTION-URL.lambda-url.REGION.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{"delay": 1.0}' \
  --no-buffer

# Plain text format
curl -X POST https://YOUR-FUNCTION-URL.lambda-url.REGION.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{"format": "text"}' \
  --no-buffer

# Custom sentence
curl -X POST https://YOUR-FUNCTION-URL.lambda-url.REGION.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{"sentence": "The quick brown fox jumps over the lazy dog", "delay": 0.3}' \
  --no-buffer

# Verbose mode to see HTTP headers (including Transfer-Encoding: chunked)
curl -X POST https://YOUR-FUNCTION-URL.lambda-url.REGION.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{"delay": 0.5}' \
  --no-buffer \
  -v
```

**Important**: The `--no-buffer` flag is **critical** for seeing the streaming output in real-time.

### Expected Output (JSON format)

```json
{"status":"start","request_id":"abc-123-def","word_count":8,"timestamp":1735481234.56}
{"type":"word","data":"Hello","sequence":1,"total":8,"timestamp":1735481234.57}
{"type":"word","data":"this","sequence":2,"total":8,"timestamp":1735481235.07}
{"type":"word","data":"is","sequence":3,"total":8,"timestamp":1735481235.57}
{"type":"word","data":"a","sequence":4,"total":8,"timestamp":1735481236.07}
{"type":"word","data":"streaming","sequence":5,"total":8,"timestamp":1735481236.57}
{"type":"word","data":"Lambda","sequence":6,"total":8,"timestamp":1735481237.07}
{"type":"word","data":"function","sequence":7,"total":8,"timestamp":1735481237.57}
{"type":"word","data":"response","sequence":8,"total":8,"timestamp":1735481238.07}
{"status":"complete","word_count":8,"timestamp":1735481238.07}
```

Each line appears with the configured delay (default 0.5 seconds).

### Expected Output (text format)

```
Hello this is a streaming Lambda function response
```

Words appear progressively with delays between them.

## Event Parameters

The function accepts the following optional parameters in the event JSON:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `delay` | float | 0.5 | Seconds to wait between words |
| `format` | string | "json" | Output format: "json" or "text" |
| `sentence` | string | "Hello this is..." | Custom sentence to stream |

## Monitoring & Logs

View CloudWatch logs:

```bash
# Tail logs
aws logs tail /aws/lambda/streaming-demo --follow

# Get latest log events
aws logs tail /aws/lambda/streaming-demo --since 5m
```

Or via AWS Console:
1. Go to Lambda function
2. Click **Monitor** tab
3. Click **View logs in CloudWatch**

## Troubleshooting

### Issue: "Cannot test streaming in Lambda console"
**Solution**: Lambda console always shows buffered responses. Use Function URL with curl instead.

### Issue: No streaming effect visible
**Solution**: Ensure you're using `--no-buffer` flag with curl and Function URL has `RESPONSE_STREAM` invoke mode.

### Issue: Function timeout
**Solution**: Increase Lambda timeout in Configuration → General configuration → Timeout (e.g., 60 seconds).

### Issue: "Runtime.ExitError"
**Solution**:
- Verify bootstrap has execute permissions: `ls -la bootstrap` should show `rwx`
- Ensure bootstrap is in zip root, not subdirectory
- Check CloudWatch logs for Python errors

### Issue: HTTP 500 errors
**Solution**: Check CloudWatch logs for detailed error messages. Common causes:
- Missing `AWS_LAMBDA_RUNTIME_API` environment variable (Lambda sets this automatically)
- Python syntax errors in runtime.py or lambda_function.py

## Technical Details

### Custom Runtime Implementation

- **Runtime API**: Uses HTTP client to poll `/2018-06-01/runtime/invocation/next`
- **Streaming**: Implements HTTP/1.1 chunked transfer encoding
- **Headers**: Sets `Lambda-Runtime-Function-Response-Mode: streaming` and `Transfer-Encoding: chunked`
- **Chunk Format**: `{size_hex}\r\n{data}\r\n` ... `0\r\n\r\n` (terminator)

### Response Streaming Limits

- Maximum response size: **20 MiB** (for custom runtime streaming)
- Bandwidth: First 6 MB uncapped, then max 2 MBps
- Standard Lambda limits: 6 MB for buffered responses

### Python Generator Pattern

The handler function uses Python's generator pattern with `yield` to produce chunks:

```python
def handler(event, context):
    for word in sentence.split():
        yield json.dumps({"data": word}).encode('utf-8')
        time.sleep(delay)
```

## Updating the Function

```bash
# After making changes, re-zip and update
zip -r function.zip bootstrap runtime.py lambda_function.py requirements.txt

aws lambda update-function-code \
  --function-name streaming-demo \
  --zip-file fileb://function.zip
```

## Clean Up

```bash
# Delete Function URL
aws lambda delete-function-url-config --function-name streaming-demo

# Delete Lambda function
aws lambda delete-function --function-name streaming-demo

# Delete IAM role (if created)
aws iam detach-role-policy \
  --role-name lambda-streaming-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam delete-role --role-name lambda-streaming-role
```

## Next Steps

- Add authentication to Function URL (AWS_IAM auth type)
- Implement more complex streaming use cases (e.g., streaming large file processing)
- Integrate with API Gateway for additional features
- Add custom metrics and monitoring
- Implement response compression

## References

- [AWS Lambda Response Streaming](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html)
- [Building Custom Runtimes](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-custom.html)
- [Lambda Runtime API](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-api.html)
