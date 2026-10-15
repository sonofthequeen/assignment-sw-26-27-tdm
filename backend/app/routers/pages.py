from pydantic import BaseModel

from app.schemas.common import Page
from app.services.pagination import PageResult


def page_of[S: BaseModel](result: PageResult, schema: type[S]) -> Page[S]:
    """Converts ORM rows while the request session is still open."""
    return Page[schema](
        items=[schema.model_validate(item) for item in result.items],
        limit=result.limit,
        offset=result.offset,
        total=result.total,
        order_by=result.order_by,
    )
