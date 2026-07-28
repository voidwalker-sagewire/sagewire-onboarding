from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.crud import events as event_crud
from app.crud import sessions as session_crud
from app.database import get_db


router = APIRouter(
    prefix="/events",
    tags=["Onboarding Events"],
)


@router.get(
    "",
    response_model=schemas.OnboardingEventListResponse,
)
def list_events(
    event_type: models.EventType | None = Query(
        default=None,
        alias="type",
    ),
    session_id: str | None = Query(
        default=None,
    ),
    actor_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=255,
    ),
    correlation_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=255,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> schemas.OnboardingEventListResponse:
    """
    List onboarding audit events.

    Events are immutable audit records. They may be filtered by event type,
    session, actor, or correlation identifier.
    """

    if session_id is not None:
        onboarding_session = (
            session_crud.resolve_session(
                db,
                session_id,
            )
        )

        if onboarding_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"onboarding session "
                    f"'{session_id}' was not found"
                ),
            )

        resolved_session_id = (
            onboarding_session.id
        )
    else:
        resolved_session_id = None

    items = event_crud.list_events(
        db,
        event_type=event_type,
        session_id=resolved_session_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )

    total = event_crud.count_events(
        db,
        event_type=event_type,
        session_id=resolved_session_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
    )

    return schemas.OnboardingEventListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_identifier}",
    response_model=schemas.OnboardingEventListResponse,
)
def list_session_events(
    session_identifier: str,
    event_type: models.EventType | None = Query(
        default=None,
        alias="type",
    ),
    actor_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=255,
    ),
    correlation_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=255,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> schemas.OnboardingEventListResponse:
    """
    List the complete audit history for one onboarding session.

    The session may be identified by its UUID or stable session key.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    items = event_crud.list_session_events(
        db,
        onboarding_session.id,
        event_type=event_type,
        actor_id=actor_id,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )

    total = event_crud.count_session_events(
        db,
        onboarding_session.id,
        event_type=event_type,
        actor_id=actor_id,
        correlation_id=correlation_id,
    )

    return schemas.OnboardingEventListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_identifier}/latest",
    response_model=schemas.OnboardingEventResponse,
)
def get_latest_session_event(
    session_identifier: str,
    db: Session = Depends(get_db),
) -> models.OnboardingEvent:
    """
    Retrieve the most recent event recorded for one onboarding session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    events = event_crud.list_session_events(
        db,
        onboarding_session.id,
        limit=1,
        offset=0,
    )

    if not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "this onboarding session does not "
                "have any recorded events"
            ),
        )

    return events[0]


@router.get(
    "/correlations/{correlation_id}",
    response_model=schemas.OnboardingEventListResponse,
)
def list_correlation_events(
    correlation_id: str,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> schemas.OnboardingEventListResponse:
    """
    List events belonging to one distributed operation or request chain.

    A correlation identifier may connect changes made across flows,
    sessions, answers, requirements, and external services.
    """

    items = event_crud.list_events(
        db,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )

    total = event_crud.count_events(
        db,
        correlation_id=correlation_id,
    )

    return schemas.OnboardingEventListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{event_identifier}",
    response_model=schemas.OnboardingEventResponse,
)
def get_event(
    event_identifier: str,
    db: Session = Depends(get_db),
) -> models.OnboardingEvent:
    """
    Retrieve one immutable audit event by UUID or stable event key.
    """

    event = _resolve_event_or_404(
        db,
        event_identifier,
    )

    return event


def _resolve_event_or_404(
    db: Session,
    event_identifier: str,
) -> models.OnboardingEvent:
    event = event_crud.get_event(
        db,
        event_identifier,
    )

    if event is None:
        event = event_crud.get_event_by_key(
            db,
            event_identifier,
        )

    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"onboarding event "
                f"'{event_identifier}' was not found"
            ),
        )

    return event


def _resolve_session_or_404(
    db: Session,
    session_identifier: str,
) -> models.OnboardingSession:
    onboarding_session = (
        session_crud.resolve_session(
            db,
            session_identifier,
        )
    )

    if onboarding_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"onboarding session "
                f"'{session_identifier}' was not found"
            ),
        )

    return onboarding_session
