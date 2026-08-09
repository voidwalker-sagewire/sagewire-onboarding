from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas


def create_event(
    db: Session,
    *,
    event_type: models.EventType,
    session_id: str | None = None,
    flow_id: str | None = None,
    flow_version_id: str | None = None,
    subject_type: models.SubjectType | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    payload_json: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> models.OnboardingEvent:
    """
    Create a durable onboarding event.

    Set commit=False when the event is being created as part of a larger
    transaction. The caller is then responsible for committing or rolling
    back the transaction.
    """

    event = models.OnboardingEvent(
        event_type=event_type,
        session_id=session_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_id=actor_id,
        payload_json=payload_json or {},
        correlation_id=correlation_id,
    )

    db.add(event)

    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()

    return event


def create_event_from_schema(
    db: Session,
    event_in: schemas.OnboardingEventCreate,
    *,
    commit: bool = True,
) -> models.OnboardingEvent:
    """
    Create an onboarding event from a validated Pydantic schema.
    """

    return create_event(
        db,
        event_type=event_in.event_type,
        session_id=event_in.session_id,
        flow_id=event_in.flow_id,
        flow_version_id=event_in.flow_version_id,
        subject_type=event_in.subject_type,
        subject_id=event_in.subject_id,
        actor_id=event_in.actor_id,
        payload_json=event_in.payload_json,
        correlation_id=event_in.correlation_id,
        commit=commit,
    )


def get_event(
    db: Session,
    event_id: str,
) -> models.OnboardingEvent | None:
    """
    Retrieve an event by its database UUID.
    """

    statement = select(models.OnboardingEvent).where(
        models.OnboardingEvent.id == event_id
    )

    return db.scalar(statement)


def get_event_by_key(
    db: Session,
    event_key: str,
) -> models.OnboardingEvent | None:
    """
    Retrieve an event by its public event key.
    """

    statement = select(models.OnboardingEvent).where(
        models.OnboardingEvent.event_key == event_key
    )

    return db.scalar(statement)


def list_events(
    db: Session,
    *,
    session_id: str | None = None,
    flow_id: str | None = None,
    flow_version_id: str | None = None,
    event_type: models.EventType | None = None,
    subject_type: models.SubjectType | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[models.OnboardingEvent]:
    """
    List onboarding events using optional filters.

    Results are returned oldest-first so the list forms a readable,
    chronological audit trail.
    """

    statement = select(models.OnboardingEvent)

    if session_id is not None:
        statement = statement.where(
            models.OnboardingEvent.session_id == session_id
        )

    if flow_id is not None:
        statement = statement.where(
            models.OnboardingEvent.flow_id == flow_id
        )

    if flow_version_id is not None:
        statement = statement.where(
            models.OnboardingEvent.flow_version_id == flow_version_id
        )

    if event_type is not None:
        statement = statement.where(
            models.OnboardingEvent.event_type == event_type
        )

    if subject_type is not None:
        statement = statement.where(
            models.OnboardingEvent.subject_type == subject_type
        )

    if subject_id is not None:
        statement = statement.where(
            models.OnboardingEvent.subject_id == subject_id
        )

    if actor_id is not None:
        statement = statement.where(
            models.OnboardingEvent.actor_id == actor_id
        )

    if correlation_id is not None:
        statement = statement.where(
            models.OnboardingEvent.correlation_id == correlation_id
        )

    statement = (
        statement.order_by(
            models.OnboardingEvent.created_at.asc(),
            models.OnboardingEvent.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    return db.scalars(statement).all()


def count_events(
    db: Session,
    *,
    session_id: str | None = None,
    flow_id: str | None = None,
    flow_version_id: str | None = None,
    event_type: models.EventType | None = None,
    subject_type: models.SubjectType | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> int:
    """
    Count onboarding events using the same filters as list_events().
    """

    statement = select(
        func.count(models.OnboardingEvent.id)
    )

    if session_id is not None:
        statement = statement.where(
            models.OnboardingEvent.session_id == session_id
        )

    if flow_id is not None:
        statement = statement.where(
            models.OnboardingEvent.flow_id == flow_id
        )

    if flow_version_id is not None:
        statement = statement.where(
            models.OnboardingEvent.flow_version_id == flow_version_id
        )

    if event_type is not None:
        statement = statement.where(
            models.OnboardingEvent.event_type == event_type
        )

    if subject_type is not None:
        statement = statement.where(
            models.OnboardingEvent.subject_type == subject_type
        )

    if subject_id is not None:
        statement = statement.where(
            models.OnboardingEvent.subject_id == subject_id
        )

    if actor_id is not None:
        statement = statement.where(
            models.OnboardingEvent.actor_id == actor_id
        )

    if correlation_id is not None:
        statement = statement.where(
            models.OnboardingEvent.correlation_id == correlation_id
        )

    return int(db.scalar(statement) or 0)


def list_session_events(
    db: Session,
    session_id: str,
    *,
    event_type: models.EventType | None = None,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[models.OnboardingEvent]:
    """
    Convenience wrapper for retrieving one session's audit trail.
    """

    return list_events(
        db,
        session_id=session_id,
        event_type=event_type,
        actor_id=actor_id,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )


def count_session_events(
    db: Session,
    session_id: str,
    *,
    event_type: models.EventType | None = None,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> int:
    """
    Convenience wrapper for counting one session's events.
    """

    return count_events(
        db,
        session_id=session_id,
        event_type=event_type,
        actor_id=actor_id,
        correlation_id=correlation_id,
    )
