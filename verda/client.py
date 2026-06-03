import os
import time
import mimetypes
from pathlib import Path
from typing import Optional, Union

import requests

from verda.models import EncodeResult, DecodeResult, Job, CreditBalance

DEFAULT_BASE_URL = "https://api.verda.ai/api/v2/enterprise"
DEFAULT_TIMEOUT = 30
DEFAULT_POLL_INTERVAL = 5
DEFAULT_POLL_TIMEOUT = 300  # 5 minutes


class VerdaError(Exception):
    def __init__(self, message: str, status_code: int = 0, error_code: str = ""):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class InsufficientCreditsError(VerdaError):
    pass


class VerdaClient:
    """Verda Enterprise API client for watermarking media.

    Usage:
        client = VerdaClient(api_key="vk_...")

        # Encode a local file (uploads + encodes + waits for result)
        result = client.encode("photo.jpg")
        print(result.watermark_id)
        print(result.download_url)

        # Encode from a URL
        result = client.encode(url="https://cdn.example.com/image.png")

        # Decode / verify
        result = client.decode("suspect.jpg")
        print(result.match)
        print(result.watermark_id)

        # Check credits
        credits = client.credits()
        print(f"${credits.balance_dollars:.4f} remaining")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        poll_timeout: int = DEFAULT_POLL_TIMEOUT,
    ):
        self.api_key = api_key or os.environ.get("VERDA_API_KEY", "")
        if not self.api_key:
            raise VerdaError("API key required. Pass api_key= or set VERDA_API_KEY env var.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._session = requests.Session()
        self._session.headers.update({
            "X-API-Key": self.api_key,
            "User-Agent": "verda-python/0.1.0",
        })

    def _request(self, method: str, path: str, **kwargs) -> dict:
        kwargs.setdefault("timeout", self.timeout)
        resp = self._session.request(method, f"{self.base_url}{path}", **kwargs)

        if resp.status_code == 402:
            raise InsufficientCreditsError("Insufficient credits", status_code=402)

        if resp.status_code >= 400:
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass
            msg = body.get("message", body.get("error", f"HTTP {resp.status_code}"))
            raise VerdaError(msg, status_code=resp.status_code, error_code=body.get("error_code", ""))

        data = resp.json()
        return data.get("data", data)

    def _get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> dict:
        return self._request("POST", path, **kwargs)

    def _delete(self, path: str, **kwargs) -> dict:
        return self._request("DELETE", path, **kwargs)

    # --- Upload ---

    def _upload_file(self, file_path: str) -> tuple[str, str]:
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

    # --- Jobs ---

    def get_job(self, job_id: str) -> Job:
        """Get the status of a watermark job."""
        resp = self._get(f"/watermark/jobs/{job_id}")
        job_data = resp.get("job", resp)
        return Job.from_dict(job_data)

    def _wait_for_job(self, job_id: str) -> Job:
        """Poll a job until it completes or fails."""
        deadline = time.time() + self.poll_timeout
        while time.time() < deadline:
            job = self.get_job(job_id)
            if job.status in ("COMPLETED", "FAILED"):
                return job
            time.sleep(self.poll_interval)
        raise VerdaError(f"Job {job_id} timed out after {self.poll_timeout}s")

    # --- Encode ---

    def encode(
        self,
        file: Optional[str] = None,
        url: Optional[str] = None,
        content_type: Optional[str] = None,
        file_format: Optional[str] = None,
        wait: bool = True,
    ) -> Union[EncodeResult, str]:
        """Encode a watermark into media.

        Args:
            file: Path to a local file to watermark.
            url: Public URL of media to watermark.
            content_type: "image", "video", or "audio". Auto-detected from file extension if not provided.
            file_format: File extension (e.g. "jpg", "mp4"). Auto-detected if not provided.
            wait: If True (default), poll until the job completes and return the result.
                  If False, return the job_id immediately.

        Returns:
            EncodeResult if wait=True, job_id string if wait=False.
        """
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

    # --- Decode ---

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
            url: Public URL of media to check.
            content_type: "image", "video", or "audio". Auto-detected if not provided.
            file_format: File extension. Auto-detected if not provided.
            wait: If True (default), poll until the job completes. If False, return job_id.

        Returns:
            DecodeResult if wait=True, job_id string if wait=False.
        """
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

    # --- Credits ---

    def credits(self) -> CreditBalance:
        """Check your credit balance."""
        resp = self._get("/credits")
        credit_data = resp.get("credits", resp)
        return CreditBalance.from_dict(credit_data)


def _guess_content_type(file_format: str) -> str:
    fmt = file_format.lower().strip(".")
    if fmt in ("jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff", "heic"):
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
