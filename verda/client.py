import os
import time
import mimetypes
from pathlib import Path
from typing import Optional, Union

import requests

from verda.models import (
    EncodeResult, DecodeResult, TensorResult, Job, JobList,
    CreditBalance, WatermarkRegistryEntry, ModelManifest,
)

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
    """Verda watermarking client.

    Usage:
        client = VerdaClient(api_key="vk_...")
        result = client.encode(file="speech.wav")

        # On-prem
        client = VerdaClient(api_key="vk_...", on_prem="http://localhost:8001")
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
            on_prem: On-prem server URL (e.g. "http://localhost:8001").
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
            "User-Agent": "verda-python/0.3.1",
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
        if self.on_prem:
            if not file:
                raise VerdaError("on_prem mode requires file= (URL not supported)")
            return self._encode_direct(file, content_type, file_format, metadata, output, self.on_prem)

        if not file and not url:
            raise VerdaError("Provide either file= or url=")

        # Cloud always uses async path (S3 upload + polling)
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
            DecodeResult with match, confidence, provenance.
        """
        if self.on_prem and file:
            return self._decode_direct(file, content_type, file_format, self.on_prem)

        # Cloud always uses async path (S3 upload + polling)
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

        buf = io.BytesIO()
        sf.write(buf, audio_16k, sample_rate, format="WAV")
        buf.seek(0)
        wav_bytes = buf.read()

        resp = self._session.post(
            f"{self.on_prem}/v1/encode",
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={"content_type": "audio", "metadata": metadata or ""},
            timeout=120,
        )
        self._check_response(resp)

        watermark_ref = resp.headers.get("X-Watermark-Ref", "")

        out_buf = io.BytesIO(resp.content)
        watermarked, out_sr = sf.read(out_buf, dtype="float32")

        return TensorResult(
            audio=watermarked,
            watermark_ref=watermark_ref,
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
            DecodeResult with match, confidence, provenance.
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
    # Public: Jobs
    # =========================================================================

    def get_job(self, job_id: str) -> Job:
        """Get the status of a watermark job."""
        resp = self._get(f"/watermark/jobs/{job_id}")
        job_data = resp.get("job", resp)
        return Job.from_dict(job_data)

    def list_jobs(self, page: int = 1, limit: int = 20) -> JobList:
        """List your watermark jobs (newest first).

        Args:
            page: Page number (1-indexed).
            limit: Results per page (max 50).

        Returns:
            JobList with jobs, total, page, limit.
        """
        resp = self._get("/watermark/jobs", params={"page": page, "limit": limit})
        return JobList.from_dict(resp)

    def delete_job_files(self, job_id: str) -> bool:
        """Delete the server-side files for a completed job.

        Args:
            job_id: The job ID to clean up.

        Returns:
            True if files were deleted.
        """
        resp = self._delete(f"/watermark/jobs/{job_id}/files")
        return resp.get("success", False)

    # =========================================================================
    # Public: Watermark Registry (on-prem integration)
    # =========================================================================

    def register_watermark(
        self,
        content_type: str,
        file_hash: str,
        file_format: str = "",
        duration_seconds: float = 0.0,
        model_version: int = 0,
        integration_type: str = "on-prem-assisted",
        sample_rate: int = 0,
        metadata: str = "",
    ) -> dict:
        """Register a watermark and receive a UID to embed.

        Use this for on-prem deployments where you run the codec yourself
        but need a centrally allocated watermark ID.

        Args:
            content_type: "image", "video", or "audio".
            file_hash: SHA-256 hash of the original file.
            file_format: File extension (e.g. "wav", "mp4", "png").
            duration_seconds: Media duration in seconds (0 for images).
            model_version: Codec model version used for encoding.
            integration_type: Deployment mode ("on-prem-assisted", "on-prem-offline", "managed-gpu").
            sample_rate: Audio/video sample rate.
            metadata: Freeform JSON string.

        Returns:
            dict with "uid" (int) and "watermark_ref" (str).
        """
        body = {
            "content_type": content_type,
            "file_hash": file_hash,
            "file_format": file_format,
            "duration_seconds": duration_seconds,
            "model_version": model_version,
            "integration_type": integration_type,
            "sample_rate": sample_rate,
            "metadata": metadata,
        }
        resp = self._post("/watermark/register", json=body)
        uid = resp.get("uid", 0)
        if isinstance(uid, str):
            uid = int(uid)
        return {
            "uid": uid,
            "watermark_ref": resp.get("watermark_ref", resp.get("watermarkRef", "")),
        }

    def lookup_watermark(self, uid: int) -> Optional[WatermarkRegistryEntry]:
        """Look up a watermark by its UID.

        Args:
            uid: The watermark UID (extracted by the decoder).

        Returns:
            WatermarkRegistryEntry if found, None otherwise.
        """
        resp = self._post("/watermark/lookup", json={"uid": uid})
        if not resp.get("found", False):
            return None
        entry_data = resp.get("entry", {})
        return WatermarkRegistryEntry.from_dict(entry_data)

    # =========================================================================
    # Public: Model Manifest (on-prem integration)
    # =========================================================================

    def get_model_manifest(self) -> ModelManifest:
        """Get the model manifest for on-prem deployments.

        Returns version info and configuration needed to run
        the watermarking codec locally.

        Returns:
            ModelManifest with version info.
        """
        resp = self._get("/models/manifest")
        manifest_data = resp.get("manifest", resp)
        return ModelManifest.from_dict(manifest_data)

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

        if output:
            out_path = output
        else:
            out_path = str(p.parent / f"{p.stem}_watermarked{p.suffix}")

        with open(out_path, "wb") as f:
            f.write(resp.content)

        return EncodeResult.from_fast(
            watermark_ref=watermark_ref,
            output_path=out_path,
        )

    def _decode_direct(
        self,
        file_path: str,
        content_type: Optional[str],
        file_format: Optional[str],
        server_url: str,
    ) -> DecodeResult:
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
    # Internal: Async path
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
    # Internal: Upload + Poll
    # =========================================================================

    def _upload_file(self, file_path: str) -> tuple:
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
