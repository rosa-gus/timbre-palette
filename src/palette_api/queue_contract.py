"""Versioned and strictly validated enrichment Queue messages."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrichmentMessage(_StrictModel):
    """Single current message: D1 is the source of truth for job data."""

    schema_version: Literal[2]
    job_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation: int = Field(ge=1)
    job_type: Literal["recording", "release"] = "recording"
    target_mbid: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    stage: Literal["identity", "source", "observe", "publish"] = "source"


class EnrichmentWorkUnitMessage(_StrictModel):
    """Compact message for a group of jobs stored in D1."""

    schema_version: Literal[3]
    work_unit_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation: int = Field(ge=1)


@dataclass(frozen=True, slots=True)
class ParsedEnrichmentMessage:
    schema_version: int
    generation: int
    job_key: str | None = None
    job_type: str = "recording"
    target_mbid: str | None = None
    stage: str = "source"
    work_unit_key: str | None = None


def parse_enrichment_message(body: object) -> ParsedEnrichmentMessage:
    """Parse the current schema or raise ``ValueError``."""

    if not isinstance(body, Mapping):
        raise ValueError("The enrichment message must be a JSON object.")
    version = body.get("schema_version")
    try:
        if version == 2:
            message = EnrichmentMessage.model_validate(body)
            if message.job_type == "release" and not message.target_mbid:
                raise ValueError("An album job requires target_mbid.")
            return ParsedEnrichmentMessage(
                schema_version=2,
                job_key=message.job_key,
                generation=message.generation,
                job_type=message.job_type,
                target_mbid=message.target_mbid,
                stage=message.stage,
            )
        if version == 3:
            message = EnrichmentWorkUnitMessage.model_validate(body)
            return ParsedEnrichmentMessage(
                schema_version=3,
                generation=message.generation,
                work_unit_key=message.work_unit_key,
            )
    except ValidationError as error:
        raise ValueError("Invalid enrichment message.") from error
    raise ValueError(f"Unsupported enrichment schema_version: {version!r}.")


def retry_delay_seconds(job_key: str, attempts: int) -> int:
    """Return exponential backoff with deterministic jitter for observability."""

    import hashlib

    normalized_attempts = max(1, attempts)
    exponential = min(3600.0, 30.0 * (2 ** min(normalized_attempts - 1, 7)))
    digest = hashlib.sha256(f"{job_key}:{normalized_attempts}".encode()).digest()
    jitter = 0.8 + (digest[0] / 255.0) * 0.4
    return max(1, min(3600, round(exponential * jitter)))
