# AWS Lambda Response Streaming - Custom Runtime on Amazon Linux 2023

A production-ready AWS Lambda function demonstrating response streaming using Python 3.11 on Amazon Linux 2023 (`provided.al2023`). The function implements HTTP/1.1 chunked transfer encoding to stream responses progressively.

## 🎯 Quick Start

### Local Testing (No AWS Required)

```bash
# Test the handler locally
python3 main.py
```

### Remote Testing with boto3

```bash
# Install dependencies
pip install boto3

# Run streaming test
python test_streaming.py
```

## 📚 Documentation

- **[IMPLEMENTATION.md](./IMPLEMENTATION.md)** - Complete implementation guide with architecture details, step-by-step instructions, and troubleshooting

## 🏗️ Architecture

```
AWS Lambda (provided.al2023)
  ↓
bootstrap → Configures Python environment
  ↓
Python 3.11 Layer (20 MB)
  ↓
runtime.py → Custom Runtime API client
  ├─ Polls for events
  ├─ Invokes handler generator
  └─ Streams via HTTP/1.1 chunked encoding
  ↓
lambda_function.py → Yields JSON chunks
  ↓
Progressive streaming response
```

## 📁 Project Structure

```
lambda_custom/
├── bootstrap              # Lambda entry point (executable shell script)
├── runtime.py            # Custom Runtime API client (~250 lines)
├── lambda_function.py    # Handler function (generator-based)
├── test_streaming.py     # boto3 test client
├── main.py               # Local testing script
├── IMPLEMENTATION.md     # Complete implementation guide
└── README.md            # This file
```

## 🚀 Key Features

✅ **Amazon Linux 2023** - Modern, optimized OS (< 40 MB vs 109 MB for AL2)
✅ **Python 3.11 Layer** - Custom layer with full stdlib support
✅ **True Streaming** - HTTP/1.1 chunked encoding (not buffering)
✅ **Generator Pattern** - Memory-efficient streaming using `yield`
✅ **Production-Ready** - Full error handling and logging

## 🧪 Testing

### Test with Function URL (curl)

```bash
curl -X POST https://YOUR-FUNCTION-URL/ \
  -H "Content-Type: application/json" \
  -d '{"sentence": "Test streaming on AL2023"}' \
  --no-buffer
```

**Expected Output** (progressive, not all at once):
```json
{"word": "Test", "index": 0, "total": 4}
{"word": "streaming", "index": 1, "total": 4}
{"word": "on", "index": 2, "total": 4}
{"word": "AL2023", "index": 3, "total": 4}
```

### Test with boto3

```python
import boto3
import json

client = boto3.client('lambda', region_name='us-east-1')

response = client.invoke_with_response_stream(
    FunctionName='streaming-demo',
    Payload=json.dumps({"sentence": "Hello world"})
)

for event in response['EventStream']:
    if 'PayloadChunk' in event:
        chunk = event['PayloadChunk']['Payload'].decode('utf-8')
        print(chunk, end='', flush=True)
```

## 🔧 Deployment

### Prerequisites

- AWS CLI configured
- Docker (for building Python layer)
- Lambda function: `streaming-demo` in `us-east-1`

### Quick Deploy

```bash
# 1. Create deployment package
chmod +x bootstrap
zip function.zip bootstrap runtime.py lambda_function.py

# 2. Deploy to Lambda
aws lambda update-function-code \
  --function-name streaming-demo \
  --zip-file fileb://function.zip \
  --region us-east-1

# 3. Update runtime to AL2023 with layer
aws lambda update-function-configuration \
  --function-name streaming-demo \
  --runtime provided.al2023 \
  --layers arn:aws:lambda:us-east-1:ACCOUNT_ID:layer:python311-al2023:VERSION \
  --region us-east-1
```

### Build Python 3.11 Layer

```bash
# Extract Python from AL2023 Docker image
mkdir -p python-layer

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

# Create layer zip
cd python-layer
zip -r ../python311-layer-x86.zip bin/ lib/
cd ..

# Publish layer to AWS
aws lambda publish-layer-version \
  --layer-name python311-al2023 \
  --description "Python 3.11 for AL2023 (x86_64)" \
  --compatible-runtimes provided.al2023 \
  --compatible-architectures x86_64 \
  --zip-file fileb://python311-layer-x86.zip \
  --region us-east-1
```

## 📊 Performance

- **Cold Start**: ~400-600 ms (runtime + layer loading)
- **Memory Usage**: ~30-40 MB (base runtime)
- **Streaming Latency**: Immediate (true streaming, no buffering)
- **Response Limit**: 20 MiB (streaming mode)

## 🐛 Troubleshooting

### Runtime.ExitError (Exit 127)

**Cause**: Bootstrap not executable
**Fix**: `chmod +x bootstrap` before zipping

### Python Not Found

**Cause**: Layer not attached
**Fix**: Verify layer ARN in function configuration

### Architecture Mismatch

**Cause**: ARM64 layer on x86_64 function (or vice versa)
**Fix**: Rebuild layer with `--platform linux/amd64` for x86_64

### No Streaming Effect

**Cause**: Function URL not in `RESPONSE_STREAM` mode
**Fix**:
```bash
aws lambda create-function-url-config \
  --function-name streaming-demo \
  --invoke-mode RESPONSE_STREAM
```

See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for complete troubleshooting guide.

## 📖 Event Parameters

```json
{
  "sentence": "Custom text to stream"
}
```

## 🔍 Monitoring

```bash
# View real-time logs
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

## 📚 Technical Details

### Custom Runtime Components

1. **bootstrap** (Shell Script)
   - Sets `PYTHONHOME`, `LD_LIBRARY_PATH`, `PYTHONPATH`
   - Launches `runtime.py` with Python from layer

2. **runtime.py** (Python Runtime API Client)
   - Polls Runtime API for invocations
   - Creates `LambdaContext` from headers
   - Invokes handler generator
   - Implements HTTP/1.1 chunked encoding
   - Handles errors gracefully

3. **lambda_function.py** (Handler)
   - Generator function using `yield`
   - Returns bytes (JSON-encoded)
   - Progressive streaming (no buffering)

### HTTP Chunked Encoding

```
1A\r\n
{"word":"Hello","index":0}\n\r\n
1B\r\n
{"word":"world","index":1}\n\r\n
0\r\n
\r\n
```

**Format**: `{size_hex}\r\n{data}\r\n` ... `0\r\n\r\n`

**Required Headers**:
- `Lambda-Runtime-Function-Response-Mode: streaming`
- `Transfer-Encoding: chunked`

## 🔗 References

- [AWS Lambda Response Streaming](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html)
- [Building Custom Runtimes](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-custom.html)
- [Lambda Runtime API](https://docs.aws.amazon.com/lambda/latest/dg/runtimes-api.html)
- [Amazon Linux 2023](https://docs.aws.amazon.com/linux/al2023/ug/lambda.html)

## 📝 License

See project license for details.

## 🤝 Contributing

See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for development guidelines.
