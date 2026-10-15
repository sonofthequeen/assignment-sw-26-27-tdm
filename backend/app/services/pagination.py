from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.schemas.common import PageQuery


@dataclass(frozen=True)
class Ordering:
    """An ORDER BY clause plus the label reported to API clients."""

    label: str
    clause: ColumnElement


@dataclass(frozen=True)
class PageResult:
    items: list[Any]
    total: int
    limit: int
    offset: int
    order_by: list[str]


def paginate(
    session: Session, statement: Select, page: PageQuery, ordering: Sequence[Ordering]
) -> PageResult:
    """Offset pagination; `ordering` must end with a unique key to be deterministic."""
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = session.scalars(
        statement.order_by(*(o.clause for o in ordering)).limit(page.limit).offset(page.offset)
    ).all()
    return PageResult(
        items=list(rows),
        total=total or 0,
        limit=page.limit,
        offset=page.offset,
        order_by=[o.label for o in ordering],
    )
