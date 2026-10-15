"""Telemetry/log file index. Registers metadata only; binaries stay in external storage.

Duplicate policy: checksum_sha256 is globally unique, so the same file content is
indexed once (409 file_checksum_taken), whichever test it is offered for.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import DomainValidationError
from app.models import Run, TelemetryFile, Test
from app.schemas.files import TelemetryFileCreate, TelemetryFileListQuery
from app.services.lookup import get_or_404, get_referenced
from app.services.pagination import Ordering, PageResult, paginate

FILE_ORDER = (
    Ordering("imported_at desc", TelemetryFile.imported_at.desc()),
    Ordering("id desc", TelemetryFile.id.desc()),
)


def register_file(session: Session, test_id: int, data: TelemetryFileCreate) -> TelemetryFile:
    get_or_404(session, Test, test_id, "test")
    if data.run_id is not None:
        run = get_referenced(session, Run, data.run_id, "run", "run_id")
        if run.test_id != test_id:
            raise DomainValidationError.for_field(
                "run_not_in_test", "run_id", f"Run {data.run_id} belongs to a different test."
            )
    values = data.model_dump(exclude={"metadata"})
    telemetry_file = TelemetryFile(test_id=test_id, file_metadata=data.metadata, **values)
    session.add(telemetry_file)
    session.flush()
    return telemetry_file


def list_files(session: Session, test_id: int, query: TelemetryFileListQuery) -> PageResult:
    get_or_404(session, Test, test_id, "test")
    statement = select(TelemetryFile).where(TelemetryFile.test_id == test_id)
    if query.run_id is not None:
        statement = statement.where(TelemetryFile.run_id == query.run_id)
    if query.file_type is not None:
        statement = statement.where(TelemetryFile.file_type == query.file_type)
    return paginate(session, statement, query, FILE_ORDER)


def get_file(session: Session, file_id: int) -> TelemetryFile:
    return get_or_404(session, TelemetryFile, file_id, "file")
