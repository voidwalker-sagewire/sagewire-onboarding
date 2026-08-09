from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.crud import events as event_crud


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_flow(
    db: Session,
    flow_id: str,
    *,
    include_versions: bool = False,
    include_definition: bool = False,
) -> models.OnboardingFlow | None:
    """
    Retrieve a flow by its database UUID.

    include_versions loads the flow's versions.

    include_definition additionally loads every version's steps, fields,
    and requirement definitions.
    """

    statement = select(models.OnboardingFlow).where(
        models.OnboardingFlow.id == flow_id
    )

    if include_definition:
        statement = statement.options(
            selectinload(models.OnboardingFlow.versions)
            .selectinload(models.OnboardingFlowVersion.steps)
            .selectinload(models.OnboardingStep.fields),
            selectinload(models.OnboardingFlow.versions)
            .selectinload(models.OnboardingFlowVersion.requirements),
        )
    elif include_versions:
        statement = statement.options(
            selectinload(models.OnboardingFlow.versions)
        )

    return db.scalar(statement)


def get_flow_by_key(
    db: Session,
    flow_key: str,
    *,
    include_versions: bool = False,
    include_definition: bool = False,
) -> models.OnboardingFlow | None:
    """
    Retrieve a flow by its stable public flow key.
    """

    statement = select(models.OnboardingFlow).where(
        models.OnboardingFlow.flow_key == flow_key
    )

    if include_definition:
        statement = statement.options(
            selectinload(models.OnboardingFlow.versions)
            .selectinload(models.OnboardingFlowVersion.steps)
            .selectinload(models.OnboardingStep.fields),
            selectinload(models.OnboardingFlow.versions)
            .selectinload(models.OnboardingFlowVersion.requirements),
        )
    elif include_versions:
        statement = statement.options(
            selectinload(models.OnboardingFlow.versions)
        )

    return db.scalar(statement)


def resolve_flow(
    db: Session,
    flow_reference: str,
    *,
    include_versions: bool = False,
    include_definition: bool = False,
) -> models.OnboardingFlow | None:
    """
    Resolve either a flow UUID or a flow_key.
    """

    flow = get_flow(
        db,
        flow_reference,
        include_versions=include_versions,
        include_definition=include_definition,
    )

    if flow is not None:
        return flow
    return get_flow_by_key(
        db,
        flow_reference,
        include_versions=include_versions,
        include_definition=include_definition,
    )




def list_flows(
    db: Session,
    *,
    status: models.FlowStatus | None = None,
    subject_type: models.SubjectType | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[models.OnboardingFlow]:
    """
    List onboarding flows in stable creation order.
    """

    statement = select(models.OnboardingFlow)

    if status is not None:
        statement = statement.where(
            models.OnboardingFlow.status == status
        )

    if subject_type is not None:
        statement = statement.where(
            models.OnboardingFlow.versions.any(
                models.OnboardingFlowVersion.subject_type == subject_type
            )
        )

    if search:
        search_pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                models.OnboardingFlow.flow_key.ilike(search_pattern),
                models.OnboardingFlow.name.ilike(search_pattern),
                models.OnboardingFlow.description.ilike(search_pattern),
            )
        )

    statement = (
        statement.order_by(
            models.OnboardingFlow.created_at.asc(),
            models.OnboardingFlow.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    return db.scalars(statement).all()


def count_flows(
    db: Session,
    *,
    status: models.FlowStatus | None = None,
    subject_type: models.SubjectType | None = None,
    search: str | None = None,
) -> int:
    """
    Count onboarding flows using the same filters as list_flows().
    """

    statement = select(func.count(models.OnboardingFlow.id))

    if status is not None:
        statement = statement.where(
            models.OnboardingFlow.status == status
        )

    if subject_type is not None:
        statement = statement.where(
            models.OnboardingFlow.versions.any(
                models.OnboardingFlowVersion.subject_type == subject_type
            )
        )

    if search:
        search_pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                models.OnboardingFlow.flow_key.ilike(search_pattern),
                models.OnboardingFlow.name.ilike(search_pattern),
                models.OnboardingFlow.description.ilike(search_pattern),
            )
        )

    return int(db.scalar(statement) or 0)


def create_flow(
    db: Session,
    flow_in: schemas.OnboardingFlowCreate,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingFlow:
    """
    Create an onboarding flow.

    If initial_version is present, the first draft version and its complete
    definition are created in the same transaction.
    """

    existing = get_flow_by_key(
        db,
        flow_in.flow_key,
    )

    if existing is not None:
        raise ValueError(
            f"flow_key '{flow_in.flow_key}' already exists"
        )

    flow = models.OnboardingFlow(
        flow_key=flow_in.flow_key,
        name=flow_in.name,
        description=flow_in.description,
        status=models.FlowStatus.ACTIVE,
        metadata_json=flow_in.metadata_json,
    )

    db.add(flow)

    try:
        db.flush()

        event_crud.create_event(
            db,
            event_type=models.EventType.FLOW_CREATED,
            flow_id=flow.id,
            actor_id=actor_id,
            payload_json={
                "flow_key": flow.flow_key,
                "name": flow.name,
                "status": flow.status.value,
            },
            correlation_id=correlation_id,
            commit=False,
        )

        if flow_in.initial_version is not None:
            _create_version_records(
                db,
                flow=flow,
                version_in=flow_in.initial_version,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return get_flow(
        db,
        flow.id,
        include_definition=True,
    ) or flow


def update_flow(
    db: Session,
    flow: models.OnboardingFlow,
    flow_in: schemas.OnboardingFlowUpdate,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingFlow:
    """
    Update mutable flow-level metadata.

    Published flow-version definitions are not modified here.
    """

    changes = flow_in.model_dump(
        exclude_unset=True,
    )

    previous_values: dict[str, object] = {}

    for field_name, value in changes.items():
        previous_values[field_name] = getattr(
            flow,
            field_name,
        )
        setattr(
            flow,
            field_name,
            value,
        )

    try:
        db.flush()

        if changes:
            event_crud.create_event(
                db,
                event_type=models.EventType.SESSION_UPDATED,
                flow_id=flow.id,
                actor_id=actor_id,
                payload_json={
                    "resource_type": "flow",
                    "flow_key": flow.flow_key,
                    "changes": {
                        key: {
                            "from": _serialize_value(
                                previous_values[key]
                            ),
                            "to": _serialize_value(value),
                        }
                        for key, value in changes.items()
                    },
                },
                correlation_id=correlation_id,
                commit=False,
            )

        db.commit()
        db.refresh(flow)

    except Exception:
        db.rollback()
        raise

    return flow


def retire_flow(
    db: Session,
    flow: models.OnboardingFlow,
    *,
    actor_id: str | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingFlow:
    """
    Retire a flow so new onboarding sessions should no longer start from it.

    Existing sessions remain attached to their original flow version.
    """

    if flow.status == models.FlowStatus.RETIRED:
        return flow

    flow.status = models.FlowStatus.RETIRED

    try:
        db.flush()

        event_crud.create_event(
            db,
            event_type=models.EventType.FLOW_VERSION_RETIRED,
            flow_id=flow.id,
            actor_id=actor_id,
            payload_json={
                "resource_type": "flow",
                "flow_key": flow.flow_key,
                "reason": reason,
            },
            correlation_id=correlation_id,
            commit=False,
        )

        db.commit()
        db.refresh(flow)

    except Exception:
        db.rollback()
        raise

    return flow


def activate_flow(
    db: Session,
    flow: models.OnboardingFlow,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingFlow:
    """
    Return a retired flow to ACTIVE status.

    This does not automatically republish any retired versions.
    """

    if flow.status == models.FlowStatus.ACTIVE:
        return flow

    flow.status = models.FlowStatus.ACTIVE

    try:
        db.flush()

        event_crud.create_event(
            db,
            event_type=models.EventType.SESSION_UPDATED,
            flow_id=flow.id,
            actor_id=actor_id,
            payload_json={
                "resource_type": "flow",
                "flow_key": flow.flow_key,
                "status": flow.status.value,
            },
            correlation_id=correlation_id,
            commit=False,
        )

        db.commit()
        db.refresh(flow)

    except Exception:
        db.rollback()
        raise

    return flow


def get_flow_version(
    db: Session,
    version_id: str,
    *,
    include_definition: bool = False,
) -> models.OnboardingFlowVersion | None:
    """
    Retrieve a flow version by its database UUID.
    """

    statement = select(models.OnboardingFlowVersion).where(
        models.OnboardingFlowVersion.id == version_id
    )

    if include_definition:
        statement = statement.options(
            selectinload(models.OnboardingFlowVersion.steps)
            .selectinload(models.OnboardingStep.fields),
            selectinload(
                models.OnboardingFlowVersion.requirements
            ),
        )

    return db.scalar(statement)


def get_flow_version_by_number(
    db: Session,
    flow_id: str,
    version_number: int,
    *,
    include_definition: bool = False,
) -> models.OnboardingFlowVersion | None:
    """
    Retrieve one numbered version belonging to a flow.
    """

    statement = select(models.OnboardingFlowVersion).where(
        models.OnboardingFlowVersion.flow_id == flow_id,
        models.OnboardingFlowVersion.version_number
        == version_number,
    )

    if include_definition:
        statement = statement.options(
            selectinload(models.OnboardingFlowVersion.steps)
            .selectinload(models.OnboardingStep.fields),
            selectinload(
                models.OnboardingFlowVersion.requirements
            ),
        )

    return db.scalar(statement)


def get_latest_published_version(
    db: Session,
    flow_id: str,
    *,
    include_definition: bool = False,
) -> models.OnboardingFlowVersion | None:
    """
    Retrieve the highest numbered published version for a flow.
    """

    statement = (
        select(models.OnboardingFlowVersion)
        .where(
            models.OnboardingFlowVersion.flow_id == flow_id,
            models.OnboardingFlowVersion.status
            == models.FlowVersionStatus.PUBLISHED,
        )
        .order_by(
            models.OnboardingFlowVersion.version_number.desc()
        )
        .limit(1)
    )

    if include_definition:
        statement = statement.options(
            selectinload(models.OnboardingFlowVersion.steps)
            .selectinload(models.OnboardingStep.fields),
            selectinload(
                models.OnboardingFlowVersion.requirements
            ),
        )

    return db.scalar(statement)


def list_flow_versions(
    db: Session,
    flow_id: str,
    *,
    status: models.FlowVersionStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[models.OnboardingFlowVersion]:
    """
    List versions belonging to one onboarding flow.
    """

    statement = select(models.OnboardingFlowVersion).where(
        models.OnboardingFlowVersion.flow_id == flow_id
    )

    if status is not None:
        statement = statement.where(
            models.OnboardingFlowVersion.status == status
        )

    statement = (
        statement.order_by(
            models.OnboardingFlowVersion.version_number.asc()
        )
        .offset(offset)
        .limit(limit)
    )

    return db.scalars(statement).all()


def count_flow_versions(
    db: Session,
    flow_id: str,
    *,
    status: models.FlowVersionStatus | None = None,
) -> int:
    """
    Count versions belonging to one onboarding flow.
    """

    statement = select(
        func.count(models.OnboardingFlowVersion.id)
    ).where(
        models.OnboardingFlowVersion.flow_id == flow_id
    )

    if status is not None:
        statement = statement.where(
            models.OnboardingFlowVersion.status == status
        )

    return int(db.scalar(statement) or 0)


def next_version_number(
    db: Session,
    flow_id: str,
) -> int:
    """
    Determine the next available integer version number.
    """

    statement = select(
        func.max(
            models.OnboardingFlowVersion.version_number
        )
    ).where(
        models.OnboardingFlowVersion.flow_id == flow_id
    )

    current_max = db.scalar(statement)

    return int(current_max or 0) + 1


def create_flow_version(
    db: Session,
    flow: models.OnboardingFlow,
    version_in: schemas.OnboardingFlowVersionCreate,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingFlowVersion:
    """
    Create a complete draft flow version.

    Steps, fields, and requirement definitions are created atomically.
    """

    if flow.status == models.FlowStatus.RETIRED:
        raise ValueError(
            "cannot create a version for a retired flow"
        )

    try:
        version = _create_version_records(
            db,
            flow=flow,
            version_in=version_in,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

        db.commit()

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the requested version number, key, or position "
            "conflicts with an existing definition"
        ) from exc

    except Exception:
        db.rollback()
        raise

    return get_flow_version(
        db,
        version.id,
        include_definition=True,
    ) or version


def update_flow_version(
    db: Session,
    version: models.OnboardingFlowVersion,
    version_in: schemas.OnboardingFlowVersionUpdate,
) -> models.OnboardingFlowVersion:
    """
    Update a draft flow version's top-level metadata.

    Published and retired versions are immutable.
    """

    _require_draft_version(version)

    changes = version_in.model_dump(
        exclude_unset=True,
    )

    for field_name, value in changes.items():
        setattr(
            version,
            field_name,
            value,
        )

    try:
        db.commit()
        db.refresh(version)

    except Exception:
        db.rollback()
        raise

    return version


def publish_flow_version(
    db: Session,
    version: models.OnboardingFlowVersion,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingFlowVersion:
    """
    Publish a complete draft version.

    A published version becomes immutable and may be used to create new
    onboarding sessions.
    """

    if version.status == models.FlowVersionStatus.PUBLISHED:
        return version

    if version.status == models.FlowVersionStatus.RETIRED:
        raise ValueError(
            "a retired flow version cannot be published"
        )

    flow = get_flow(
        db,
        version.flow_id,
    )

    if flow is None:
        raise ValueError(
            "the parent flow no longer exists"
        )

    if flow.status == models.FlowStatus.RETIRED:
        raise ValueError(
            "cannot publish a version of a retired flow"
        )

    version_with_definition = get_flow_version(
        db,
        version.id,
        include_definition=True,
    )

    if version_with_definition is None:
        raise ValueError(
            "flow version not found"
        )

    _validate_publishable_definition(
        version_with_definition
    )

    version_with_definition.status = (
        models.FlowVersionStatus.PUBLISHED
    )
    version_with_definition.published_at = utc_now()
    version_with_definition.retired_at = None

    try:
        db.flush()

        event_crud.create_event(
            db,
            event_type=models.EventType.FLOW_VERSION_PUBLISHED,
            flow_id=version_with_definition.flow_id,
            flow_version_id=version_with_definition.id,
            actor_id=actor_id,
            payload_json={
                "version_number": (
                    version_with_definition.version_number
                ),
                "title": version_with_definition.title,
                "subject_type": (
                    version_with_definition.subject_type.value
                ),
                "step_count": len(
                    version_with_definition.steps
                ),
                "requirement_count": len(
                    version_with_definition.requirements
                ),
            },
            correlation_id=correlation_id,
            commit=False,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return get_flow_version(
        db,
        version_with_definition.id,
        include_definition=True,
    ) or version_with_definition


def retire_flow_version(
    db: Session,
    version: models.OnboardingFlowVersion,
    *,
    actor_id: str | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingFlowVersion:
    """
    Retire a flow version.

    Existing sessions remain attached to the retired version, but new
    sessions should not be created from it.
    """

    if version.status == models.FlowVersionStatus.RETIRED:
        return version

    version.status = models.FlowVersionStatus.RETIRED
    version.retired_at = utc_now()

    try:
        db.flush()

        event_crud.create_event(
            db,
            event_type=models.EventType.FLOW_VERSION_RETIRED,
            flow_id=version.flow_id,
            flow_version_id=version.id,
            actor_id=actor_id,
            payload_json={
                "version_number": version.version_number,
                "title": version.title,
                "reason": reason,
            },
            correlation_id=correlation_id,
            commit=False,
        )

        db.commit()
        db.refresh(version)

    except Exception:
        db.rollback()
        raise

    return version


def add_step(
    db: Session,
    version: models.OnboardingFlowVersion,
    step_in: schemas.OnboardingStepCreate,
) -> models.OnboardingStep:
    """
    Add one complete step to a draft version.
    """

    _require_draft_version(version)

    step = _build_step_record(
        version=version,
        step_in=step_in,
    )

    db.add(step)

    try:
        db.commit()
        db.refresh(step)

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the step key, step position, field key, "
            "or field position already exists"
        ) from exc

    return step


def update_step(
    db: Session,
    step: models.OnboardingStep,
    step_in: schemas.OnboardingStepUpdate,
) -> models.OnboardingStep:
    """
    Update a step belonging to a draft version.
    """

    version = get_flow_version(
        db,
        step.flow_version_id,
    )

    if version is None:
        raise ValueError(
            "the parent flow version no longer exists"
        )

    _require_draft_version(version)

    changes = step_in.model_dump(
        exclude_unset=True,
    )

    for field_name, value in changes.items():
        setattr(
            step,
            field_name,
            value,
        )

    try:
        db.commit()
        db.refresh(step)

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the requested step position conflicts "
            "with another step"
        ) from exc

    return step


def add_field(
    db: Session,
    version: models.OnboardingFlowVersion,
    step: models.OnboardingStep,
    field_in: schemas.OnboardingFieldCreate,
) -> models.OnboardingField:
    """
    Add one field to a step in a draft version.
    """

    _require_draft_version(version)

    if step.flow_version_id != version.id:
        raise ValueError(
            "the step does not belong to the supplied flow version"
        )

    field = _build_field_record(
        version=version,
        step=step,
        field_in=field_in,
    )

    db.add(field)

    try:
        db.commit()
        db.refresh(field)

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the field key or field position already exists"
        ) from exc

    return field


def update_field(
    db: Session,
    field: models.OnboardingField,
    field_in: schemas.OnboardingFieldUpdate,
) -> models.OnboardingField:
    """
    Update a field belonging to a draft flow version.
    """

    version = get_flow_version(
        db,
        field.flow_version_id,
    )

    if version is None:
        raise ValueError(
            "the parent flow version no longer exists"
        )

    _require_draft_version(version)

    changes = field_in.model_dump(
        exclude_unset=True,
    )

    for field_name, value in changes.items():
        setattr(
            field,
            field_name,
            _dump_nested_schema(value),
        )

    try:
        db.commit()
        db.refresh(field)

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the requested field position conflicts "
            "with another field"
        ) from exc

    return field


def add_requirement(
    db: Session,
    version: models.OnboardingFlowVersion,
    requirement_in: schemas.OnboardingRequirementCreate,
) -> models.OnboardingRequirement:
    """
    Add one requirement definition to a draft version.
    """

    _require_draft_version(version)

    requirement = _build_requirement_record(
        version=version,
        requirement_in=requirement_in,
    )

    db.add(requirement)

    try:
        db.commit()
        db.refresh(requirement)

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the requirement key or position already exists"
        ) from exc

    return requirement


def update_requirement(
    db: Session,
    requirement: models.OnboardingRequirement,
    requirement_in: schemas.OnboardingRequirementUpdate,
) -> models.OnboardingRequirement:
    """
    Update a requirement definition belonging to a draft version.
    """

    version = get_flow_version(
        db,
        requirement.flow_version_id,
    )

    if version is None:
        raise ValueError(
            "the parent flow version no longer exists"
        )

    _require_draft_version(version)

    changes = requirement_in.model_dump(
        exclude_unset=True,
    )

    for field_name, value in changes.items():
        setattr(
            requirement,
            field_name,
            _dump_nested_schema(value),
        )

    try:
        db.commit()
        db.refresh(requirement)

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the requested requirement position conflicts "
            "with another requirement"
        ) from exc

    return requirement


def _create_version_records(
    db: Session,
    *,
    flow: models.OnboardingFlow,
    version_in: schemas.OnboardingFlowVersionCreate,
    actor_id: str | None,
    correlation_id: str | None,
) -> models.OnboardingFlowVersion:
    """
    Internal transaction-aware version constructor.

    The caller owns the final commit.
    """

    version_number = (
        version_in.version_number
        if version_in.version_number is not None
        else next_version_number(db, flow.id)
    )

    existing = get_flow_version_by_number(
        db,
        flow.id,
        version_number,
    )

    if existing is not None:
        raise ValueError(
            f"version {version_number} already exists "
            f"for flow '{flow.flow_key}'"
        )

    version = models.OnboardingFlowVersion(
        flow_id=flow.id,
        version_number=version_number,
        status=models.FlowVersionStatus.DRAFT,
        title=version_in.title,
        description=version_in.description,
        subject_type=version_in.subject_type,
        metadata_json=version_in.metadata_json,
    )

    db.add(version)
    db.flush()

    for step_in in version_in.steps:
        step = _build_step_record(
            version=version,
            step_in=step_in,
        )
        db.add(step)

    for requirement_in in version_in.requirements:
        requirement = _build_requirement_record(
            version=version,
            requirement_in=requirement_in,
        )
        db.add(requirement)

    db.flush()

    event_crud.create_event(
        db,
        event_type=models.EventType.FLOW_VERSION_CREATED,
        flow_id=flow.id,
        flow_version_id=version.id,
        actor_id=actor_id,
        payload_json={
            "flow_key": flow.flow_key,
            "version_number": version.version_number,
            "title": version.title,
            "subject_type": version.subject_type.value,
            "status": version.status.value,
        },
        correlation_id=correlation_id,
        commit=False,
    )

    return version


def _build_step_record(
    *,
    version: models.OnboardingFlowVersion,
    step_in: schemas.OnboardingStepCreate,
) -> models.OnboardingStep:
    step = models.OnboardingStep(
        flow_version_id=version.id,
        step_key=step_in.step_key,
        title=step_in.title,
        description=step_in.description,
        position=step_in.position,
        optional=step_in.optional,
        visibility_json=_dump_nested_schema(
            step_in.visibility_json
        ),
        metadata_json=step_in.metadata_json,
    )

    for field_in in step_in.fields:
        _build_field_record(
            version=version,
            step=step,
            field_in=field_in,
        )

    return step


def _build_field_record(
    *,
    version: models.OnboardingFlowVersion,
    step: models.OnboardingStep,
    field_in: schemas.OnboardingFieldCreate,
) -> models.OnboardingField:
    return models.OnboardingField(
        flow_version_id=version.id,
        step=step,
        field_key=field_in.field_key,
        label=field_in.label,
        description=field_in.description,
        placeholder=field_in.placeholder,
        field_type=field_in.field_type,
        position=field_in.position,
        required=field_in.required,
        sensitive=field_in.sensitive,
        default_value_json=field_in.default_value_json,
        options_json=[
            option.model_dump(mode="json")
            for option in field_in.options_json
        ],
        validation_json=field_in.validation_json.model_dump(
            mode="json"
        ),
        visibility_json=_dump_nested_schema(
            field_in.visibility_json
        ),
        metadata_json=field_in.metadata_json,
    )


def _build_requirement_record(
    *,
    version: models.OnboardingFlowVersion,
    requirement_in: schemas.OnboardingRequirementCreate,
) -> models.OnboardingRequirement:
    return models.OnboardingRequirement(
        flow_version_id=version.id,
        requirement_key=requirement_in.requirement_key,
        name=requirement_in.name,
        description=requirement_in.description,
        position=requirement_in.position,
        required=requirement_in.required,
        source=requirement_in.source,
        provider_key=requirement_in.provider_key,
        configuration_json=(
            requirement_in.configuration_json
        ),
        visibility_json=_dump_nested_schema(
            requirement_in.visibility_json
        ),
        metadata_json=requirement_in.metadata_json,
    )


def _require_draft_version(
    version: models.OnboardingFlowVersion,
) -> None:
    if version.status != models.FlowVersionStatus.DRAFT:
        raise ValueError(
            "only draft flow versions may be modified"
        )


def _validate_publishable_definition(
    version: models.OnboardingFlowVersion,
) -> None:
    """
    Validate structural requirements before publishing.
    """

    if not version.steps:
        raise ValueError(
            "a flow version must contain at least one step "
            "before it can be published"
        )

    field_keys: set[str] = set()

    for step in version.steps:
        for field in step.fields:
            if field.field_key in field_keys:
                raise ValueError(
                    f"duplicate field key '{field.field_key}'"
                )

            field_keys.add(field.field_key)

            if (
                field.field_type
                in {
                    models.FieldType.SELECT,
                    models.FieldType.MULTISELECT,
                }
                and not field.options_json
            ):
                raise ValueError(
                    f"field '{field.field_key}' requires options"
                )

    for step in version.steps:
        _validate_visibility_references(
            visibility_json=step.visibility_json,
            valid_field_keys=field_keys,
            resource_name=f"step '{step.step_key}'",
        )

        for field in step.fields:
            _validate_visibility_references(
                visibility_json=field.visibility_json,
                valid_field_keys=field_keys,
                resource_name=f"field '{field.field_key}'",
            )

    for requirement in version.requirements:
        _validate_visibility_references(
            visibility_json=requirement.visibility_json,
            valid_field_keys=field_keys,
            resource_name=(
                f"requirement "
                f"'{requirement.requirement_key}'"
            ),
        )


def _validate_visibility_references(
    *,
    visibility_json: dict | None,
    valid_field_keys: set[str],
    resource_name: str,
) -> None:
    if not visibility_json:
        return

    conditions = visibility_json.get(
        "conditions",
        [],
    )

    for condition in conditions:
        field_key = condition.get("field_key")

        if field_key not in valid_field_keys:
            raise ValueError(
                f"{resource_name} references unknown "
                f"visibility field '{field_key}'"
            )


def _dump_nested_schema(value: object) -> object:
    if value is None:
        return None

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    if isinstance(value, list):
        return [
            _dump_nested_schema(item)
            for item in value
        ]

    if isinstance(value, dict):
        return {
            key: _dump_nested_schema(item)
            for key, item in value.items()
        }

    return value


def _serialize_value(value: object) -> object:
    if isinstance(value, models.FlowStatus):
        return value.value

    if isinstance(value, models.FlowVersionStatus):
        return value.value

    if isinstance(value, models.SubjectType):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    return value
