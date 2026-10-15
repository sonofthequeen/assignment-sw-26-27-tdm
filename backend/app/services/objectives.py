"""Season objectives and their links to tests and runs.

Links are create-once (no unlink): removing a link would rewrite the history
of what a test or run was meant to address. Updates of objective status are
deferred.
"""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, DomainValidationError, ErrorDetail
from app.models import (
    ObjectivePriority,
    Run,
    RunObjective,
    Season,
    SeasonObjective,
    Test,
    TestObjective,
)
from app.schemas.common import PageQuery
from app.schemas.objectives import (
    ObjectiveLinkCreate,
    SeasonObjectiveCreate,
    SeasonObjectiveDetail,
    SeasonObjectiveRead,
)
from app.services.lookup import get_or_404
from app.services.pagination import Ordering, PageResult, paginate

PRIORITY_RANK = {priority: rank for rank, priority in enumerate(ObjectivePriority)}
OBJECTIVE_ORDER = (
    Ordering("priority (CRITICAL first)", case(PRIORITY_RANK, value=SeasonObjective.priority)),
    Ordering("id asc", SeasonObjective.id.asc()),
)


def create_objective(
    session: Session, season_id: int, data: SeasonObjectiveCreate
) -> SeasonObjective:
    get_or_404(session, Season, season_id, "season")
    objective = SeasonObjective(season_id=season_id, **data.model_dump())
    session.add(objective)
    session.flush()
    return objective


def list_objectives(session: Session, season_id: int, page: PageQuery) -> PageResult:
    get_or_404(session, Season, season_id, "season")
    statement = select(SeasonObjective).where(SeasonObjective.season_id == season_id)
    return paginate(session, statement, page, OBJECTIVE_ORDER)


def get_objective_detail(session: Session, objective_id: int) -> SeasonObjectiveDetail:
    objective = get_or_404(session, SeasonObjective, objective_id, "objective")
    tests = session.scalar(select(func.count()).where(TestObjective.objective_id == objective_id))
    runs = session.scalar(select(func.count()).where(RunObjective.objective_id == objective_id))
    return SeasonObjectiveDetail(
        **SeasonObjectiveRead.model_validate(objective).model_dump(),
        linked_test_count=tests,
        linked_run_count=runs,
    )


def _link(
    session: Session, season_id: int, data: ObjectiveLinkCreate, link_model, owner_field, owner_id
):
    objectives = {
        o.id: o
        for o in session.scalars(
            select(SeasonObjective).where(SeasonObjective.id.in_(data.objective_ids))
        )
    }
    for index, objective_id in enumerate(data.objective_ids):
        field = f"objective_ids.{index}"
        objective = objectives.get(objective_id)
        if objective is None:
            raise DomainValidationError.for_field(
                "referenced_resource_not_found", field, f"Objective {objective_id} does not exist."
            )
        if objective.season_id != season_id:
            raise DomainValidationError.for_field(
                "objective_season_mismatch",
                field,
                f"Objective {objective_id} belongs to another season.",
            )
    owner_column = getattr(link_model, owner_field)
    existing = set(
        session.scalars(
            select(link_model.objective_id).where(
                owner_column == owner_id, link_model.objective_id.in_(data.objective_ids)
            )
        )
    )
    if existing:
        raise ConflictError(
            code="objective_link_conflict",
            message="These objectives are already linked.",
            details=[
                ErrorDetail(f"objective_ids.{i}", f"Objective {oid} is already linked.")
                for i, oid in enumerate(data.objective_ids)
                if oid in existing
            ],
        )
    session.add_all(
        link_model(**{owner_field: owner_id, "objective_id": oid}) for oid in data.objective_ids
    )
    session.flush()


def _linked(session: Session, link_model, owner_field, owner_id) -> list[SeasonObjective]:
    return list(
        session.scalars(
            select(SeasonObjective)
            .join(link_model, link_model.objective_id == SeasonObjective.id)
            .where(getattr(link_model, owner_field) == owner_id)
            .order_by(*(o.clause for o in OBJECTIVE_ORDER))
        )
    )


def link_test_objectives(session: Session, test_id: int, data: ObjectiveLinkCreate) -> list:
    test = get_or_404(session, Test, test_id, "test")
    _link(session, test.season_id, data, TestObjective, "test_id", test_id)
    return _linked(session, TestObjective, "test_id", test_id)


def list_test_objectives(session: Session, test_id: int) -> list[SeasonObjective]:
    get_or_404(session, Test, test_id, "test")
    return _linked(session, TestObjective, "test_id", test_id)


def link_run_objectives(session: Session, run_id: int, data: ObjectiveLinkCreate) -> list:
    """A run may only address objectives of its parent test's season."""
    run = get_or_404(session, Run, run_id, "run")
    _link(session, run.test.season_id, data, RunObjective, "run_id", run_id)
    return _linked(session, RunObjective, "run_id", run_id)


def list_run_objectives(session: Session, run_id: int) -> list[SeasonObjective]:
    get_or_404(session, Run, run_id, "run")
    return _linked(session, RunObjective, "run_id", run_id)
