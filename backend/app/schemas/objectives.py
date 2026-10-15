from pydantic import Field, computed_field, model_validator

from app.models import ObjectivePriority, ObjectiveStatus
from app.schemas.common import Id, LongText, PositiveCount, RequestModel, ResponseModel


class SeasonObjectiveCreate(RequestModel):
    description: LongText
    priority: ObjectivePriority
    desired_repetitions: PositiveCount
    status: ObjectiveStatus = ObjectiveStatus.OPEN
    notes: LongText | None = None


class SeasonObjectiveRead(ResponseModel):
    id: int
    season_id: int
    description: str
    priority: ObjectivePriority
    desired_repetitions: int
    status: ObjectiveStatus
    notes: str | None


class SeasonObjectiveDetail(SeasonObjectiveRead):
    """Progress is derived from links, never stored or synchronised by hand."""

    linked_test_count: int
    linked_run_count: int = Field(description="Actual runs linked to the objective.")

    @computed_field
    @property
    def remaining_repetitions(self) -> int:
        return max(self.desired_repetitions - self.linked_run_count, 0)


class ObjectiveLinkCreate(RequestModel):
    """Links are added together or not at all."""

    objective_ids: list[Id] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique(self):
        if len(self.objective_ids) != len(set(self.objective_ids)):
            raise ValueError("objective_ids must not repeat")
        return self
