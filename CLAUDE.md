# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an AWS Lambda function demonstrating **response streaming** using a **Python custom runtime**. It streams text word-by-word using HTTP/1.1 chunked transfer encoding.

## Architecture

The streaming architecture consists of three layers:

1. **bootstrap** → Lambda entry point (executable shell script)
2. **runtime.py** → Custom Runtime API implementation with HTTP chunked encoding
3. **lambda_function.py** → Handler function (Python generator yielding bytes)

### Execution Flow

```
AWS Lambda Invoke
  ↓
bootstrap (shell)
  ↓
runtime.py polls Runtime API → Creates LambdaContext → Invokes handler()
  ↓
handler() yields chunks → runtime.py streams via HTTP chunked encoding
  ↓
Response streamed to client
```

### Key Technical Constraints

- **Custom Runtime**: Uses `provided.al2` runtime (not standard Python runtime)
- **Streaming Headers**: Must set `Lambda-Runtime-Function-Response-Mode: streaming` and `Transfer-Encoding: chunked`
- **Generator Pattern**: Handler MUST be a generator function (uses `yield`, not `return`)
- **Byte Encoding**: All chunks yielded must be bytes, not strings
- **HTTP Chunked Format**: `{size_hex}\r\n{data}\r\n` ... `0\r\n\r\n`

## Development Workflow

### Local Testing

```bash
# Test locally without AWS deployment
python3 main.py
```

Edit the `event` dictionary in `main.py` to test different sentences:
```python
event = {"sentence": "Your custom sentence here"}
```

### Creating Deployment Package

```bash
# Ensure bootstrap is executable
chmod +x bootstrap

# Create zip (all files must be in root directory)
zip -r function.zip bootstrap runtime.py lambda_function.py requirements.txt
```

**Critical**: The `bootstrap` file MUST have execute permissions before zipping.

### Deploying to Lambda

```bash
# Deploy new function
aws lambda create-function \
  --function-name streaming-demo \
  --runtime provided.al2 \
  --role arn:aws:iam::ACCOUNT_ID:role/lambda-streaming-role \
  --handler not.used.in.custom.runtime \
  --zip-file fileb://function.zip \
  --timeout 30 \
  --memory-size 128

# Update existing function
aws lambda update-function-code \
  --function-name streaming-demo \
  --zip-file fileb://function.zip
```

### Enable Streaming via Function URL

```bash
# Create Function URL with RESPONSE_STREAM mode
aws lambda create-function-url-config \
  --function-name streaming-demo \
  --auth-type NONE \
  --invoke-mode RESPONSE_STREAM
```

**Critical**: The `--invoke-mode RESPONSE_STREAM` flag is REQUIRED for streaming to work.

### Testing Deployed Function

```bash
# Test with curl (--no-buffer is critical for seeing streaming)
curl -X POST https://YOUR-FUNCTION-URL/ \
  -H "Content-Type: application/json" \
  -d '{"sentence": "Test streaming response"}' \
  --no-buffer
```

### Viewing Logs

```bash
# Tail CloudWatch logs
aws logs tail /aws/lambda/streaming-demo --follow
```

## Handler Function Contract

The `handler()` function in `lambda_function.py` MUST:
- Be a generator function (use `yield`)
- Accept `(event, context)` parameters
- Yield bytes (use `.encode('utf-8')`)
- Event format: `{"sentence": "text to stream"}`

```python
def handler(event, context):
    sentence = event.get('sentence', 'default text')
    for word in sentence.split():
        yield (word + ' ').encode('utf-8')
        time.sleep(0.5)
```

## Runtime API Implementation

The `runtime.py` handles:
- Polling `/2018-06-01/runtime/invocation/next` for events
- Creating `LambdaContext` from response headers
- Invoking the handler generator
- Streaming chunks via HTTP/1.1 chunked encoding to `/2018-06-01/runtime/invocation/{request_id}/response`
- Error reporting to `/2018-06-01/runtime/invocation/{request_id}/error`

**Do not modify** `runtime.py` unless changing streaming behavior.

## Common Issues

### Bootstrap Not Executable
**Symptom**: `Runtime.ExitError` in Lambda
**Fix**: Run `chmod +x bootstrap` before creating zip

### No Streaming Visible
**Symptom**: All output appears at once
**Fix**: Ensure Function URL has `RESPONSE_STREAM` invoke mode and use `--no-buffer` with curl

### Lambda Console Shows Buffered Response
**Note**: This is expected. Lambda console does NOT support streaming visualization. Always test with Function URL + curl.

## Event Format

```json
{
  "sentence": "Text to stream word by word"
}
```

The sentence is split on whitespace and each word is streamed with a 0.5 second delay.

## Reference Links

### AWS Documentation
- [AWS Lambda Response Streaming](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html) - Official guide on configuring response streaming
- [Building Custom Runtimes](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-custom.html) - Custom runtime overview
- [Custom Runtime Response Streaming](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-custom.html#runtimes-custom-response-streaming) - Streaming-specific requirements for custom runtimes
- [Lambda Runtime API](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-api.html) - Runtime API endpoints and specifications
