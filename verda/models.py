from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EncodeResult:
    job_id: str
    watermark_id: str
    download_url: str
    status: str
    watermark_ref: str = ""

    @classmethod
    def from_job(cls, job: dict) -> "EncodeResult":
        return cls(
            job_id=job.get("job_id", ""),
            watermark_id=job.get("watermark_id", ""),
            download_url=job.get("download_url", ""),
            status=job.get("status", ""),
            watermark_ref=job.get("watermark_ref", ""),
        )

    @classmethod
    def from_fast(cls, watermark_ref: str, watermark_id: str = "", output_path: str = "") -> "EncodeResult":
        return cls(
            job_id="",
            watermark_id=watermark_id,
            download_url=output_path,
            status="COMPLETED",
            watermark_ref=watermark_ref,
        )


@dataclass
class DecodeResult:
    job_id: str
    match: bool
    watermark_id: Optional[str]
    confidence: float
    status: str
    owner: Optional[str] = None
    timestamp: Optional[int] = None
    entry: Optional[dict] = None

    @classmethod
    def from_job(cls, job: dict) -> "DecodeResult":
        return cls(
            job_id=job.get("job_id", ""),
            match=job.get("match", False),
            watermark_id=job.get("watermark_id") or None,
            confidence=job.get("confidence", 0.0),
            status=job.get("status", ""),
        )

    @classmethod
    def from_fast(cls, data: dict) -> "DecodeResult":
        entry = data.get("entry") or {}
        return cls(
            job_id="",
            match=data.get("match", False),
            watermark_id=str(data.get("uid", "")) if data.get("uid") else None,
            confidence=data.get("confidence", 0.0),
            status="COMPLETED",
            owner=entry.get("client_id", entry.get("clientId")),
            timestamp=entry.get("created_at", entry.get("createdAt")),
            entry=entry if entry else None,
        )


@dataclass
class TensorResult:
    """Result from tensor-level encode (on-prem only)."""
    audio: object  # numpy array
    watermark_ref: str
    watermark_id: str
    sample_rate: int


@dataclass
class Job:
    job_id: str
    job_type: str
    status: str
    watermark_id: Optional[str]
    download_url: Optional[str]
    match: bool
    confidence: float
    error_message: Optional[str]
    created_at: int
    completed_at: Optional[int]

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        status_map = {0: "UNSPECIFIED", 1: "QUEUED", 2: "PROCESSING", 3: "COMPLETED", 4: "FAILED"}
        raw_status = d.get("status", 0)
        status = status_map.get(raw_status, str(raw_status)) if isinstance(raw_status, int) else raw_status
        return cls(
            job_id=d.get("job_id", ""),
            job_type=d.get("job_type", ""),
            status=status,
            watermark_id=d.get("watermark_id") or None,
            download_url=d.get("download_url") or None,
            match=d.get("match", False),
            confidence=d.get("confidence", 0.0),
            error_message=d.get("error_message") or None,
            created_at=d.get("created_at", 0),
            completed_at=d.get("completed_at") or None,
        )


@dataclass
class CreditBalance:
    balance_microdollars: int
    balance_dollars: float
    free_tier_reset_at: int

    @classmethod
    def from_dict(cls, d: dict) -> "CreditBalance":
        micros = d.get("balance_microdollars", d.get("balanceMicrodollars", 0))
        return cls(
            balance_microdollars=micros,
            balance_dollars=micros / 1_000_000,
            free_tier_reset_at=d.get("free_tier_reset_at", d.get("freeTierResetAt", 0)),
        )
