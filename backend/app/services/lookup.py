from sqlalchemy.orm import Session

from app.exceptions import NotFoundError, missing_reference


def get_or_404[ModelT](
    session: Session, model: type[ModelT], resource_id: int, resource: str
) -> ModelT:
    """Fetch the resource addressed by the request path."""
    instance = session.get(model, resource_id)
    if instance is None:
        raise NotFoundError(resource, resource_id)
    return instance


def get_referenced[ModelT](
    session: Session, model: type[ModelT], resource_id: int, resource: str, field_name: str
) -> ModelT:
    """Fetch a row referenced by a request-body field (422 if missing).

    Checked explicitly because SQLite foreign-key errors do not say which
    reference failed; the FK constraint remains the final integrity boundary.
    """
    instance = session.get(model, resource_id)
    if instance is None:
        raise missing_reference(resource, field_name, resource_id)
    return instance
