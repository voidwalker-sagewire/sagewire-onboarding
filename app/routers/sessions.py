from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.crud import answers as answer_crud
from app.crud import requirements as requirement_crud
from app.crud import sessions as session_crud
from app.database import get_db
from app.services import completion
from app.services import conditions
from app.services import validation


router = APIRouter(
    prefix="/sessions",
    tags=["Onboarding Sessions"],
)


@router.post(
    "",
    response_model=schemas.OnboardingSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    session_in: schemas.OnboardingSessionCreate,
    db: Session = Depends(get_db),
) -> models.OnboardingSession:
    """
    Create a new onboarding session.

    The session is permanently attached to one published, immutable flow
    version. Runtime requirement states are created from the requirement
    definitions belonging to that version.
    """

    try:
        return session_crud.create_session(
            db,
            session_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=schemas.OnboardingSessionListResponse,
)
def list_sessions(
    session_status: models.SessionStatus | None = Query(
        default=None,
        alias="status",
    ),
    subject_type: models.SubjectType | None = None,
    subject_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=255,
    ),
    flow_id: str | None = None,
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
) -> schemas.OnboardingSessionListResponse:
    """
    List onboarding sessions with optional filters.
    """

    items = session_crud.list_sessions(
        db,
        status=session_status,
        subject_type=subject_type,
        subject_id=subject_id,
        flow_id=flow_id,
        limit=limit,
        offset=offset,
    )

    total = session_crud.count_sessions(
        db,
        status=session_status,
        subject_type=subject_type,
        subject_id=subject_id,
        flow_id=flow_id,
    )

    return schemas.OnboardingSessionListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{session_identifier}",
    response_model=schemas.OnboardingSessionResponse,
)
def get_session(
    session_identifier: str,
    db: Session = Depends(get_db),
) -> models.OnboardingSession:
    """
    Retrieve a session by UUID or stable session key.
    """

    return _resolve_session_or_404(
        db,
        session_identifier,
    )


@router.patch(
    "/{session_identifier}",
    response_model=schemas.OnboardingSessionResponse,
)
def update_session(
    session_identifier: str,
    session_in: schemas.OnboardingSessionUpdate,
    db: Session = Depends(get_db),
) -> models.OnboardingSession:
    """
    Update mutable session metadata.

    Completed and abandoned sessions remain immutable.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        return session_crud.update_session(
            db,
            onboarding_session,
            session_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{session_identifier}/start",
    response_model=schemas.OnboardingSessionResponse,
)
def start_session(
    session_identifier: str,
    action_in: schemas.SessionActionRequest | None = None,
    db: Session = Depends(get_db),
) -> models.OnboardingSession:
    """
    Start a session and resolve its first currently visible step.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        answer_map = answer_crud.get_answer_value_map(
            db,
            onboarding_session.id,
        )

        flow_version = (
            session_crud.get_session_flow_version(
                db,
                onboarding_session,
                include_definition=True,
            )
        )

        if flow_version is None:
            raise ValueError(
                "the session's flow version no longer exists"
            )

        first_step = conditions.get_first_visible_step(
            flow_version,
            answer_map,
        )

        return session_crud.start_session(
            db,
            onboarding_session,
            current_step_key=(
                first_step.step_key
                if first_step is not None
                else None
            ),
            actor_id=(
                action_in.actor_id
                if action_in is not None
                else None
            ),
            correlation_id=(
                action_in.correlation_id
                if action_in is not None
                else None
            ),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{session_identifier}/abandon",
    response_model=schemas.OnboardingSessionResponse,
)
def abandon_session(
    session_identifier: str,
    action_in: schemas.SessionAbandonRequest | None = None,
    db: Session = Depends(get_db),
) -> models.OnboardingSession:
    """
    Abandon a noncompleted onboarding session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        return session_crud.abandon_session(
            db,
            onboarding_session,
            actor_id=(
                action_in.actor_id
                if action_in is not None
                else None
            ),
            correlation_id=(
                action_in.correlation_id
                if action_in is not None
                else None
            ),
            payload_json={
                "reason": (
                    action_in.reason
                    if action_in is not None
                    else None
                )
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{session_identifier}/definition",
    response_model=schemas.OnboardingFlowDefinitionResponse,
)
def get_session_definition(
    session_identifier: str,
    db: Session = Depends(get_db),
) -> Any:
    """
    Retrieve the immutable flow definition assigned to this session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    flow_version = session_crud.get_session_flow_version(
        db,
        onboarding_session,
        include_definition=True,
    )

    if flow_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "the flow version assigned to this "
                "session was not found"
            ),
        )

    from app.crud import flows as flow_crud

    return flow_crud.build_flow_definition(
        flow_version
    )


@router.get(
    "/{session_identifier}/state",
    response_model=schemas.OnboardingSessionStateResponse,
)
def get_session_state(
    session_identifier: str,
    db: Session = Depends(get_db),
) -> schemas.OnboardingSessionStateResponse:
    """
    Return a complete application-facing runtime state.

    The response combines:

    - session metadata
    - assigned flow definition
    - submitted answers
    - requirement states
    - visibility state
    - completion readiness
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    flow_version = session_crud.get_session_flow_version(
        db,
        onboarding_session,
        include_definition=True,
    )

    if flow_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "the flow version assigned to this "
                "session was not found"
            ),
        )

    answer_rows = answer_crud.list_answers(
        db,
        onboarding_session.id,
    )

    answer_map = {
        answer.field_key: answer.value_json
        for answer in answer_rows
    }

    requirement_states = (
        requirement_crud.list_session_requirements(
            db,
            onboarding_session.id,
        )
    )

    visibility_map = conditions.build_visibility_map(
        flow_version,
        answer_map,
    )

    completion_result = completion.evaluate_completion(
        db,
        onboarding_session,
        persist_validation=False,
        commit=False,
    )

    return schemas.OnboardingSessionStateResponse(
        session=onboarding_session,
        answers=answer_rows,
        requirements=requirement_states,
        visibility=visibility_map,
        completion=completion_result.to_dict(),
    )


@router.get(
    "/{session_identifier}/answers",
    response_model=schemas.OnboardingAnswerListResponse,
)
def list_answers(
    session_identifier: str,
    limit: int = Query(
        default=500,
        ge=1,
        le=1000,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> schemas.OnboardingAnswerListResponse:
    """
    List stored answers for one session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    items = answer_crud.list_answers(
        db,
        onboarding_session.id,
        limit=limit,
        offset=offset,
    )

    return schemas.OnboardingAnswerListResponse(
        items=items,
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.put(
    "/{session_identifier}/answers/{field_key}",
    response_model=schemas.OnboardingAnswerResponse,
)
def write_answer(
    session_identifier: str,
    field_key: str,
    answer_in: schemas.OnboardingAnswerWrite,
    db: Session = Depends(get_db),
) -> models.OnboardingAnswer:
    """
    Create or replace one answer by stable field key.

    Persistence and validation remain separate operations. The submitted
    value is stored first, then validated against the immutable field
    definition assigned to the session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    if (
        answer_in.field_key is not None
        and answer_in.field_key != field_key
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "the route field key and request field key "
                "do not match"
            ),
        )

    try:
        answer = answer_crud.write_answer(
            db,
            onboarding_session,
            field_key,
            answer_in,
            commit=False,
        )

        onboarding_field = (
            answer_crud.get_field_for_session(
                db,
                onboarding_session,
                field_key=field_key,
            )
        )

        if onboarding_field is None:
            raise ValueError(
                f"field '{field_key}' does not belong "
                "to this onboarding session"
            )

        answer_map = answer_crud.get_answer_value_map(
            db,
            onboarding_session.id,
        )

        flow_version = (
            session_crud.get_session_flow_version(
                db,
                onboarding_session,
                include_definition=True,
            )
        )

        if flow_version is None:
            raise ValueError(
                "the session's flow version no longer exists"
            )

        step_visible = True

        if onboarding_field.step is not None:
            step_visible = conditions.is_step_visible(
                onboarding_field.step,
                answer_map,
            )

        field_visible = conditions.is_field_visible(
            onboarding_field,
            answer_map,
            step_visible=step_visible,
        )

        field_result = validation.validate_field_value(
            onboarding_field,
            answer.value_json,
            visible=field_visible,
        )

        answer.value_json = (
            field_result.normalized_value
        )

        answer_crud.set_answer_validation(
            db,
            answer,
            is_valid=field_result.valid,
            validation_errors=[
                issue.to_dict()
                for issue in field_result.issues
            ],
            commit=False,
        )

        completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=True,
            commit=False,
        )

        db.commit()
        db.refresh(answer)

        return answer

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.put(
    "/{session_identifier}/answers",
    response_model=schemas.OnboardingAnswerBulkResponse,
)
def write_answers_bulk(
    session_identifier: str,
    bulk_in: schemas.OnboardingAnswerBulkWrite,
    db: Session = Depends(get_db),
) -> schemas.OnboardingAnswerBulkResponse:
    """
    Create or replace multiple answers atomically.

    Every submitted answer must belong to the immutable flow version
    assigned to the session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        answers = answer_crud.write_answers_bulk(
            db,
            onboarding_session,
            bulk_in,
            commit=False,
        )

        validation_result = validation.validate_session(
            db,
            onboarding_session,
            persist_results=True,
            commit=False,
        )

        completion_result = completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=True,
            commit=False,
        )

        db.commit()

        for answer in answers:
            db.refresh(answer)

        return schemas.OnboardingAnswerBulkResponse(
            items=answers,
            total=len(answers),
            validation=validation_result.to_dict(),
            completion=completion_result.to_dict(),
        )

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.delete(
    "/{session_identifier}/answers/{field_key}",
    response_model=schemas.OnboardingAnswerResponse,
)
def clear_answer(
    session_identifier: str,
    field_key: str,
    action_in: schemas.SessionActionRequest | None = None,
    db: Session = Depends(get_db),
) -> models.OnboardingAnswer:
    """
    Clear one answer while preserving its row and audit history.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        answer = answer_crud.clear_answer(
            db,
            onboarding_session,
            field_key,
            actor_id=(
                action_in.actor_id
                if action_in is not None
                else None
            ),
            correlation_id=(
                action_in.correlation_id
                if action_in is not None
                else None
            ),
            commit=False,
        )

        completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=True,
            commit=False,
        )

        db.commit()
        db.refresh(answer)

        return answer

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.post(
    "/{session_identifier}/validate",
    response_model=schemas.SessionValidationResponse,
)
def validate_session(
    session_identifier: str,
    db: Session = Depends(get_db),
) -> Any:
    """
    Validate every currently visible field in the session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        result = validation.validate_session(
            db,
            onboarding_session,
            persist_results=True,
            commit=True,
        )

        return result.to_dict()

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{session_identifier}/validate-current-step",
    response_model=schemas.StepValidationResponse,
)
def validate_current_step(
    session_identifier: str,
    db: Session = Depends(get_db),
) -> Any:
    """
    Validate only the session's current visible step.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        result = validation.validate_current_step(
            db,
            onboarding_session,
            persist_results=True,
            commit=True,
        )

        return result.to_dict()

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{session_identifier}/completion",
    response_model=schemas.CompletionEvaluationResponse,
)
def evaluate_session_completion(
    session_identifier: str,
    persist_validation: bool = Query(
        default=True,
    ),
    db: Session = Depends(get_db),
) -> Any:
    """
    Evaluate progress and determine whether the session can be completed.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        result = completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=persist_validation,
            commit=True,
        )

        return result.to_dict()

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{session_identifier}/advance",
    response_model=schemas.CompletionEvaluationResponse,
)
def advance_session(
    session_identifier: str,
    action_in: schemas.SessionActionRequest | None = None,
    db: Session = Depends(get_db),
) -> Any:
    """
    Validate the current step and move to the next visible step.

    When no later step exists, the service attempts to complete the
    session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        result = completion.advance_session(
            db,
            onboarding_session,
            actor_id=(
                action_in.actor_id
                if action_in is not None
                else None
            ),
            correlation_id=(
                action_in.correlation_id
                if action_in is not None
                else None
            ),
        )

        return result.to_dict()

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{session_identifier}/retreat",
    response_model=schemas.CompletionEvaluationResponse,
)
def retreat_session(
    session_identifier: str,
    action_in: schemas.SessionActionRequest | None = None,
    db: Session = Depends(get_db),
) -> Any:
    """
    Move to the previous currently visible step.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        result = completion.retreat_session(
            db,
            onboarding_session,
            actor_id=(
                action_in.actor_id
                if action_in is not None
                else None
            ),
            correlation_id=(
                action_in.correlation_id
                if action_in is not None
                else None
            ),
        )

        return result.to_dict()

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{session_identifier}/complete",
    response_model=schemas.CompletionEvaluationResponse,
)
def complete_session(
    session_identifier: str,
    action_in: schemas.SessionActionRequest | None = None,
    db: Session = Depends(get_db),
) -> Any:
    """
    Complete the session when every visible field and required requirement
    is ready.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        result = completion.complete_session(
            db,
            onboarding_session,
            actor_id=(
                action_in.actor_id
                if action_in is not None
                else None
            ),
            correlation_id=(
                action_in.correlation_id
                if action_in is not None
                else None
            ),
        )

        return result.to_dict()

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{session_identifier}/requirements",
    response_model=schemas.SessionRequirementListResponse,
)
def list_session_requirements(
    session_identifier: str,
    requirement_status: models.RequirementStatus | None = Query(
        default=None,
        alias="status",
    ),
    required_only: bool = False,
    limit: int = Query(
        default=500,
        ge=1,
        le=1000,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> schemas.SessionRequirementListResponse:
    """
    List runtime requirement states for a session.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    items = requirement_crud.list_session_requirements(
        db,
        onboarding_session.id,
        status=requirement_status,
        required_only=required_only,
        limit=limit,
        offset=offset,
    )

    total = requirement_crud.count_session_requirements(
        db,
        onboarding_session.id,
        status=requirement_status,
        required_only=required_only,
    )

    return schemas.SessionRequirementListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/{session_identifier}/requirements/{requirement_key}",
    response_model=schemas.SessionRequirementResponse,
)
def update_session_requirement(
    session_identifier: str,
    requirement_key: str,
    requirement_in: schemas.SessionRequirementUpdate,
    db: Session = Depends(get_db),
) -> models.OnboardingSessionRequirement:
    """
    Update one runtime requirement state.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        session_requirement = (
            requirement_crud.update_session_requirement(
                db,
                onboarding_session,
                requirement_key,
                requirement_in,
                commit=False,
            )
        )

        completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=False,
            commit=False,
        )

        db.commit()
        db.refresh(session_requirement)

        return session_requirement

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.post(
    "/{session_identifier}/requirements/{requirement_key}/satisfy",
    response_model=schemas.SessionRequirementResponse,
)
def satisfy_requirement(
    session_identifier: str,
    requirement_key: str,
    satisfy_in: schemas.SessionRequirementSatisfy,
    db: Session = Depends(get_db),
) -> models.OnboardingSessionRequirement:
    """
    Mark one runtime requirement satisfied.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        session_requirement = (
            requirement_crud.satisfy_requirement(
                db,
                onboarding_session,
                requirement_key,
                satisfied_by=satisfy_in.satisfied_by,
                external_reference=(
                    satisfy_in.external_reference
                ),
                details_json=satisfy_in.details_json,
                correlation_id=(
                    satisfy_in.correlation_id
                ),
                commit=False,
            )
        )

        completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=False,
            commit=False,
        )

        db.commit()
        db.refresh(session_requirement)

        return session_requirement

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.post(
    "/{session_identifier}/requirements/{requirement_key}/reset",
    response_model=schemas.SessionRequirementResponse,
)
def reset_requirement(
    session_identifier: str,
    requirement_key: str,
    reset_in: schemas.SessionRequirementReset | None = None,
    db: Session = Depends(get_db),
) -> models.OnboardingSessionRequirement:
    """
    Reset one runtime requirement to its pending state.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        session_requirement = (
            requirement_crud.reset_requirement(
                db,
                onboarding_session,
                requirement_key,
                actor_id=(
                    reset_in.actor_id
                    if reset_in is not None
                    else None
                ),
                details_json=(
                    reset_in.details_json
                    if reset_in is not None
                    else None
                ),
                correlation_id=(
                    reset_in.correlation_id
                    if reset_in is not None
                    else None
                ),
                commit=False,
            )
        )

        completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=False,
            commit=False,
        )

        db.commit()
        db.refresh(session_requirement)

        return session_requirement

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.post(
    "/{session_identifier}/requirements/{requirement_key}/waive",
    response_model=schemas.SessionRequirementResponse,
)
def waive_requirement(
    session_identifier: str,
    requirement_key: str,
    waive_in: schemas.SessionRequirementWaive,
    db: Session = Depends(get_db),
) -> models.OnboardingSessionRequirement:
    """
    Waive one requirement when the RequirementStatus enum supports WAIVED.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        session_requirement = (
            requirement_crud.waive_requirement(
                db,
                onboarding_session,
                requirement_key,
                waived_by=waive_in.waived_by,
                reason=waive_in.reason,
                correlation_id=(
                    waive_in.correlation_id
                ),
                commit=False,
            )
        )

        completion.evaluate_completion(
            db,
            onboarding_session,
            persist_validation=False,
            commit=False,
        )

        db.commit()
        db.refresh(session_requirement)

        return session_requirement

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.post(
    "/{session_identifier}/requirements/sync",
    response_model=schemas.SessionRequirementSyncResponse,
)
def sync_session_requirements(
    session_identifier: str,
    db: Session = Depends(get_db),
) -> schemas.SessionRequirementSyncResponse:
    """
    Repair missing runtime requirement rows for the assigned flow version.
    """

    onboarding_session = _resolve_session_or_404(
        db,
        session_identifier,
    )

    try:
        created = (
            requirement_crud.sync_session_requirement_states(
                db,
                onboarding_session,
                commit=True,
            )
        )

        return schemas.SessionRequirementSyncResponse(
            created=created,
            created_count=len(created),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


def _resolve_session_or_404(
    db: Session,
    session_identifier: str,
) -> models.OnboardingSession:
    onboarding_session = session_crud.resolve_session(
        db,
        session_identifier,
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
