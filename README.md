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
print(result.verify_url)     # Verification link (verda.ai/XXXXXX)
print(result.download_url)   # Download the watermarked file

# Encode from a URL
result = client.encode(url="https://cdn.example.com/video.mp4")

# Decode / verify a watermark
result = client.decode(file="suspect.jpg")
print(result.match)          # True if watermark found
print(result.provenance)     # Origin info (owner, verify_url, etc.)

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

## AI Disclosure (SB 942 / SB 1000, EU AI Act Article 50)

Tell Verda what the AI did, and the watermark resolves to those facts. They are
shown on the content's verify page and in decode results, and signed into its
certificate.

```python
from verda import AiDisclosure, ContentDetails, ComplianceError

try:
    result = client.encode(
        file="render.png",
        ai_disclosure=AiDisclosure(
            ai_involvement="generated",      # "generated", "altered" or "none"
            system_name="Acme Imagine",
            system_version="3.2",
            # provider_name is filled in from your verified company,
            # generated_at defaults to the encode time
        ),
        details=ContentDetails(
            license="CC BY-NC 4.0",
            ai_training="not_allowed",
            actions=["created", "upscaled"],
            prompt="a lighthouse at dusk",   # private by default
            external_ref="campaign-0193",    # private by default
        ),
        compliance_profile="both",           # "us_ca", "eu_art50" or "both"
    )
except ComplianceError as e:
    print("Not encoded, nothing charged. Missing:", e.missing)
```

- **Provider name.** Always your company's legal name, filled in by Verda once
  it has verified your company from its incorporation details. It is read-only:
  results carry it as `result.ai_disclosure.provider_name`, and a request that
  sends one is refused (`PROVIDER_NAME_NOT_ACCEPTED`). Until your company is
  verified, `us_ca` and `both` are refused with `COMPANY_NOT_VERIFIED`; contact
  Verda to get verified.
- **Profiles.** `us_ca` needs a verified company, the AI system name and
  version, and whether the AI created or altered the content (plus
  `assistive_technology` from 1 Jan 2029). `eu_art50` needs `ai_involvement`.
  Without a profile nothing is enforced.
- **Public or private.** `prompt`, `prompt_hash`, `external_ref` and
  `editorial_owner` are private by default; everything else is public. Change
  that with `private_fields=[...]` / `public_fields=[...]`. Custom entries:
  `custom={"brand": {"value": "Autumn", "public": True}}`. Public values must not
  contain emails or phone numbers.
- **Proof of private details.** The certificate signs a salted hash of your
  private details. Keep `result.private_details_salt` with them: together they
  prove later exactly what you disclosed, and when.
- **Decode** returns the matched content's `ai_disclosure`, its public `details`
  and `detected_by`.

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
    if job.verify_url:
        print(f"  Verify: {job.verify_url}")

# Filter by source (jobs from SDK vs web playground)
api_jobs = client.list_jobs(source="api")
playground_jobs = client.list_jobs(source="playground")

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
