"""Telemetry/log file index schemas (metadata only; no binary upload)."""

import json
import re
from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from app.models import FileType
from app.schemas.common import MAX_INT, Id, PageQuery, RequestModel, ResponseModel, text

MAX_METADATA_KEYS = 50
MAX_METADATA_BYTES = 8_192
MAX_METADATA_STRING = 500
METADATA_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

MetadataValue = str | int | float | bool | None


class TelemetryFileCreate(RequestModel):
    run_id: Id | None = Field(None, description="Optional; must belong to the same test.")
    file_type: FileType
    original_filename: text(255)
    storage_uri: text(1024) = Field(description="Location in externally managed storage.")
    checksum_sha256: Annotated[str, Field(min_length=64, max_length=64)]
    size_bytes: Annotated[int, Field(ge=0, le=MAX_INT * MAX_INT)]
    metadata: dict[str, MetadataValue] = Field(
        default_factory=dict,
        description=(
            "Flat, auxiliary, source-dependent metadata: snake_case keys, scalar values, "
            f"at most {MAX_METADATA_KEYS} keys and {MAX_METADATA_BYTES} bytes."
        ),
    )

    @field_validator("checksum_sha256", mode="before")
    @classmethod
    def _checksum(cls, value):
        if isinstance(value, str):
            value = value.strip().lower()
        if not isinstance(value, str) or not SHA256.match(value):
            raise ValueError("checksum_sha256 must be 64 hexadecimal characters")
        return value

    @field_validator("metadata")
    @classmethod
    def _metadata_shape(cls, metadata: dict) -> dict:
        if len(metadata) > MAX_METADATA_KEYS:
            raise ValueError(f"metadata may have at most {MAX_METADATA_KEYS} keys")
        for key, value in metadata.items():
            if not METADATA_KEY.match(key):
                raise ValueError(f"metadata key {key!r} must be snake_case (max 64 characters)")
            if isinstance(value, str) and len(value) > MAX_METADATA_STRING:
                raise ValueError(f"metadata value for {key!r} exceeds {MAX_METADATA_STRING} chars")
        try:
            encoded = json.dumps(metadata, allow_nan=False).encode()
        except ValueError:
            raise ValueError("metadata numbers must be finite (no NaN/Infinity)") from None
        if len(encoded) > MAX_METADATA_BYTES:
            raise ValueError(f"metadata exceeds {MAX_METADATA_BYTES} bytes")
        return metadata


class TelemetryFileListQuery(PageQuery):
    run_id: Id | None = None
    file_type: FileType | None = None


class TelemetryFileRead(ResponseModel):
    id: int
    test_id: int
    run_id: int | None
    file_type: FileType
    original_filename: str
    storage_uri: str
    checksum_sha256: str
    size_bytes: int
    metadata: dict[str, MetadataValue] = Field(validation_alias="file_metadata")
    imported_at: datetime
