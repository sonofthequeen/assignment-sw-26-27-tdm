from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Path, Request
from sqlalchemy.orm import Session

from app.schemas.common import MAX_ID


def get_session(request: Request) -> Iterator[Session]:
    """One session and one transaction per request.

    Services add/flush/query but never commit. The transaction commits when the
    path operation returns and rolls back on any exception, so multi-entity
    commands are atomic.
    """
    with request.app.state.session_factory.begin() as session:
        yield session


# scope="function": commit/rollback finishes *before* the response is sent, so a
# failing commit becomes an error response instead of a silently lost 2xx.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]

IdPath = Annotated[int, Path(gt=0, le=MAX_ID)]
