from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


AI_INVOLVEMENT = ("generated", "altered", "none")


@dataclass
class AiDisclosure:
    """What an AI provider discloses about a piece of content.

    These are the facts California SB 942 (as amended by SB 1000) and EU AI Act
    Article 50 ask the hidden disclosure to carry. Always public: the verify
    page and decode results show it, and the signed certificate covers it.

    Args:
        ai_involvement: "generated", "altered" or "none".
        system_name / system_version: the AI system that made or changed it.
        provider_name: the company running the AI system. Required by "us_ca".
        generated_at: Unix seconds the AI made it. Defaults to encode time.
        assistive_technology: designed primarily as assistive technology
            (required by California from 1 Jan 2029).
    """
    ai_involvement: str = ""
    system_name: str = ""
    system_version: str = ""
    provider_name: str = ""
    generated_at: int = 0
    assistive_technology: Optional[bool] = None

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in ("", 0, None)}
        if self.assistive_technology is not None:
            d["assistive_technology"] = self.assistive_technology
        return d

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["AiDisclosure"]:
        if not d:
            return None
        gen = d.get("generated_at", 0) or 0
        return cls(
            ai_involvement=d.get("ai_involvement", ""),
            system_name=d.get("system_name", ""),
            system_version=d.get("system_version", ""),
            provider_name=d.get("provider_name", ""),
            generated_at=int(gen),
            assistive_technology=d.get("assistive_technology"),
        )


@dataclass
class ContentDetails:
    """Optional extra details about the content, each public or private.

    prompt, prompt_hash, external_ref and editorial_owner are private by
    default; everything else is public. Use private_fields / public_fields to
    change that by field name. Custom entries go in ``custom`` as
    ``{"key": {"value": "...", "public": True}}``. Public values must not
    contain personal information (emails, phone numbers): they appear on the
    verify page.
    """
    depicts_real_person_or_event: Optional[bool] = None
    artistic_or_satirical: Optional[bool] = None
    human_reviewed: Optional[bool] = None
    editorial_owner: str = ""
    tools_used: List[Dict[str, str]] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    source_assets: List[str] = field(default_factory=list)
    copyright_holder: str = ""
    license: str = ""
    usage_terms: str = ""
    ai_training: str = ""
    prompt: str = ""
    prompt_hash: str = ""
    external_ref: str = ""
    language: str = ""
    region: str = ""
    contact_url: str = ""
    custom: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    private_fields: List[str] = field(default_factory=list)
    public_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in ("", None, [], {})}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["ContentDetails"]:
        if not d:
            return None
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _disclosure_body(ai_disclosure, details, compliance_profile) -> dict:
    """Shared request fields for encode and register."""
    body: dict = {}
    if ai_disclosure is not None:
        body["ai_disclosure"] = ai_disclosure.to_dict() if isinstance(ai_disclosure, AiDisclosure) else dict(ai_disclosure)
    if details is not None:
        body["details"] = details.to_dict() if isinstance(details, ContentDetails) else dict(details)
    if compliance_profile:
        body["compliance_profile"] = compliance_profile
    return body


@dataclass
class EncodeResult:
    job_id: str
    watermark_ref: str
    download_url: str
    status: str
    verify_url: Optional[str] = None
    provenance: Optional[Dict[str, str]] = None
    ai_disclosure: Optional[AiDisclosure] = None
    details: Optional[ContentDetails] = None
    # Opens the certificate's commitment to your private details. Keep it with
    # them: together they prove later exactly what you kept private.
    private_details_salt: Optional[str] = None

    @classmethod
    def from_job(cls, job: dict) -> "EncodeResult":
        prov = job.get("provenance") or {}
        return cls(
            job_id=job.get("job_id", ""),
            watermark_ref=job.get("watermark_ref", "") or prov.get("watermark_ref", ""),
            download_url=job.get("download_url", ""),
            status=job.get("status", ""),
            verify_url=job.get("verify_url") or prov.get("verify_url"),
            provenance=prov if prov else None,
            ai_disclosure=job.get("ai_disclosure"),
            details=job.get("details"),
            private_details_salt=prov.get("private_details_salt"),
        )

    @classmethod
    def from_fast(cls, watermark_ref: str, watermark_id: str = "", output_path: str = "") -> "EncodeResult":
        return cls(
            job_id="",
            watermark_ref=watermark_ref,
            download_url=output_path,
            status="COMPLETED",
        )


@dataclass
class DecodeResult:
    job_id: str
    match: bool
    confidence: float
    status: str
    watermark_ref: Optional[str] = None
    owner: Optional[str] = None
    timestamp: Optional[int] = None
    provenance: Optional[Dict[str, str]] = None
    ai_disclosure: Optional[AiDisclosure] = None
    details: Optional[ContentDetails] = None  # public details only
    detected_by: Optional[str] = None         # "watermark" today
    entry: Optional[dict] = None

    @classmethod
    def from_job(cls, job: dict) -> "DecodeResult":
        prov = job.get("provenance") or {}
        return cls(
            job_id=job.get("job_id", ""),
            match=job.get("match", False),
            confidence=job.get("confidence", 0.0),
            status=job.get("status", ""),
            # The API returns the reference inside provenance on cloud decodes.
            watermark_ref=job.get("watermark_ref") or prov.get("watermark_ref") or None,
            owner=prov.get("owner_id"),
            provenance=prov if prov else None,
            ai_disclosure=job.get("ai_disclosure"),
            details=job.get("details"),
            detected_by=job.get("detected_by") or None,
        )

    @classmethod
    def from_fast(cls, data: dict) -> "DecodeResult":
        entry = data.get("entry") or {}
        return cls(
            job_id="",
            match=data.get("match", False),
            confidence=data.get("confidence", 0.0),
            status="COMPLETED",
            watermark_ref=entry.get("watermark_ref", entry.get("watermarkRef")),
            owner=entry.get("client_id", entry.get("clientId")),
            timestamp=entry.get("created_at", entry.get("createdAt")),
            entry=entry if entry else None,
        )


@dataclass
class TensorResult:
    """Result from tensor-level encode (on-prem only)."""
    audio: object  # numpy array
    watermark_ref: str
    sample_rate: int


@dataclass
class Job:
    job_id: str
    job_type: str
    status: str
    watermark_ref: Optional[str]
    download_url: Optional[str]
    match: bool
    confidence: float
    error_message: Optional[str]
    created_at: int
    completed_at: Optional[int]
    provenance: Optional[Dict[str, str]] = None
    files_deleted: bool = False
    content_type: Optional[str] = None
    file_format: Optional[str] = None
    source: Optional[str] = None
    verify_url: Optional[str] = None
    ai_disclosure: Optional[AiDisclosure] = None
    details: Optional[ContentDetails] = None
    detected_by: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        status_map = {0: "UNSPECIFIED", 1: "QUEUED", 2: "PROCESSING", 3: "COMPLETED", 4: "FAILED"}
        raw_status = d.get("status", 0)
        status = status_map.get(raw_status, str(raw_status)) if isinstance(raw_status, int) else raw_status
        prov = d.get("provenance") or {}
        files_deleted = prov.pop("files_deleted", None) == "true" if prov else False
        verify_url = prov.pop("verify_url", None)
        return cls(
            job_id=d.get("job_id", d.get("jobId", "")),
            job_type=d.get("job_type", d.get("jobType", "")),
            status=status,
            watermark_ref=d.get("watermark_ref", d.get("watermarkRef", d.get("watermark_id", d.get("watermarkId")))) or None,
            download_url=d.get("download_url", d.get("downloadUrl")) or None,
            match=d.get("match", False),
            confidence=d.get("confidence", 0.0),
            error_message=d.get("error_message", d.get("errorMessage")) or None,
            created_at=d.get("created_at", d.get("createdAt", 0)),
            completed_at=d.get("completed_at", d.get("completedAt")) or None,
            provenance=prov if prov else None,
            files_deleted=files_deleted,
            content_type=d.get("content_type", d.get("contentType")) or None,
            file_format=d.get("file_format", d.get("fileFormat")) or None,
            source=d.get("source") or None,
            verify_url=verify_url,
            ai_disclosure=AiDisclosure.from_dict(d.get("ai_disclosure", d.get("aiDisclosure"))),
            details=ContentDetails.from_dict(d.get("details")),
            detected_by=d.get("detected_by", d.get("detectedBy")) or None,
        )


@dataclass
class CreditBalance:
    balance_microdollars: int
    balance_dollars: float

    @classmethod
    def from_dict(cls, d: dict) -> "CreditBalance":
        micros = d.get("balance_microdollars", d.get("balanceMicrodollars", 0))
        if isinstance(micros, str):
            micros = int(micros)
        return cls(
            balance_microdollars=micros,
            balance_dollars=micros / 1_000_000,
        )


@dataclass
class WatermarkRegistryEntry:
    """A registered watermark in the Verda registry."""
    uid: int
    watermark_ref: str
    client_id: str
    created_at: int
    content_type: str
    duration_seconds: float = 0.0
    model_version: int = 0
    file_hash: str = ""
    integration_type: str = ""
    file_format: str = ""
    metadata: str = ""
    status: str = "ACTIVE"

    @classmethod
    def from_dict(cls, d: dict) -> "WatermarkRegistryEntry":
        uid = d.get("uid", 0)
        if isinstance(uid, str):
            uid = int(uid)
        created = d.get("created_at", d.get("createdAt", 0))
        if isinstance(created, str):
            created = int(created) if created else 0
        return cls(
            uid=uid,
            watermark_ref=d.get("watermark_ref", d.get("watermarkRef", "")),
            client_id=d.get("client_id", d.get("clientId", "")),
            created_at=created,
            content_type=d.get("content_type", d.get("contentType", "")),
            duration_seconds=d.get("duration_seconds", d.get("durationSeconds", 0.0)),
            model_version=d.get("model_version", d.get("modelVersion", 0)),
            file_hash=d.get("file_hash", d.get("fileHash", "")),
            integration_type=d.get("integration_type", d.get("integrationType", "")),
            file_format=d.get("file_format", d.get("fileFormat", "")),
            metadata=d.get("metadata", ""),
            status=d.get("status", "ACTIVE"),
        )


@dataclass
class ModelVersionInfo:
    version: int
    ecc_type: str = ""
    ecc_n: int = 0
    ecc_t: int = 0
    is_default_encode: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "ModelVersionInfo":
        return cls(
            version=d.get("version", 0),
            ecc_type=d.get("ecc_type", d.get("eccType", "")),
            ecc_n=d.get("ecc_n", d.get("eccN", 0)),
            ecc_t=d.get("ecc_t", d.get("eccT", 0)),
            is_default_encode=d.get("is_default_encode", d.get("isDefaultEncode", False)),
        )


@dataclass
class ModelManifest:
    """Model manifest for on-prem deployments."""
    versions: List[ModelVersionInfo] = field(default_factory=list)
    latest_encode_version: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "ModelManifest":
        versions_raw = d.get("versions", [])
        versions = [ModelVersionInfo.from_dict(v) for v in versions_raw] if versions_raw else []
        return cls(
            versions=versions,
            latest_encode_version=d.get("latest_encode_version", d.get("latestEncodeVersion", 0)),
        )


@dataclass
class JobList:
    """Paginated list of jobs."""
    jobs: List[Job]
    total: int
    page: int
    limit: int

    @classmethod
    def from_dict(cls, d: dict) -> "JobList":
        jobs_raw = d.get("jobs", [])
        return cls(
            jobs=[Job.from_dict(j) for j in jobs_raw],
            total=d.get("total", 0),
            page=d.get("page", 1),
            limit=d.get("limit", 20),
        )
