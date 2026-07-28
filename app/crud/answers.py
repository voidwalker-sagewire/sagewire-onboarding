from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.crud import events as event_crud
from app.crud import sessions as session_crud


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_answer(
    db: Session,
    answer_id: str,
) -> models.OnboardingAnswer | None:
    """
    Retrieve an onboarding answer by its database UUID.
    """

    statement = (
        select(models.OnboardingAnswer)
        .where(
            models.OnboardingAnswer.id == answer_id
        )
        .options(
            selectinload(models.OnboardingAnswer.field)
        )
    )

    return db.scalar(statement)


def get_answer_by_field_id(
    db: Session,
    *,
    session_id: str,
    field_id: str,
) -> models.OnboardingAnswer | None:
    """
    Retrieve one answer by session and field UUID.
    """

    statement = (
        select(models.OnboardingAnswer)
        .where(
            models.OnboardingAnswer.session_id == session_id,
            models.OnboardingAnswer.field_id == field_id,
        )
        .options(
            selectinload(models.OnboardingAnswer.field)
        )
    )

    return db.scalar(statement)


def get_answer_by_field_key(
    db: Session,
    *,
    session_id: str,
    field_key: str,
) -> models.OnboardingAnswer | None:
    """
    Retrieve one answer by session and stable field key.
    """

    statement = (
        select(models.OnboardingAnswer)
        .where(
            models.OnboardingAnswer.session_id == session_id,
            models.OnboardingAnswer.field_key == field_key,
        )
        .options(
            selectinload(models.OnboardingAnswer.field)
        )
    )

    return db.scalar(statement)


def list_answers(
    db: Session,
    session_id: str,
) -> Sequence[models.OnboardingAnswer]:
    """
    List all answers for a session in flow-definition order.
    """

    statement = (
        select(models.OnboardingAnswer)
        .join(
            models.OnboardingField,
            models.OnboardingAnswer.field_id
            == models.OnboardingField.id,
        )
        .join(
            models.OnboardingStep,
            models.OnboardingField.step_id
            == models.OnboardingStep.id,
        )
        .where(
            models.OnboardingAnswer.session_id == session_id
        )
        .options(
            selectinload(models.OnboardingAnswer.field)
        )
        .order_by(
            models.OnboardingStep.position.asc(),
            models.OnboardingField.position.asc(),
            models.OnboardingAnswer.id.asc(),
        )
    )

    return db.scalars(statement).all()


def get_field_for_session(
    db: Session,
    *,
    onboarding_session: models.OnboardingSession,
    field_key: str,
) -> models.OnboardingField | None:
    """
    Retrieve a field from the exact flow version assigned to a session.
    """

    statement = (
        select(models.OnboardingField)
        .join(
            models.OnboardingStep,
            models.OnboardingField.step_id
            == models.OnboardingStep.id,
        )
        .where(
            models.OnboardingField.flow_version_id
            == onboarding_session.flow_version_id,
            models.OnboardingField.field_key == field_key,
        )
        .options(
            selectinload(models.OnboardingField.step)
        )
    )

    return db.scalar(statement)


def list_fields_for_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
) -> Sequence[models.OnboardingField]:
    """
    List all fields from the immutable flow version used by a session.
    """

    statement = (
        select(models.OnboardingField)
        .join(
            models.OnboardingStep,
            models.OnboardingField.step_id
            == models.OnboardingStep.id,
        )
        .where(
            models.OnboardingField.flow_version_id
            == onboarding_session.flow_version_id
        )
        .options(
            selectinload(models.OnboardingField.step)
        )
        .order_by(
            models.OnboardingStep.position.asc(),
            models.OnboardingField.position.asc(),
            models.OnboardingField.id.asc(),
        )
    )

    return db.scalars(statement).all()


def write_answer(
    db: Session,
    onboarding_session: models.OnboardingSession,
    field_key: str,
    answer_in: schemas.OnboardingAnswerWrite,
    *,
    commit: bool = True,
) -> models.OnboardingAnswer:
    """
    Create or update one answer.

    This CRUD layer confirms that the field belongs to the session's exact
    flow version and stores the value. Detailed type and business-rule
    validation is handled by the validation service.

    Set commit=False when this operation is part of a larger transaction.
    """

    _require_modifiable_session(onboarding_session)

    field = get_field_for_session(
        db,
        onboarding_session=onboarding_session,
        field_key=field_key,
    )

    if field is None:
        raise ValueError(
            f"field '{field_key}' does not belong to the "
            "session's flow version"
        )

    existing_answer = get_answer_by_field_id(
        db,
        session_id=onboarding_session.id,
        field_id=field.id,
    )

    now = utc_now()

    if existing_answer is None:
        answer = models.OnboardingAnswer(
            session_id=onboarding_session.id,
            field_id=field.id,
            field_key=field.field_key,
            value_json=answer_in.value_json,
            is_valid=True,
            validation_errors_json=[],
            answered_by=answer_in.answered_by,
            answered_at=now,
        )

        db.add(answer)
        event_type = models.EventType.ANSWER_CREATED
        previous_value = None

    else:
        answer = existing_answer
        previous_value = answer.value_json

        answer.value_json = answer_in.value_json
        answer.is_valid = True
        answer.validation_errors_json = []
        answer.answered_by = answer_in.answered_by
        answer.answered_at = now

        event_type = models.EventType.ANSWER_UPDATED

    try:
        db.flush()

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
            actor_id=answer_in.answered_by,
            payload_json={
                "answer_id": answer.id,
                "field_id": field.id,
                "field_key": field.field_key,
                "step_key": (
                    field.step.step_key
                    if field.step is not None
                    else None
                ),
                "previous_value": _event_safe_value(
                    previous_value,
                    sensitive=field.sensitive,
                ),
                "value": _event_safe_value(
                    answer.value_json,
                    sensitive=field.sensitive,
                ),
                "sensitive": field.sensitive,
            },
            correlation_id=answer_in.correlation_id,
            commit=False,
        )

        _ensure_session_started(
            onboarding_session
        )

        if commit:
            db.commit()
            db.refresh(answer)

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "the answer could not be saved because an answer "
            "already exists for this session and field"
        ) from exc

    except Exception:
        if commit:
            db.rollback()
        raise

    return answer


def write_answers_bulk(
    db: Session,
    onboarding_session: models.OnboardingSession,
    bulk_in: schemas.OnboardingAnswerBulkWrite,
) -> list[models.OnboardingAnswer]:
    """
    Create or update multiple answers in one atomic transaction.

    If any field key is invalid or any write fails, no answers are committed.
    """

    _require_modifiable_session(onboarding_session)

    fields = list_fields_for_session(
        db,
        onboarding_session,
    )

    fields_by_key = {
        field.field_key: field
        for field in fields
    }

    unknown_field_keys = [
        item.field_key
        for item in bulk_in.answers
        if item.field_key not in fields_by_key
    ]

    if unknown_field_keys:
        unknown_list = ", ".join(
            sorted(unknown_field_keys)
        )

        raise ValueError(
            "the following fields do not belong to the "
            f"session's flow version: {unknown_list}"
        )

    saved_answers: list[models.OnboardingAnswer] = []

    try:
        for item in bulk_in.answers:
            write_in = schemas.OnboardingAnswerWrite(
                value_json=item.value_json,
                answered_by=bulk_in.answered_by,
                correlation_id=bulk_in.correlation_id,
            )

            answer = write_answer(
                db,
                onboarding_session,
                item.field_key,
                write_in,
                commit=False,
            )

            saved_answers.append(answer)

        _ensure_session_started(
            onboarding_session
        )

        db.commit()

        for answer in saved_answers:
            db.refresh(answer)

    except Exception:
        db.rollback()
        raise

    return saved_answers


def set_answer_validation(
    db: Session,
    answer: models.OnboardingAnswer,
    *,
    is_valid: bool,
    validation_errors: list[dict[str, Any]] | None = None,
    commit: bool = True,
) -> models.OnboardingAnswer:
    """
    Store validation results for one answer.

    This helper is intended for the validation service.
    """

    answer.is_valid = is_valid
    answer.validation_errors_json = (
        validation_errors or []
    )

    if commit:
        try:
            db.commit()
            db.refresh(answer)

        except Exception:
            db.rollback()
            raise
    else:
        db.flush()

    return answer


def clear_answer(
    db: Session,
    onboarding_session: models.OnboardingSession,
    field_key: str,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> models.OnboardingAnswer:
    """
    Clear an answer while preserving its audit record.

    The answer row remains present with value_json set to None. This is
    preferable to deleting the record because it preserves answer history
    through the event ledger.
    """

    _require_modifiable_session(onboarding_session)

    field = get_field_for_session(
        db,
        onboarding_session=onboarding_session,
        field_key=field_key,
    )

    if field is None:
        raise ValueError(
            f"field '{field_key}' does not belong to the "
            "session's flow version"
        )

    answer = get_answer_by_field_id(
        db,
        session_id=onboarding_session.id,
        field_id=field.id,
    )

    if answer is None:
        answer = models.OnboardingAnswer(
            session_id=onboarding_session.id,
            field_id=field.id,
            field_key=field.field_key,
            value_json=None,
            is_valid=True,
            validation_errors_json=[],
            answered_by=actor_id,
            answered_at=utc_now(),
        )

        db.add(answer)
        previous_value = None
        event_type = models.EventType.ANSWER_CREATED

    else:
        previous_value = answer.value_json
        answer.value_json = None
        answer.is_valid = True
        answer.validation_errors_json = []
        answer.answered_by = actor_id
        answer.answered_at = utc_now()
        event_type = models.EventType.ANSWER_UPDATED

    try:
        db.flush()

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
            payload_json={
                "answer_id": answer.id,
                "field_id": field.id,
                "field_key": field.field_key,
                "action": "cleared",
                "previous_value": _event_safe_value(
                    previous_value,
                    sensitive=field.sensitive,
                ),
                "value": None,
                "sensitive": field.sensitive,
            },
            correlation_id=correlation_id,
            commit=False,
        )

        if commit:
            db.commit()
            db.refresh(answer)

    except Exception:
        if commit:
            db.rollback()
        raise

    return answer


def delete_answer(
    db: Session,
    answer: models.OnboardingAnswer,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> None:
    """
    Permanently delete an answer row.

    This should be reserved for administrative correction or privacy
    workflows. Normal users should clear an answer instead.
    """

    onboarding_session = session_crud.get_session(
        db,
        answer.session_id,
    )

    if onboarding_session is None:
        raise ValueError(
            "the answer's onboarding session no longer exists"
        )

    _require_modifiable_session(onboarding_session)

    field = answer.field

    if field is None:
        field = db.get(
            models.OnboardingField,
            answer.field_id,
        )

    event_crud.create_event(
        db,
        event_type=models.EventType.ANSWER_UPDATED,
        session_id=onboarding_session.id,
        flow_id=onboarding_session.flow_id,
        flow_version_id=(
            onboarding_session.flow_version_id
        ),
        subject_type=onboarding_session.subject_type,
        subject_id=onboarding_session.subject_id,
        actor_id=actor_id,
        payload_json={
            "answer_id": answer.id,
            "field_id": answer.field_id,
            "field_key": answer.field_key,
            "action": "deleted",
            "previous_value": _event_safe_value(
                answer.value_json,
                sensitive=(
                    field.sensitive
                    if field is not None
                    else True
                ),
            ),
        },
        correlation_id=correlation_id,
        commit=False,
    )

    db.delete(answer)

    if commit:
        try:
            db.commit()

        except Exception:
            db.rollback()
            raise
    else:
        db.flush()


def get_answer_value_map(
    db: Session,
    session_id: str,
) -> dict[str, Any]:
    """
    Return answers as a field_key-to-value mapping.

    The conditions and validation services can use this directly.
    """

    answers = list_answers(
        db,
        session_id,
    )

    return {
        answer.field_key: answer.value_json
        for answer in answers
    }


def get_valid_answer_map(
    db: Session,
    session_id: str,
) -> dict[str, Any]:
    """
    Return only answers currently marked valid.
    """

    statement = select(
        models.OnboardingAnswer
    ).where(
        models.OnboardingAnswer.session_id == session_id,
        models.OnboardingAnswer.is_valid.is_(True),
    )

    answers = db.scalars(statement).all()

    return {
        answer.field_key: answer.value_json
        for answer in answers
    }


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
            "and its answers can no longer be modified"
        )


def _ensure_session_started(
    onboarding_session: models.OnboardingSession,
) -> None:
    """
    Automatically begin a session when its first answer is written.

    This changes the runtime state inside the caller's current transaction.
    The answer event remains the durable record of the triggering action.
    """

    if (
        onboarding_session.status
        == models.SessionStatus.NOT_STARTED
    ):
        onboarding_session.status = (
            models.SessionStatus.IN_PROGRESS
        )

        if onboarding_session.started_at is None:
            onboarding_session.started_at = utc_now()


def _event_safe_value(
    value: Any,
    *,
    sensitive: bool,
) -> Any:
    """
    Prevent sensitive answer values from entering the event payload.
    """

    if sensitive and value is not None:
        return {
            "redacted": True,
        }

    return value
