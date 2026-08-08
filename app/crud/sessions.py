from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.crud import events as event_crud
from app.crud import flows as flow_crud


TERMINAL_SESSION_STATUSES = {
    models.SessionStatus.COMPLETED,
    models.SessionStatus.ABANDONED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_session(
    db: Session,
    session_id: str,
    *,
    include_details: bool = False,
) -> models.OnboardingSession | None:
    """
    Retrieve an onboarding session by its database UUID.

    When include_details is True, load the session's flow definition,
    answers, requirement states, and requirement definitions.
    """

    statement = select(models.OnboardingSession).where(
        models.OnboardingSession.id == session_id
    )

    if include_details:
        statement = statement.options(
            selectinload(models.OnboardingSession.flow),
            selectinload(models.OnboardingSession.flow_version)
            .selectinload(models.OnboardingFlowVersion.steps)
            .selectinload(models.OnboardingStep.fields),
            selectinload(models.OnboardingSession.flow_version)
            .selectinload(models.OnboardingFlowVersion.requirements),
            selectinload(models.OnboardingSession.answers),
            selectinload(models.OnboardingSession.requirements)
            .selectinload(
                models.OnboardingSessionRequirement.requirement
            ),
        )

    return db.scalar(statement)


def get_session_by_key(
    db: Session,
    session_key: str,
    *,
    include_details: bool = False,
) -> models.OnboardingSession | None:
    """
    Retrieve an onboarding session by its stable public session key.
    """

    statement = select(models.OnboardingSession).where(
        models.OnboardingSession.session_key == session_key
    )

    if include_details:
        statement = statement.options(
            selectinload(models.OnboardingSession.flow),
            selectinload(models.OnboardingSession.flow_version)
            .selectinload(models.OnboardingFlowVersion.steps)
            .selectinload(models.OnboardingStep.fields),
            selectinload(models.OnboardingSession.flow_version)
            .selectinload(models.OnboardingFlowVersion.requirements),
            selectinload(models.OnboardingSession.answers),
            selectinload(models.OnboardingSession.requirements)
            .selectinload(
                models.OnboardingSessionRequirement.requirement
            ),
        )

    return db.scalar(statement)


def resolve_session(
    db: Session,
    session_reference: str,
    *,
    include_details: bool = False,
) -> models.OnboardingSession | None:
    """
    Resolve either a session UUID or a public session_key.
    """

    onboarding_session = get_session(
        db,
        session_reference,
        include_details=include_details,
    )

    if onboarding_session is not None:
        return onboarding_session

    return get_session_by_key(
        db,
        session_reference,
        include_details=include_details,
    )


def list_sessions(
    db: Session,
    *,
    flow_id: str | None = None,
    flow_version_id: str | None = None,
    subject_type: models.SubjectType | None = None,
    subject_id: str | None = None,
    status: models.SessionStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[models.OnboardingSession]:
    """
    List onboarding sessions using optional filters.

    Newest sessions are returned first.
    """

    statement = select(models.OnboardingSession)

    if flow_id is not None:
        statement = statement.where(
            models.OnboardingSession.flow_id == flow_id
        )

    if flow_version_id is not None:
        statement = statement.where(
            models.OnboardingSession.flow_version_id
            == flow_version_id
        )

    if subject_type is not None:
        statement = statement.where(
            models.OnboardingSession.subject_type
            == subject_type
        )

    if subject_id is not None:
        statement = statement.where(
            models.OnboardingSession.subject_id == subject_id
        )

    if status is not None:
        statement = statement.where(
            models.OnboardingSession.status == status
        )

    statement = (
        statement.order_by(
            models.OnboardingSession.created_at.desc(),
            models.OnboardingSession.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    return db.scalars(statement).all()


def count_sessions(
    db: Session,
    *,
    flow_id: str | None = None,
    flow_version_id: str | None = None,
    subject_type: models.SubjectType | None = None,
    subject_id: str | None = None,
    status: models.SessionStatus | None = None,
) -> int:
    """
    Count sessions using the same filters as list_sessions().
    """

    statement = select(
        func.count(models.OnboardingSession.id)
    )

    if flow_id is not None:
        statement = statement.where(
            models.OnboardingSession.flow_id == flow_id
        )

    if flow_version_id is not None:
        statement = statement.where(
            models.OnboardingSession.flow_version_id
            == flow_version_id
        )

    if subject_type is not None:
        statement = statement.where(
            models.OnboardingSession.subject_type
            == subject_type
        )

    if subject_id is not None:
        statement = statement.where(
            models.OnboardingSession.subject_id == subject_id
        )

    if status is not None:
        statement = statement.where(
            models.OnboardingSession.status == status
        )

    return int(db.scalar(statement) or 0)


def get_active_session_for_subject(
    db: Session,
    *,
    flow_id: str,
    subject_type: models.SubjectType,
    subject_id: str,
) -> models.OnboardingSession | None:
    """
    Retrieve the newest nonterminal session for one subject and flow.

    The service permits historical completed and abandoned sessions while
    allowing callers to discover an existing active session before creating
    another one.
    """

    statement = (
        select(models.OnboardingSession)
        .where(
            models.OnboardingSession.flow_id == flow_id,
            models.OnboardingSession.subject_type
            == subject_type,
            models.OnboardingSession.subject_id == subject_id,
            models.OnboardingSession.status.not_in(
                TERMINAL_SESSION_STATUSES
            ),
        )
        .order_by(
            models.OnboardingSession.created_at.desc(),
            models.OnboardingSession.id.desc(),
        )
        .limit(1)
    )

    return db.scalar(statement)


def create_session(
    db: Session,
    session_in: schemas.OnboardingSessionCreate,
) -> models.OnboardingSession:
    """
    Create an onboarding session from a published flow version.

    If version_number is omitted, the newest published version is used.

    Requirement definitions are copied into session-specific requirement
    state records so the session preserves its own runtime status.
    """

    flow = flow_crud.get_flow_by_key(
        db,
        session_in.flow_key,
    )

    if flow is None:
        raise ValueError(
            f"flow '{session_in.flow_key}' was not found"
        )

    if flow.status != models.FlowStatus.ACTIVE:
        raise ValueError(
            "new sessions cannot be created for a retired flow"
        )

    if session_in.version_number is None:
        flow_version = flow_crud.get_latest_published_version(
            db,
            flow.id,
            include_definition=True,
        )
    else:
        flow_version = flow_crud.get_flow_version_by_number(
            db,
            flow.id,
            session_in.version_number,
            include_definition=True,
        )

    if flow_version is None:
        if session_in.version_number is None:
            raise ValueError(
                "the flow has no published version"
            )

        raise ValueError(
            f"version {session_in.version_number} was not found "
            f"for flow '{flow.flow_key}'"
        )

    if (
        flow_version.status
        != models.FlowVersionStatus.PUBLISHED
    ):
        raise ValueError(
            "onboarding sessions may only use published versions"
        )

    if flow_version.subject_type != session_in.subject_type:
        raise ValueError(
            "session subject_type does not match the "
            "flow version subject_type"
        )

    if session_in.session_key is not None:
        existing_by_key = get_session_by_key(
            db,
            session_in.session_key,
        )

        if existing_by_key is not None:
            raise ValueError(
                f"session_key '{session_in.session_key}' "
                "already exists"
            )

    first_step_key = _get_first_visible_candidate_step_key(
        flow_version
    )

    onboarding_session = models.OnboardingSession(
        session_key=(
            session_in.session_key
            if session_in.session_key is not None
            else models.new_uuid()
        ),
        flow_id=flow.id,
        flow_version_id=flow_version.id,
        subject_type=session_in.subject_type,
        subject_id=session_in.subject_id,
        status=models.SessionStatus.NOT_STARTED,
        current_step_key=first_step_key,
        progress_percent=0,
        context_json=session_in.context_json,
        metadata_json=session_in.metadata_json,
    )

    db.add(onboarding_session)

    try:
        db.flush()

        for requirement in flow_version.requirements:
            session_requirement = (
                models.OnboardingSessionRequirement(
                    session_id=onboarding_session.id,
                    requirement_id=requirement.id,
                    requirement_key=requirement.requirement_key,
                    status=models.RequirementStatus.PENDING,
                    details_json={},
                )
            )

            db.add(session_requirement)

        event_crud.create_event(
            db,
            event_type=models.EventType.SESSION_CREATED,
            session_id=onboarding_session.id,
            flow_id=flow.id,
            flow_version_id=flow_version.id,
            subject_type=onboarding_session.subject_type,
            subject_id=onboarding_session.subject_id,
            actor_id=session_in.actor_id,
            payload_json={
                "session_key": onboarding_session.session_key,
                "flow_key": flow.flow_key,
                "version_number": (
                    flow_version.version_number
                ),
                "status": onboarding_session.status.value,
                "current_step_key": (
                    onboarding_session.current_step_key
                ),
                "requirement_count": len(
                    flow_version.requirements
                ),
            },
            correlation_id=session_in.correlation_id,
            commit=False,
        )

        db.commit()

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the session could not be created because a unique "
            "session value already exists"
        ) from exc

    except Exception:
        db.rollback()
        raise

    return get_session(
        db,
        onboarding_session.id,
        include_details=True,
    ) or onboarding_session


def start_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> models.OnboardingSession:
    """
    Move a newly created session into IN_PROGRESS state.

    Calling this function repeatedly is idempotent for sessions already in
    progress or blocked.
    """

    _require_nonterminal_session(onboarding_session)

    if onboarding_session.status in {
        models.SessionStatus.IN_PROGRESS,
        models.SessionStatus.BLOCKED,
    }:
        return onboarding_session

    onboarding_session.status = (
        models.SessionStatus.IN_PROGRESS
    )

    if onboarding_session.started_at is None:
        onboarding_session.started_at = utc_now()

    try:
        db.flush()

        event_crud.create_event(
            db,
            event_type=models.EventType.SESSION_STARTED,
            session_id=onboarding_session.id,
            flow_id=onboarding_session.flow_id,
            flow_version_id=(
                onboarding_session.flow_version_id
            ),
            subject_type=onboarding_session.subject_type,
            subject_id=onboarding_session.subject_id,
            actor_id=actor_id,
            payload_json={
                "session_key": (
                    onboarding_session.session_key
                ),
                "status": onboarding_session.status.value,
                "current_step_key": (
                    onboarding_session.current_step_key
                ),
            },
            correlation_id=correlation_id,
            commit=False,
        )

        db.commit()
        db.refresh(onboarding_session)

    except Exception:
        db.rollback()
        raise

    return onboarding_session


def update_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
    session_in: schemas.OnboardingSessionUpdate,
) -> models.OnboardingSession:
    """
    Update mutable runtime session values.

    Status transitions are handled by dedicated CRUD or service functions.
    """

    _require_nonterminal_session(onboarding_session)

    changes = session_in.model_dump(
        exclude_unset=True,
        exclude={
            "actor_id",
            "correlation_id",
        },
    )

    if "current_step_key" in changes:
        _validate_step_key(
            db,
            onboarding_session,
            changes["current_step_key"],
        )

    previous_values: dict[str, object] = {}

    for field_name, value in changes.items():
        previous_values[field_name] = getattr(
            onboarding_session,
            field_name,
        )

        setattr(
            onboarding_session,
            field_name,
            value,
        )

    try:
        db.flush()

        if changes:
            event_crud.create_event(
                db,
                event_type=models.EventType.SESSION_UPDATED,
                session_id=onboarding_session.id,
                flow_id=onboarding_session.flow_id,
                flow_version_id=(
                    onboarding_session.flow_version_id
                ),
                subject_type=(
                    onboarding_session.subject_type
                ),
                subject_id=onboarding_session.subject_id,
                actor_id=session_in.actor_id,
                payload_json={
                    "session_key": (
                        onboarding_session.session_key
                    ),
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
                correlation_id=session_in.correlation_id,
                commit=False,
            )

        db.commit()
        db.refresh(onboarding_session)

    except Exception:
        db.rollback()
        raise

    return onboarding_session


def set_session_runtime_state(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    status: models.SessionStatus | None = None,
    current_step_key: str | None = None,
    progress_percent: int | None = None,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    payload_json: dict | None = None,
    commit: bool = True,
) -> models.OnboardingSession:
    """
    Update calculated runtime state.

    This transaction-aware helper is intended for answer, validation,
    advancement, requirement, and completion services.
    """

    _require_nonterminal_session(onboarding_session)

    changes: dict[str, object] = {}

    if status is not None:
        if status in TERMINAL_SESSION_STATUSES:
            raise ValueError(
                "terminal status transitions must use their "
                "dedicated operation"
            )

        if onboarding_session.status != status:
            changes["status"] = status

    if current_step_key is not None:
        _validate_step_key(
            db,
            onboarding_session,
            current_step_key,
        )

        if (
            onboarding_session.current_step_key
            != current_step_key
        ):
            changes["current_step_key"] = current_step_key

    if progress_percent is not None:
        normalized_progress = max(
            0,
            min(100, progress_percent),
        )

        if (
            onboarding_session.progress_percent
            != normalized_progress
        ):
            changes["progress_percent"] = normalized_progress

    previous_values = {
        key: getattr(onboarding_session, key)
        for key in changes
    }

    for field_name, value in changes.items():
        setattr(
            onboarding_session,
            field_name,
            value,
        )

    if (
        onboarding_session.status
        in {
            models.SessionStatus.IN_PROGRESS,
            models.SessionStatus.BLOCKED,
        }
        and onboarding_session.started_at is None
    ):
        onboarding_session.started_at = utc_now()

    event_type = models.EventType.SESSION_UPDATED

    if status == models.SessionStatus.BLOCKED:
        event_type = models.EventType.SESSION_BLOCKED

    db.flush()

    if changes or payload_json:
        event_payload = {
            "session_key": onboarding_session.session_key,
            "changes": {
                key: {
                    "from": _serialize_value(
                        previous_values[key]
                    ),
                    "to": _serialize_value(value),
                }
                for key, value in changes.items()
            },
        }

        if payload_json:
            event_payload.update(payload_json)

        event_crud.create_event(
            db,
            event_type=event_type,
            session_id=onboarding_session.id,
            flow_id=onboarding_session.flow_id,
            flow_version_id=(
                onboarding_session.flow_version_id
            ),
            subject_type=onboarding_session.subject_type,
            subject_id=onboarding_session.subject_id,
            actor_id=actor_id,
            payload_json=event_payload,
            correlation_id=correlation_id,
            commit=False,
        )

    if commit:
        try:
            db.commit()
            db.refresh(onboarding_session)

        except Exception:
            db.rollback()
            raise

    return onboarding_session


def mark_session_completed(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    payload_json: dict | None = None,
    commit: bool = True,
) -> models.OnboardingSession:
    """
    Mark a validated session as completed.

    Validation and requirement checks belong to the completion service.
    This function performs only the final database transition and event.
    """

    if (
        onboarding_session.status
        == models.SessionStatus.COMPLETED
    ):
        return onboarding_session

    if (
        onboarding_session.status
        == models.SessionStatus.ABANDONED
    ):
        raise ValueError(
            "an abandoned session cannot be completed"
        )

    previous_status = onboarding_session.status

    onboarding_session.status = (
        models.SessionStatus.COMPLETED
    )
    onboarding_session.progress_percent = 100
    onboarding_session.completed_at = utc_now()
    onboarding_session.abandoned_at = None
    onboarding_session.current_step_key = None

    db.flush()

    event_payload = {
        "session_key": onboarding_session.session_key,
        "previous_status": previous_status.value,
        "status": onboarding_session.status.value,
        "progress_percent": 100,
    }

    if payload_json:
        event_payload.update(payload_json)

    event_crud.create_event(
        db,
        event_type=models.EventType.SESSION_COMPLETED,
        session_id=onboarding_session.id,
        flow_id=onboarding_session.flow_id,
        flow_version_id=onboarding_session.flow_version_id,
        subject_type=onboarding_session.subject_type,
        subject_id=onboarding_session.subject_id,
        actor_id=actor_id,
        payload_json=event_payload,
        correlation_id=correlation_id,
        commit=False,
    )

    if commit:
        try:
            db.commit()
            db.refresh(onboarding_session)

        except Exception:
            db.rollback()
            raise

    return onboarding_session


def abandon_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
    abandon_in: schemas.SessionAbandonRequest,
) -> models.OnboardingSession:
    """
    Permanently abandon an unfinished onboarding session.
    """

    if (
        onboarding_session.status
        == models.SessionStatus.ABANDONED
    ):
        return onboarding_session

    if (
        onboarding_session.status
        == models.SessionStatus.COMPLETED
    ):
        raise ValueError(
            "a completed session cannot be abandoned"
        )

    previous_status = onboarding_session.status

    onboarding_session.status = (
        models.SessionStatus.ABANDONED
    )
    onboarding_session.abandoned_at = utc_now()

    try:
        db.flush()

        event_crud.create_event(
            db,
            event_type=models.EventType.SESSION_ABANDONED,
            session_id=onboarding_session.id,
            flow_id=onboarding_session.flow_id,
            flow_version_id=(
                onboarding_session.flow_version_id
            ),
            subject_type=onboarding_session.subject_type,
            subject_id=onboarding_session.subject_id,
            actor_id=abandon_in.actor_id,
            payload_json={
                "session_key": (
                    onboarding_session.session_key
                ),
                "previous_status": previous_status.value,
                "status": onboarding_session.status.value,
                "reason": abandon_in.reason,
            },
            correlation_id=abandon_in.correlation_id,
            commit=False,
        )

        db.commit()
        db.refresh(onboarding_session)

    except Exception:
        db.rollback()
        raise

    return onboarding_session


def get_session_flow_version(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    include_definition: bool = True,
) -> models.OnboardingFlowVersion | None:
    """
    Retrieve the exact immutable version used by a session.
    """

    return flow_crud.get_flow_version(
        db,
        onboarding_session.flow_version_id,
        include_definition=include_definition,
    )


def get_session_step(
    db: Session,
    onboarding_session: models.OnboardingSession,
    step_key: str,
) -> models.OnboardingStep | None:
    """
    Retrieve one step from the version assigned to a session.
    """

    statement = (
        select(models.OnboardingStep)
        .where(
            models.OnboardingStep.flow_version_id
            == onboarding_session.flow_version_id,
            models.OnboardingStep.step_key == step_key,
        )
        .options(
            selectinload(models.OnboardingStep.fields)
        )
    )

    return db.scalar(statement)


def get_current_step(
    db: Session,
    onboarding_session: models.OnboardingSession,
) -> models.OnboardingStep | None:
    """
    Retrieve the session's current step with its fields.
    """

    if onboarding_session.current_step_key is None:
        return None

    return get_session_step(
        db,
        onboarding_session,
        onboarding_session.current_step_key,
    )


def list_session_requirements(
    db: Session,
    session_id: str,
) -> Sequence[models.OnboardingSessionRequirement]:
    """
    List one session's requirement states in definition order.
    """

    statement = (
        select(models.OnboardingSessionRequirement)
        .join(
            models.OnboardingRequirement,
            models.OnboardingSessionRequirement.requirement_id
            == models.OnboardingRequirement.id,
        )
        .where(
            models.OnboardingSessionRequirement.session_id
            == session_id
        )
        .options(
            selectinload(
                models.OnboardingSessionRequirement.requirement
            )
        )
        .order_by(
            models.OnboardingRequirement.position.asc(),
            models.OnboardingRequirement.id.asc(),
        )
    )

    return db.scalars(statement).all()


def _get_first_visible_candidate_step_key(
    flow_version: models.OnboardingFlowVersion,
) -> str | None:
    """
    Select the first ordered step as the initial runtime candidate.

    Actual conditional visibility is evaluated later by the conditions
    service after session answers exist.
    """

    if not flow_version.steps:
        return None

    ordered_steps = sorted(
        flow_version.steps,
        key=lambda step: (
            step.position,
            step.id,
        ),
    )

    return ordered_steps[0].step_key


def _validate_step_key(
    db: Session,
    onboarding_session: models.OnboardingSession,
    step_key: str | None,
) -> None:
    if step_key is None:
        return

    step = get_session_step(
        db,
        onboarding_session,
        step_key,
    )

    if step is None:
        raise ValueError(
            f"step '{step_key}' does not belong to the "
            "session's flow version"
        )


def _require_nonterminal_session(
    onboarding_session: models.OnboardingSession,
) -> None:
    if onboarding_session.status in TERMINAL_SESSION_STATUSES:
        raise ValueError(
            f"session is {onboarding_session.status.value.lower()} "
            "and can no longer be modified"
        )


def _serialize_value(value: object) -> object:
    if isinstance(value, models.SessionStatus):
        return value.value

    if isinstance(value, models.SubjectType):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    return value
