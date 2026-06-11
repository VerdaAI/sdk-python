import hashlib
import os
import time
import mimetypes
from pathlib import Path
from typing import Optional, Union

import requests

from verda.models import EncodeResult, DecodeResult, TensorResult, Job, CreditBalance

DEFAULT_BASE_URL = "https://api.verda.ai/api/v2/enterprise"
DEFAULT_TIMEOUT = 30
DEFAULT_POLL_INTERVAL = 5
DEFAULT_POLL_TIMEOUT = 300  # 5 minutes
FAST_PATH_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


class VerdaError(Exception):
    def __init__(self, message: str, status_code: int = 0, error_code: str = ""):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class InsufficientCreditsError(VerdaError):
    pass


class VerdaClient:
    """Verda watermarking client. Supports cloud API, managed GPU, and on-prem.

    Usage:
        # Cloud API (default)
        client = VerdaClient(api_key="vk_...")
        result = client.encode(file="speech.wav")

        # On-prem container
        client = VerdaClient(api_key="vk_...", on_prem="http://localhost:8001")
        result = client.encode(file="speech.wav")

        # Tensor-level (on-prem only)
        result = client.encode_tensor(audio_16k=waveform, sample_rate=16000)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        on_prem: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        poll_timeout: int = DEFAULT_POLL_TIMEOUT,
    ):
        """
        Args:
            api_key: Verda API key (vk_...). Or set VERDA_API_KEY env var.
            base_url: Cloud API URL (default: api.verda.ai).
            on_prem: On-prem comply server URL (e.g. "http://localhost:8001").
                     If set, encode/decode route to the local server instead of cloud.
            timeout: Request timeout in seconds.
            poll_interval: Seconds between job status polls (cloud async path).
            poll_timeout: Max seconds to wait for job completion (cloud async path).
        """
        self.api_key = api_key or os.environ.get("VERDA_API_KEY", "")
        if not self.api_key:
            raise VerdaError("API key required. Pass api_key= or set VERDA_API_KEY env var.")
        self.base_url = base_url.rstrip("/")
        self.on_prem = on_prem.rstrip("/") if on_prem else None
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

        self._session = requests.Session()
        self._session.headers.update({
            "X-API-Key": self.api_key,
            "User-Agent": "verda-python/0.2.0",
        })

    # =========================================================================
    # Public: Encode
    # =========================================================================

    def encode(
        self,
        file: Optional[str] = None,
        url: Optional[str] = None,
        content_type: Optional[str] = None,
        file_format: Optional[str] = None,
        metadata: Optional[str] = None,
        wait: bool = True,
        output: Optional[str] = None,
    ) -> Union[EncodeResult, str]:
        """Encode a watermark into media.

        Automatically picks the fastest path:
        - On-prem: routes to local comply server (if on_prem is set)
        - Fast cloud: sends bytes directly to comply server (files < 50 MB)
        - Async cloud: uploads to S3, polls job (files > 50 MB or URL input)

        Args:
            file: Path to a local file to watermark.
            url: Public URL of media to watermark (cloud async only).
            content_type: "image", "video", or "audio". Auto-detected if not provided.
            file_format: File extension. Auto-detected if not provided.
            metadata: Freeform JSON string to attach to the watermark registry record.
            wait: If True (default), wait for result. If False, return job_id (async only).
            output: Path to save watermarked file (fast/on-prem path). If None, auto-generates.

        Returns:
            EncodeResult with watermark_ref, download_url/output path, status.
        """
        # On-prem: always use direct path
        if self.on_prem:
            if not file:
                raise VerdaError("on_prem mode requires file= (URL not supported)")
            return self._encode_direct(file, content_type, file_format, metadata, output, self.on_prem)

        # Cloud: pick fast vs async based on file size
        if file:
            file_size = os.path.getsize(file)
            if file_size <= FAST_PATH_MAX_BYTES:
                return self._encode_direct(file, content_type, file_format, metadata, output, self.base_url)
            # Large file: fall through to async path
        elif not url:
            raise VerdaError("Provide either file= or url=")

        # Async cloud path (S3 + Temporal + polling)
        return self._encode_async(file, url, content_type, file_format, wait)

    # =========================================================================
    # Public: Decode
    # =========================================================================

    def decode(
        self,
        file: Optional[str] = None,
        url: Optional[str] = None,
        content_type: Optional[str] = None,
        file_format: Optional[str] = None,
        wait: bool = True,
    ) -> Union[DecodeResult, str]:
        """Decode / verify a watermark from media.

        Args:
            file: Path to a local file to check.
            url: Public URL of media to check (cloud only).
            content_type: "image", "video", or "audio". Auto-detected if not provided.
            file_format: File extension. Auto-detected if not provided.
            wait: If True (default), wait for result.

        Returns:
            DecodeResult with match, confidence, owner, timestamp.
        """
        # On-prem or fast path
        if self.on_prem and file:
            return self._decode_direct(file, content_type, file_format, self.on_prem)

        if file and os.path.getsize(file) <= FAST_PATH_MAX_BYTES:
            return self._decode_direct(file, content_type, file_format, self.base_url)

        # Async cloud path
        return self._decode_async(file, url, content_type, file_format, wait)

    # =========================================================================
    # Public: Tensor encode/decode (on-prem only)
    # =========================================================================

    def encode_tensor(
        self,
        audio_16k,  # numpy float32 array
        sample_rate: int = 16000,
        metadata: Optional[str] = None,
    ) -> TensorResult:
        """Encode watermark into raw audio tensor. On-prem only.

        Args:
            audio_16k: numpy float32 array, mono, at the given sample_rate.
            sample_rate: Sample rate of the input (default 16000).
            metadata: Optional metadata JSON string.

        Returns:
            TensorResult with watermarked audio array, watermark_ref, sample_rate.
        """
        if not self.on_prem:
            raise VerdaError("encode_tensor requires on_prem mode. Set on_prem= URL.")

        import numpy as np
        import io
        import soundfile as sf

        # Write tensor to WAV bytes for the comply server
        buf = io.BytesIO()
        sf.write(buf, audio_16k, sample_rate, format="WAV")
        buf.seek(0)
        wav_bytes = buf.read()

        # Send to comply server
        resp = self._session.post(
            f"{self.on_prem}/v1/encode",
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={"content_type": "audio", "metadata": metadata or ""},
            timeout=120,
        )
        self._check_response(resp)

        watermark_ref = resp.headers.get("X-Watermark-Ref", "")
        watermark_id = resp.headers.get("X-Watermark-UID", "")

        # Read watermarked audio back
        out_buf = io.BytesIO(resp.content)
        watermarked, out_sr = sf.read(out_buf, dtype="float32")

        return TensorResult(
            audio=watermarked,
            watermark_ref=watermark_ref,
            watermark_id=watermark_id,
            sample_rate=out_sr,
        )

    def decode_tensor(
        self,
        audio_16k,  # numpy float32 array
        sample_rate: int = 16000,
    ) -> DecodeResult:
        """Decode watermark from raw audio tensor. On-prem only.

        Args:
            audio_16k: numpy float32 array.
            sample_rate: Sample rate.

        Returns:
            DecodeResult with match, confidence, owner.
        """
        if not self.on_prem:
            raise VerdaError("decode_tensor requires on_prem mode.")

        import io
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio_16k, sample_rate, format="WAV")
        buf.seek(0)

        resp = self._session.post(
            f"{self.on_prem}/v1/decode",
            files={"file": ("audio.wav", buf.read(), "audio/wav")},
            data={"content_type": "audio"},
            timeout=120,
        )
        self._check_response(resp)

        return DecodeResult.from_fast(resp.json())

    # =========================================================================
    # Public: Credits
    # =========================================================================

    def credits(self) -> CreditBalance:
        """Check your credit balance."""
        resp = self._get("/credits")
        credit_data = resp.get("credits", resp)
        return CreditBalance.from_dict(credit_data)

    # =========================================================================
    # Public: Jobs (async path)
    # =========================================================================

    def get_job(self, job_id: str) -> Job:
        """Get the status of a watermark job."""
        resp = self._get(f"/watermark/jobs/{job_id}")
        job_data = resp.get("job", resp)
        return Job.from_dict(job_data)

    # =========================================================================
    # Internal: Direct path (fast cloud + on-prem)
    # =========================================================================

    def _encode_direct(
        self,
        file_path: str,
        content_type: Optional[str],
        file_format: Optional[str],
        metadata: Optional[str],
        output: Optional[str],
        server_url: str,
    ) -> EncodeResult:
        """Send file bytes to comply server, get watermarked bytes back."""
        p = Path(file_path)
        if not p.exists():
            raise VerdaError(f"File not found: {file_path}")

        fmt = file_format or p.suffix.lstrip(".").lower()
        ct = content_type or _guess_content_type(fmt)
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        resp = self._session.post(
            f"{server_url}/v1/encode",
            files={"file": (p.name, file_bytes, mime)},
            data={"content_type": ct, "metadata": metadata or ""},
            timeout=120,
        )
        self._check_response(resp)

        watermark_ref = resp.headers.get("X-Watermark-Ref", "")
        watermark_id = resp.headers.get("X-Watermark-UID", "")

        # Save output
        if output:
            out_path = output
        else:
            out_path = str(p.parent / f"{p.stem}_watermarked{p.suffix}")

        with open(out_path, "wb") as f:
            f.write(resp.content)

        return EncodeResult.from_fast(
            watermark_ref=watermark_ref,
            watermark_id=watermark_id,
            output_path=out_path,
        )

    def _decode_direct(
        self,
        file_path: str,
        content_type: Optional[str],
        file_format: Optional[str],
        server_url: str,
    ) -> DecodeResult:
        """Send file bytes to comply server for decode."""
        p = Path(file_path)
        if not p.exists():
            raise VerdaError(f"File not found: {file_path}")

        fmt = file_format or p.suffix.lstrip(".").lower()
        ct = content_type or _guess_content_type(fmt)
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        resp = self._session.post(
            f"{server_url}/v1/decode",
            files={"file": (p.name, file_bytes, mime)},
            data={"content_type": ct},
            timeout=120,
        )
        self._check_response(resp)

        return DecodeResult.from_fast(resp.json())

    # =========================================================================
    # Internal: Async path (S3 + Temporal + polling) — existing flow, unchanged
    # =========================================================================

    def _encode_async(self, file, url, content_type, file_format, wait):
        body = {}
        if file:
            content_id, fmt = self._upload_file(file)
            body["content_id"] = content_id
            body["file_format"] = file_format or fmt
            body["content_type"] = content_type or _guess_content_type(fmt)
        elif url:
            body["media_url"] = url
            if file_format:
                body["file_format"] = file_format
            else:
                body["file_format"] = _format_from_url(url)
            body["content_type"] = content_type or _guess_content_type(body["file_format"])
        else:
            raise VerdaError("Provide either file= or url=")

        resp = self._post("/watermark/encode", json=body)
        job_id = resp.get("job_id", resp.get("jobId", ""))

        if not wait:
            return job_id

        job = self._wait_for_job(job_id)
        if job.status == "FAILED":
            raise VerdaError(f"Encode failed: {job.error_message}", error_code="ENCODE_FAILED")

        return EncodeResult.from_job(job.__dict__)

    def _decode_async(self, file, url, content_type, file_format, wait):
        body = {}
        if file:
            content_id, fmt = self._upload_file(file)
            body["content_id"] = content_id
            body["file_format"] = file_format or fmt
            body["content_type"] = content_type or _guess_content_type(fmt)
        elif url:
            body["media_url"] = url
            if file_format:
                body["file_format"] = file_format
            else:
                body["file_format"] = _format_from_url(url)
            body["content_type"] = content_type or _guess_content_type(body["file_format"])
        else:
            raise VerdaError("Provide either file= or url=")

        resp = self._post("/watermark/decode", json=body)
        job_id = resp.get("job_id", resp.get("jobId", ""))

        if not wait:
            return job_id

        job = self._wait_for_job(job_id)
        if job.status == "FAILED":
            raise VerdaError(f"Decode failed: {job.error_message}", error_code="DECODE_FAILED")

        return DecodeResult.from_job(job.__dict__)

    # =========================================================================
    # Internal: Upload + Poll (shared by async paths)
    # =========================================================================

    def _upload_file(self, file_path: str) -> tuple:
        """Upload a local file to Verda S3 and return (content_id, file_format)."""
        p = Path(file_path)
        if not p.exists():
            raise VerdaError(f"File not found: {file_path}")

        file_format = p.suffix.lstrip(".").lower()
        content_type = _guess_content_type(file_format)

        resp = self._get("/watermark/upload-url", params={
            "filename": p.name,
            "content_type": content_type,
            "file_format": file_format,
        })

        upload_url = resp.get("upload_url", resp.get("uploadUrl", ""))
        content_id = resp.get("content_id", resp.get("contentId", ""))

        if not upload_url or not content_id:
            raise VerdaError("Failed to get upload URL")

        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            put_resp = requests.put(upload_url, data=f, headers={"Content-Type": mime_type}, timeout=120)
            if put_resp.status_code >= 400:
                raise VerdaError(f"Upload failed: HTTP {put_resp.status_code}")

        return content_id, file_format

    def _wait_for_job(self, job_id: str) -> Job:
        """Poll a job until it completes or fails."""
        deadline = time.time() + self.poll_timeout
        while time.time() < deadline:
            job = self.get_job(job_id)
            if job.status in ("COMPLETED", "FAILED"):
                return job
            time.sleep(self.poll_interval)
        raise VerdaError(f"Job {job_id} timed out after {self.poll_timeout}s")

    # =========================================================================
    # Internal: HTTP helpers
    # =========================================================================

    def _request(self, method: str, path: str, **kwargs) -> dict:
        kwargs.setdefault("timeout", self.timeout)
        resp = self._session.request(method, f"{self.base_url}{path}", **kwargs)
        self._check_response(resp)
        data = resp.json()
        return data.get("data", data)

    def _check_response(self, resp):
        if resp.status_code == 402:
            raise InsufficientCreditsError("Insufficient credits", status_code=402)
        if resp.status_code >= 400:
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass
            msg = body.get("message", body.get("error", body.get("detail", f"HTTP {resp.status_code}")))
            raise VerdaError(msg, status_code=resp.status_code, error_code=body.get("error_code", ""))

    def _get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> dict:
        return self._request("POST", path, **kwargs)

    def _delete(self, path: str, **kwargs) -> dict:
        return self._request("DELETE", path, **kwargs)


def _guess_content_type(file_format: str) -> str:
    fmt = file_format.lower().strip(".")
    if fmt in ("jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff", "heic", "avif"):
        return "image"
    elif fmt in ("mp4", "mov", "avi", "mkv", "webm", "ts", "m4v"):
        return "video"
    elif fmt in ("mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"):
        return "audio"
    return "image"


def _format_from_url(url: str) -> str:
    path = url.split("?")[0].split("#")[0]
    if "." in path:
        return path.rsplit(".", 1)[-1].lower()
    return "jpg"
