from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from app.models import ConditionsSource, TrackState, Weather
from app.schemas.common import LongText, RequestModel, ResponseModel

# Mirrors NUMERIC(4, 1). Plausibility ranges live in app.policies (service-checked).
TemperatureC = Annotated[Decimal, Field(max_digits=4, decimal_places=1)]


class RunConditionCreate(RequestModel):
    """Conditions for one run. Omitted values are stored as unavailable (NULL)."""

    ambient_temperature_c: TemperatureC | None = None
    asphalt_temperature_c: TemperatureC | None = None
    conditions_source: ConditionsSource | None = Field(
        None, description="Whether the temperatures were MEASURED or ESTIMATED."
    )
    weather: Weather | None = None
    track_state: TrackState | None = None
    notes: LongText | None = None

    @model_validator(mode="after")
    def _source_for_temperatures(self):
        has_temperature = (
            self.ambient_temperature_c is not None or self.asphalt_temperature_c is not None
        )
        if has_temperature and self.conditions_source is None:
            raise ValueError("conditions_source is required when a temperature is given")
        return self


class RunConditionRead(ResponseModel):
    run_id: int
    ambient_temperature_c: Decimal | None
    asphalt_temperature_c: Decimal | None
    conditions_source: ConditionsSource | None
    weather: Weather | None
    track_state: TrackState | None
    notes: str | None
