from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.crud import events as event_crud
from app.crud import sessions as session_crud


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_session_requirement(
    db: Session,
    session_requirement_id: str,
    *,
    include_definition: bool = True,
) -> models.OnboardingSessionRequirement | None:
    """
    Retrieve a session requirement state by its database UUID.
    """

    statement = select(
        models.OnboardingSessionRequirement
    ).where(
        models.OnboardingSessionRequirement.id
        == session_requirement_id
    )

    if include_definition:
        statement = statement.options(
            selectinload(
                models.OnboardingSessionRequirement.requirement
            )
        )

    return db.scalar(statement)


def get_session_requirement_by_key(
    db: Session,
    *,
    session_id: str,
    requirement_key: str,
    include_definition: bool = True,
) -> models.OnboardingSessionRequirement | None:
    """
    Retrieve one requirement state using the session and stable
    requirement key.
    """

    statement = select(
        models.OnboardingSessionRequirement
    ).where(
        models.OnboardingSessionRequirement.session_id
        == session_id,
        models.OnboardingSessionRequirement.requirement_key
        == requirement_key,
    )

    if include_definition:
        statement = statement.options(
            selectinload(
                models.OnboardingSessionRequirement.requirement
            )
        )

    return db.scalar(statement)


def list_session_requirements(
    db: Session,
    session_id: str,
    *,
    status: models.RequirementStatus | None = None,
    required_only: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> Sequence[models.OnboardingSessionRequirement]:
    """
    List requirement states for one onboarding session.

    Requirement states are ordered according to their immutable flow
    definition.
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
    )

    if status is not None:
        statement = statement.where(
            models.OnboardingSessionRequirement.status
            == status
        )

    if required_only:
        statement = statement.where(
            models.OnboardingRequirement.required.is_(True)
        )

    statement = (
        statement.order_by(
            models.OnboardingRequirement.position.asc(),
            models.OnboardingRequirement.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    return db.scalars(statement).all()


def count_session_requirements(
    db: Session,
    session_id: str,
    *,
    status: models.RequirementStatus | None = None,
    required_only: bool = False,
) -> int:
    """
    Count session requirement states using the same filters as
    list_session_requirements().
    """

    statement = (
        select(
            func.count(
                models.OnboardingSessionRequirement.id
            )
        )
        .join(
            models.OnboardingRequirement,
            models.OnboardingSessionRequirement.requirement_id
            == models.OnboardingRequirement.id,
        )
        .where(
            models.OnboardingSessionRequirement.session_id
            == session_id
        )
    )

    if status is not None:
        statement = statement.where(
            models.OnboardingSessionRequirement.status
            == status
        )

    if required_only:
        statement = statement.where(
            models.OnboardingRequirement.required.is_(True)
        )

    return int(db.scalar(statement) or 0)


def update_session_requirement(
    db: Session,
    onboarding_session: models.OnboardingSession,
    requirement_key: str,
    requirement_in: schemas.SessionRequirementUpdate,
    *,
    commit: bool = True,
) -> models.OnboardingSessionRequirement:
    """
    Update the runtime state of one onboarding requirement.

    The requirement definition remains unchanged. Only the state belonging
    to this specific onboarding session is modified.

    Set commit=False when the update is part of a larger transaction.
    """

    _require_modifiable_session(onboarding_session)

    session_requirement = get_session_requirement_by_key(
        db,
        session_id=onboarding_session.id,
        requirement_key=requirement_key,
        include_definition=True,
    )

    if session_requirement is None:
        raise ValueError(
            f"requirement '{requirement_key}' does not belong "
            "to this onboarding session"
        )

    previous_status = session_requirement.status
    previous_external_reference = (
        session_requirement.external_reference
    )
    previous_details = dict(
        session_requirement.details_json or {}
    )
    previous_satisfied_by = (
        session_requirement.satisfied_by
    )
    previous_satisfied_at = (
        session_requirement.satisfied_at
    )

    session_requirement.status = requirement_in.status
    session_requirement.external_reference = (
        requirement_in.external_reference
    )
    session_requirement.details_json = (
        requirement_in.details_json
    )

    if (
        requirement_in.status
        == models.RequirementStatus.SATISFIED
    ):
        session_requirement.satisfied_by = (
            requirement_in.satisfied_by
        )

        if session_requirement.satisfied_at is None:
            session_requirement.satisfied_at = utc_now()

    else:
        session_requirement.satisfied_by = None
        session_requirement.satisfied_at = None

    try:
        db.flush()

        event_type = _requirement_event_type(
            previous_status=previous_status,
            new_status=session_requirement.status,
        )

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
            actor_id=requirement_in.satisfied_by,
            payload_json={
                "session_requirement_id": (
                    session_requirement.id
                ),
                "requirement_id": (
                    session_requirement.requirement_id
                ),
                "requirement_key": (
                    session_requirement.requirement_key
                ),
                "required": (
                    session_requirement.requirement.required
                    if session_requirement.requirement
                    is not None
                    else None
                ),
                "previous_status": previous_status.value,
                "status": session_requirement.status.value,
                "changes": {
                    "external_reference": {
                        "from": previous_external_reference,
                        "to": (
                            session_requirement.external_reference
                        ),
                    },
                    "details_json": {
                        "from": previous_details,
                        "to": (
                            session_requirement.details_json
                        ),
                    },
                    "satisfied_by": {
                        "from": previous_satisfied_by,
                        "to": (
                            session_requirement.satisfied_by
                        ),
                    },
                    "satisfied_at": {
                        "from": _serialize_datetime(
                            previous_satisfied_at
                        ),
                        "to": _serialize_datetime(
                            session_requirement.satisfied_at
                        ),
                    },
                },
            },
            correlation_id=requirement_in.correlation_id,
            commit=False,
        )

        if commit:
            db.commit()
            db.refresh(session_requirement)

    except Exception:
        if commit:
            db.rollback()
        raise

    return session_requirement


def satisfy_requirement(
    db: Session,
    onboarding_session: models.OnboardingSession,
    requirement_key: str,
    *,
    satisfied_by: str,
    external_reference: str | None = None,
    details_json: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> models.OnboardingSessionRequirement:
    """
    Convenience operation for marking a requirement satisfied.
    """

    requirement_in = schemas.SessionRequirementUpdate(
        status=models.RequirementStatus.SATISFIED,
        external_reference=external_reference,
        details_json=details_json or {},
        satisfied_by=satisfied_by,
        correlation_id=correlation_id,
    )

    return update_session_requirement(
        db,
        onboarding_session,
        requirement_key,
        requirement_in,
        commit=commit,
    )


def reset_requirement(
    db: Session,
    onboarding_session: models.OnboardingSession,
    requirement_key: str,
    *,
    actor_id: str | None = None,
    details_json: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> models.OnboardingSessionRequirement:
    """
    Reset a requirement to its pending state.

    This is useful when an external verification expires, a payment lapses,
    a device goes offline, or an administrator revokes approval.
    """

    pending_status = _get_requirement_status("PENDING")

    requirement_in = schemas.SessionRequirementUpdate(
        status=pending_status,
        external_reference=None,
        details_json=details_json or {},
        satisfied_by=None,
        correlation_id=correlation_id,
    )

    session_requirement = update_session_requirement(
        db,
        onboarding_session,
        requirement_key,
        requirement_in,
        commit=False,
    )

    if actor_id is not None:
        event_crud.create_event(
            db,
            event_type=_get_event_type(
                "REQUIREMENT_RESET",
                fallback="SESSION_UPDATED",
            ),
            session_id=onboarding_session.id,
            flow_id=onboarding_session.flow_id,
            flow_version_id=(
                onboarding_session.flow_version_id
            ),
            subject_type=onboarding_session.subject_type,
            subject_id=onboarding_session.subject_id,
            actor_id=actor_id,
            payload_json={
                "session_requirement_id": (
                    session_requirement.id
                ),
                "requirement_key": requirement_key,
                "action": "reset",
            },
            correlation_id=correlation_id,
            commit=False,
        )

    if commit:
        try:
            db.commit()
            db.refresh(session_requirement)

        except Exception:
            db.rollback()
            raise

    return session_requirement


def waive_requirement(
    db: Session,
    onboarding_session: models.OnboardingSession,
    requirement_key: str,
    *,
    waived_by: str,
    reason: str,
    correlation_id: str | None = None,
    commit: bool = True,
) -> models.OnboardingSessionRequirement:
    """
    Mark a requirement waived when the RequirementStatus enum supports
    WAIVED.

    A waiver is treated as nonblocking by the blocking-requirement helpers.
    """

    waived_status = _get_requirement_status("WAIVED")

    requirement_in = schemas.SessionRequirementUpdate(
        status=waived_status,
        external_reference=None,
        details_json={
            "waiver_reason": reason,
        },
        satisfied_by=None,
        correlation_id=correlation_id,
    )

    session_requirement = update_session_requirement(
        db,
        onboarding_session,
        requirement_key,
        requirement_in,
        commit=False,
    )

    event_crud.create_event(
        db,
        event_type=_get_event_type(
            "REQUIREMENT_WAIVED",
            fallback="SESSION_UPDATED",
        ),
        session_id=onboarding_session.id,
        flow_id=onboarding_session.flow_id,
        flow_version_id=onboarding_session.flow_version_id,
        subject_type=onboarding_session.subject_type,
        subject_id=onboarding_session.subject_id,
        actor_id=waived_by,
        payload_json={
            "session_requirement_id": (
                session_requirement.id
            ),
            "requirement_key": requirement_key,
            "reason": reason,
        },
        correlation_id=correlation_id,
        commit=False,
    )

    if commit:
        try:
            db.commit()
            db.refresh(session_requirement)

        except Exception:
            db.rollback()
            raise

    return session_requirement


def list_blocking_requirements(
    db: Session,
    onboarding_session: models.OnboardingSession,
) -> Sequence[models.OnboardingSessionRequirement]:
    """
    Return required, visible requirement states that are not satisfied or
    waived.

    Visibility conditions are evaluated later by the conditions service.
    Until that service is applied, this function considers all required
    requirement definitions potentially active.
    """

    nonblocking_statuses = [
        models.RequirementStatus.SATISFIED
    ]

    waived_status = models.RequirementStatus.__members__.get(
        "WAIVED"
    )

    if waived_status is not None:
        nonblocking_statuses.append(waived_status)

    statement = (
        select(models.OnboardingSessionRequirement)
        .join(
            models.OnboardingRequirement,
            models.OnboardingSessionRequirement.requirement_id
            == models.OnboardingRequirement.id,
        )
        .where(
            models.OnboardingSessionRequirement.session_id
            == onboarding_session.id,
            models.OnboardingRequirement.required.is_(True),
            models.OnboardingSessionRequirement.status.not_in(
                nonblocking_statuses
            ),
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


def has_blocking_requirements(
    db: Session,
    onboarding_session: models.OnboardingSession,
) -> bool:
    """
    Return True when at least one required requirement remains blocking.
    """

    return bool(
        list_blocking_requirements(
            db,
            onboarding_session,
        )
    )


def all_required_requirements_satisfied(
    db: Session,
    onboarding_session: models.OnboardingSession,
) -> bool:
    """
    Return True when no required requirement remains blocking.
    """

    return not has_blocking_requirements(
        db,
        onboarding_session,
    )


def sync_session_requirement_states(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    commit: bool = True,
) -> list[models.OnboardingSessionRequirement]:
    """
    Ensure the session has one runtime state row for every requirement
    definition in its assigned flow version.

    Sessions normally receive these rows at creation. This repair helper is
    useful after migrations, imports, or administrative correction.
    """

    _require_modifiable_session(onboarding_session)

    flow_version = session_crud.get_session_flow_version(
        db,
        onboarding_session,
        include_definition=True,
    )

    if flow_version is None:
        raise ValueError(
            "the session's flow version no longer exists"
        )

    existing_states = list_session_requirements(
        db,
        onboarding_session.id,
    )

    existing_requirement_ids = {
        state.requirement_id
        for state in existing_states
    }

    created_states: list[
        models.OnboardingSessionRequirement
    ] = []

    pending_status = _get_requirement_status("PENDING")

    for requirement in flow_version.requirements:
        if requirement.id in existing_requirement_ids:
            continue

        session_requirement = (
            models.OnboardingSessionRequirement(
                session_id=onboarding_session.id,
                requirement_id=requirement.id,
                requirement_key=requirement.requirement_key,
                status=pending_status,
                details_json={},
            )
        )

        db.add(session_requirement)
        created_states.append(session_requirement)

    try:
        db.flush()

        if created_states:
            event_crud.create_event(
                db,
                event_type=_get_event_type(
                    "REQUIREMENTS_SYNCHRONIZED",
                    fallback="SESSION_UPDATED",
                ),
                session_id=onboarding_session.id,
                flow_id=onboarding_session.flow_id,
                flow_version_id=(
                    onboarding_session.flow_version_id
                ),
                subject_type=(
                    onboarding_session.subject_type
                ),
                subject_id=onboarding_session.subject_id,
                payload_json={
                    "created_count": len(created_states),
                    "requirement_keys": [
                        item.requirement_key
                        for item in created_states
                    ],
                },
                commit=False,
            )

        if commit:
            db.commit()

            for item in created_states:
                db.refresh(item)

    except Exception:
        if commit:
            db.rollback()
        raise

    return created_states


def _require_modifiable_session(
    onboarding_session: models.OnboardingSession,
) -> None:
    if onboarding_session.status in {
        models.SessionStatus.COMPLETED,
        models.SessionStatus.ABANDONED,
    }:
        raise ValueError(
            f"session is "
            f"{onboarding_session.status.value.lower()} "
            "and its requirements can no longer be modified"
        )


def _requirement_event_type(
    *,
    previous_status: models.RequirementStatus,
    new_status: models.RequirementStatus,
) -> models.EventType:
    if (
        new_status
        == models.RequirementStatus.SATISFIED
    ):
        return _get_event_type(
            "REQUIREMENT_SATISFIED",
            fallback="SESSION_UPDATED",
        )

    if (
        previous_status
        == models.RequirementStatus.SATISFIED
        and new_status
        != models.RequirementStatus.SATISFIED
    ):
        return _get_event_type(
            "REQUIREMENT_REVOKED",
            fallback="SESSION_UPDATED",
        )

    if new_status.name == "FAILED":
        return _get_event_type(
            "REQUIREMENT_FAILED",
            fallback="SESSION_UPDATED",
        )

    if new_status.name == "WAIVED":
        return _get_event_type(
            "REQUIREMENT_WAIVED",
            fallback="SESSION_UPDATED",
        )

    return _get_event_type(
        "REQUIREMENT_UPDATED",
        fallback="SESSION_UPDATED",
    )


def _get_event_type(
    name: str,
    *,
    fallback: str,
) -> models.EventType:
    """
    Resolve newer, more precise event types while remaining compatible
    with the current EventType enum.
    """

    event_type = models.EventType.__members__.get(name)

    if event_type is not None:
        return event_type

    fallback_type = models.EventType.__members__.get(
        fallback
    )

    if fallback_type is None:
        raise ValueError(
            f"EventType contains neither '{name}' "
            f"nor fallback '{fallback}'"
        )

    return fallback_type


def _get_requirement_status(
    name: str,
) -> models.RequirementStatus:
    status = models.RequirementStatus.__members__.get(name)

    if status is None:
        raise ValueError(
            f"RequirementStatus does not support '{name}'"
        )

    return status


def _serialize_datetime(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    return value.isoformat()
