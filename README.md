# Verda Python SDK

Python SDK for the [Verda Watermarking API](https://enterprise.verda.ai/api-docs).

Embed imperceptible watermarks into images, videos, and audio. Decode watermarks to trace content back to its source.

## Install

```bash
pip install verda-watermark
```

## Quick Start

```python
from verda import VerdaClient

client = VerdaClient(api_key="vk_...")

# Encode a watermark
result = client.encode(file="photo.jpg")
print(result.watermark_ref)  # Unique reference for this watermark
print(result.download_url)   # Download the watermarked file

# Encode from a URL
result = client.encode(url="https://cdn.example.com/video.mp4")

# Decode / verify a watermark
result = client.decode(file="suspect.jpg")
print(result.match)          # True if watermark found
print(result.provenance)     # Origin info (owner, timestamp, etc.)

# Check credits
balance = client.credits()
print(f"${balance.balance_dollars:.2f} remaining")
```

## Configuration

```python
client = VerdaClient(
    api_key="vk_...",                                    # or set VERDA_API_KEY env var
    base_url="https://api.verda.ai/api/v2/enterprise",   # default
    poll_interval=5,                                      # seconds between job polls
    poll_timeout=300,                                     # max seconds to wait
)
```

## Async Jobs

By default, `encode()` and `decode()` wait for the job to complete. For long-running jobs (video), use `wait=False`:

```python
# Start encode without waiting
job_id = client.encode("long_video.mp4", wait=False)

# Check status later
job = client.get_job(job_id)
print(job.status)  # QUEUED, PROCESSING, COMPLETED, or FAILED
```

## Job Management

```python
# List your recent jobs
job_list = client.list_jobs(page=1, limit=20)
for job in job_list.jobs:
    print(f"{job.job_id}: {job.job_type} - {job.status}")

# Delete server-side files for a completed job
client.delete_job_files(job_id)
```

## Watermark Registry (On-Prem)

For on-prem deployments where you run the codec yourself, use the registry to allocate watermark IDs centrally:

```python
# Register a watermark before encoding locally
reg = client.register_watermark(
    content_type="audio",
    file_hash="sha256_of_original_file",
    file_format="wav",
    duration_seconds=180.0,
)
uid = reg["uid"]               # Embed this value with your local codec
ref = reg["watermark_ref"]     # Store this for your records

# After decoding, look up the watermark
entry = client.lookup_watermark(uid=uid)
if entry:
    print(f"Registered by: {entry.client_id}")
    print(f"Content type: {entry.content_type}")
```

## Model Manifest (On-Prem)

```python
manifest = client.get_model_manifest()
print(f"Latest encode version: {manifest.latest_encode_version}")
for v in manifest.versions:
    print(f"  v{v.version} (default={v.is_default_encode})")
```

## On-Prem Mode

Point the client to your local server:

```python
client = VerdaClient(api_key="vk_...", on_prem="http://localhost:8001")

# File-based
result = client.encode(file="speech.wav")

# Tensor-based (requires numpy + soundfile)
result = client.encode_tensor(audio_16k=waveform, sample_rate=16000)
```

## Supported Formats

| Type | Formats |
|------|---------|
| Image | jpg, png, webp, bmp, gif, tiff, heic |
| Video | mp4, mov, avi, mkv, webm |
| Audio | mp3, wav, flac, aac, ogg, m4a |

## Pricing

New accounts receive a one-time free credit. See [enterprise.verda.ai/api-docs](https://enterprise.verda.ai/api-docs) for current pricing.

## Error Handling

```python
from verda import VerdaClient, VerdaError, InsufficientCreditsError

try:
    result = client.encode(file="photo.jpg")
except InsufficientCreditsError:
    print("Top up your credits at enterprise.verda.ai")
except VerdaError as e:
    print(f"Error: {e.message} (HTTP {e.status_code})")
```

## License

MIT
