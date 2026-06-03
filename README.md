# Verda Python SDK

Python SDK for the [Verda Enterprise Watermarking API](https://enterprise.verda.ai/api-docs).

Embed imperceptible watermarks into images, videos, and audio. Decode watermarks to trace content back to its source.

## Install

```bash
pip install verda-watermark
```

## Quick Start

```python
from verda import VerdaClient

client = VerdaClient(api_key="vk_...")

# Encode a watermark into a local file
result = client.encode("photo.jpg")
print(result.watermark_id)   # 40-bit watermark identifier
print(result.download_url)   # Download the watermarked file

# Encode from a URL
result = client.encode(url="https://cdn.example.com/video.mp4")

# Decode / verify a watermark
result = client.decode("suspect.jpg")
print(result.match)          # True if watermark found
print(result.watermark_id)   # Original watermark ID

# Check credits
credits = client.credits()
print(f"${credits.balance_dollars:.2f} remaining")
```

## Configuration

```python
client = VerdaClient(
    api_key="vk_...",                                    # or set VERDA_API_KEY env var
    base_url="https://api.verda.ai/api/v2/enterprise",   # default
    poll_interval=5,                                      # seconds between job polls
    poll_timeout=300,                                     # max seconds to wait for a job
)
```

## Async Jobs

By default, `encode()` and `decode()` wait for the job to complete. For long-running jobs (video), you can use `wait=False`:

```python
# Start encode without waiting
job_id = client.encode("long_video.mp4", wait=False)

# Check status later
job = client.get_job(job_id)
print(job.status)  # QUEUED, PROCESSING, COMPLETED, or FAILED

# Or poll manually
import time
while True:
    job = client.get_job(job_id)
    if job.status in ("COMPLETED", "FAILED"):
        break
    time.sleep(10)
```

## Supported Formats

| Type | Formats |
|------|---------|
| Image | jpg, png, webp, bmp, gif, tiff, heic |
| Video | mp4, mov, avi, mkv, webm |
| Audio | mp3, wav, flac, aac, ogg, m4a |

## Pricing

| Operation | Price | Free Tier |
|-----------|-------|-----------|
| Image encode | $0.005/file | 100/month |
| Audio encode | $0.01/minute | 10 min/month |
| Video encode | $0.10/minute | 10 min/month |
| Image decode | $0.001/file | 1,000/month |
| Audio decode | $0.001/minute | 1,000/month |
| Video decode | $0.001/minute | 1,000/month |

## License

MIT
