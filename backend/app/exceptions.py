"""Domain errors raised by services and translated to HTTP responses in app.errors."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ErrorDetail:
    field: str | None
    issue: str


@dataclass
class DomainError(Exception):
    code: str
    message: str
    details: list[ErrorDetail] = field(default_factory=list)

    status_code = 400

    def __str__(self) -> str:
        return self.message


class NotFoundError(DomainError):
    """The resource addressed by the request path does not exist (404)."""

    status_code = 404

    def __init__(self, resource: str, resource_id: int):
        super().__init__(
            code=f"{resource}_not_found",
            message=f"{resource.replace('_', ' ').capitalize()} {resource_id} was not found.",
        )


class ConflictError(DomainError):
    """The request is valid but conflicts with existing state (409)."""

    status_code = 409


class DomainValidationError(DomainError):
    """The request is well-formed but violates a domain rule (422)."""

    status_code = 422

    @classmethod
    def for_field(cls, code: str, field_name: str, message: str) -> "DomainValidationError":
        return cls(code=code, message=message, details=[ErrorDetail(field_name, message)])


def missing_reference(resource: str, field_name: str, resource_id: int) -> DomainValidationError:
    """A body field references a row that does not exist (422, not 404: the path was valid)."""
    return DomainValidationError.for_field(
        "referenced_resource_not_found",
        field_name,
        f"{resource.replace('_', ' ').capitalize()} {resource_id} does not exist.",
    )
