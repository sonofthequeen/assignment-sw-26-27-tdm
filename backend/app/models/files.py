"""Metadata-only index of telemetry and log files.

Binaries are never stored in the database: storage_uri points at externally
managed storage, and checksum_sha256 identifies the content (one index entry
per distinct file). `metadata` is the one JSON column in the schema: auxiliary,
source-dependent key/value data that is validated (flat, bounded) and never
used for core relational facts.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, str_enum, utc_now


class FileType(enum.StrEnum):
    TELEMETRY = "TELEMETRY"
    DATA_LOG = "DATA_LOG"
    VIDEO = "VIDEO"
    SETUP_SHEET = "SETUP_SHEET"
    OTHER = "OTHER"


class TelemetryFile(Base):
    __tablename__ = "telemetry_file"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("length(checksum_sha256) = 64", name="checksum_length"),
        # The test's file listing (newest first) is the main access path; a test's
        # files grow without bound over years of logging.
        Index(None, "test_id", "imported_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("test.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id"))
    file_type: Mapped[FileType] = mapped_column(str_enum(FileType, "file_type"))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_uri: Mapped[str] = mapped_column(String(1024))
    checksum_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Attribute renamed: "metadata" is reserved on declarative classes.
    file_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
