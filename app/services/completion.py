from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.crud import answers as answer_crud
from app.crud import requirements as requirement_crud
from app.crud import sessions as session_crud
from app.services import conditions
from app.services import validation


@dataclass(slots=True)
class RequirementCompletionResult:
    """
    Completion state for one currently visible requirement.
    """

    requirement_key: str
    required: bool
    visible: bool
    status: str
    satisfied: bool
    blocking: bool
    title: str | None = None
    details: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_key": self.requirement_key,
            "title": self.title,
            "required": self.required,
            "visible": self.visible,
            "status": self.status,
            "satisfied": self.satisfied,
            "blocking": self.blocking,
            "details": self.details,
        }


@dataclass(slots=True)
class StepCompletionResult:
    """
    Completion state for one currently visible onboarding step.
    """

    step_key: str
    title: str | None
    visible: bool
    completed: bool
    completed_field_count: int
    total_field_count: int
    progress_percent: int
    blocking_field_keys: list[str] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_key": self.step_key,
            "title": self.title,
            "visible": self.visible,
            "completed": self.completed,
            "completed_field_count": (
                self.completed_field_count
            ),
            "total_field_count": self.total_field_count,
            "progress_percent": self.progress_percent,
            "blocking_field_keys": (
                self.blocking_field_keys
            ),
        }


@dataclass(slots=True)
class CompletionEvaluation:
    """
    Complete readiness result for one onboarding session.
    """

    session_id: str
    session_key: str
    session_status: str
    can_complete: bool
    fields_valid: bool
    requirements_satisfied: bool
    completed_field_count: int
    total_field_count: int
    satisfied_requirement_count: int
    total_required_requirement_count: int
    progress_percent: int
    current_step_key: str | None
    blocking_field_keys: list[str] = field(
        default_factory=list
    )
    blocking_requirement_keys: list[str] = field(
        default_factory=list
    )
    visible_step_keys: list[str] = field(
        default_factory=list
    )
    step_results: list[StepCompletionResult] = field(
        default_factory=list
    )
    requirement_results: list[
        RequirementCompletionResult
    ] = field(default_factory=list)
    validation_result: (
        validation.SessionValidationResult | None
    ) = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_key": self.session_key,
            "session_status": self.session_status,
            "can_complete": self.can_complete,
            "fields_valid": self.fields_valid,
            "requirements_satisfied": (
                self.requirements_satisfied
            ),
            "completed_field_count": (
                self.completed_field_count
            ),
            "total_field_count": self.total_field_count,
            "satisfied_requirement_count": (
                self.satisfied_requirement_count
            ),
            "total_required_requirement_count": (
                self.total_required_requirement_count
            ),
            "progress_percent": self.progress_percent,
            "current_step_key": self.current_step_key,
            "blocking_field_keys": (
                self.blocking_field_keys
            ),
            "blocking_requirement_keys": (
                self.blocking_requirement_keys
            ),
            "visible_step_keys": self.visible_step_keys,
            "step_results": [
                result.to_dict()
                for result in self.step_results
            ],
            "requirement_results": [
                result.to_dict()
                for result in self.requirement_results
            ],
            "validation": (
                self.validation_result.to_dict()
                if self.validation_result is not None
                else None
            ),
        }


def evaluate_completion(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    persist_validation: bool = True,
    commit: bool = True,
) -> CompletionEvaluation:
    """
    Evaluate whether a session is ready for completion.

    Completion requires:

    - every visible field to be valid
    - every visible required field to be complete
    - every visible required requirement to be satisfied
      or waived
    - the session to remain nonterminal

    Hidden fields and hidden requirements do not block completion.
    """

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

    answer_rows = answer_crud.list_answers(
        db,
        onboarding_session.id,
    )

    answer_map = {
        answer.field_key: answer.value_json
        for answer in answer_rows
    }

    validation_result = validation.validate_session(
        db,
        onboarding_session,
        persist_results=persist_validation,
        commit=False,
    )

    visible_steps = conditions.list_visible_steps(
        flow_version,
        answer_map,
    )

    visible_step_keys = [
        step.step_key
        for step in visible_steps
    ]

    field_results_by_key = {
        result.field_key: result
        for result in validation_result.field_results
    }

    step_results = _build_step_results(
        visible_steps=visible_steps,
        field_results_by_key=field_results_by_key,
    )

    completed_field_count = sum(
        result.completed_field_count
        for result in step_results
    )

    total_field_count = sum(
        result.total_field_count
        for result in step_results
    )

    blocking_field_keys = [
        field_key
        for step_result in step_results
        for field_key
        in step_result.blocking_field_keys
    ]

    fields_valid = not blocking_field_keys

    session_requirement_states = (
        requirement_crud.list_session_requirements(
            db,
            onboarding_session.id,
        )
    )

    states_by_key = {
        state.requirement_key: state
        for state in session_requirement_states
    }

    visible_requirements = (
        conditions.list_visible_requirements(
            flow_version,
            answer_map,
        )
    )

    requirement_results = (
        _build_requirement_results(
            visible_requirements=(
                visible_requirements
            ),
            states_by_key=states_by_key,
        )
    )

    required_requirement_results = [
        result
        for result in requirement_results
        if result.required and result.visible
    ]

    satisfied_requirement_count = sum(
        1
        for result in required_requirement_results
        if result.satisfied
    )

    total_required_requirement_count = len(
        required_requirement_results
    )

    blocking_requirement_keys = [
        result.requirement_key
        for result in required_requirement_results
        if result.blocking
    ]

    requirements_satisfied = (
        not blocking_requirement_keys
    )

    can_complete = (
        fields_valid
        and requirements_satisfied
        and onboarding_session.status
        not in {
            models.SessionStatus.COMPLETED,
            models.SessionStatus.ABANDONED,
        }
    )

    progress_percent = calculate_overall_progress(
        completed_field_count=completed_field_count,
        total_field_count=total_field_count,
        satisfied_requirement_count=(
            satisfied_requirement_count
        ),
        total_required_requirement_count=(
            total_required_requirement_count
        ),
    )

    resolved_current_step = (
        conditions.resolve_current_visible_step(
            flow_version,
            answer_map,
            current_step_key=(
                onboarding_session.current_step_key
            ),
        )
    )

    current_step_key = (
        resolved_current_step.step_key
        if resolved_current_step is not None
        else None
    )

    if (
        onboarding_session.status
        not in {
            models.SessionStatus.COMPLETED,
            models.SessionStatus.ABANDONED,
        }
    ):
        runtime_status = _resolve_runtime_status(
            onboarding_session=onboarding_session,
            fields_valid=fields_valid,
            requirements_satisfied=(
                requirements_satisfied
            ),
        )

        session_crud.set_session_runtime_state(
            db,
            onboarding_session,
            status=runtime_status,
            current_step_key=current_step_key,
            progress_percent=progress_percent,
            payload_json={
                "action": "completion_evaluated",
                "fields_valid": fields_valid,
                "requirements_satisfied": (
                    requirements_satisfied
                ),
                "blocking_field_keys": (
                    blocking_field_keys
                ),
                "blocking_requirement_keys": (
                    blocking_requirement_keys
                ),
            },
            commit=False,
        )

    result = CompletionEvaluation(
        session_id=onboarding_session.id,
        session_key=onboarding_session.session_key,
        session_status=(
            onboarding_session.status.value
        ),
        can_complete=can_complete,
        fields_valid=fields_valid,
        requirements_satisfied=(
            requirements_satisfied
        ),
        completed_field_count=completed_field_count,
        total_field_count=total_field_count,
        satisfied_requirement_count=(
            satisfied_requirement_count
        ),
        total_required_requirement_count=(
            total_required_requirement_count
        ),
        progress_percent=progress_percent,
        current_step_key=current_step_key,
        blocking_field_keys=blocking_field_keys,
        blocking_requirement_keys=(
            blocking_requirement_keys
        ),
        visible_step_keys=visible_step_keys,
        step_results=step_results,
        requirement_results=requirement_results,
        validation_result=validation_result,
    )

    if commit:
        try:
            db.commit()
            db.refresh(onboarding_session)
        except Exception:
            db.rollback()
            raise

    return result


def complete_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> CompletionEvaluation:
    """
    Validate and complete a session atomically.

    Raises ValueError when any visible field or required requirement still
    blocks completion.
    """

    if (
        onboarding_session.status
        == models.SessionStatus.COMPLETED
    ):
        return evaluate_completion(
            db,
            onboarding_session,
            persist_validation=False,
            commit=False,
        )

    if (
        onboarding_session.status
        == models.SessionStatus.ABANDONED
    ):
        raise ValueError(
            "an abandoned session cannot be completed"
        )

    try:
        evaluation = evaluate_completion(
            db,
            onboarding_session,
            persist_validation=True,
            commit=False,
        )

        if not evaluation.can_complete:
            raise ValueError(
                _completion_failure_message(
                    evaluation
                )
            )

        session_crud.mark_session_completed(
            db,
            onboarding_session,
            actor_id=actor_id,
            correlation_id=correlation_id,
            payload_json={
                "completed_field_count": (
                    evaluation.completed_field_count
                ),
                "total_field_count": (
                    evaluation.total_field_count
                ),
                "satisfied_requirement_count": (
                    evaluation
                    .satisfied_requirement_count
                ),
                "total_required_requirement_count": (
                    evaluation
                    .total_required_requirement_count
                ),
                "visible_step_keys": (
                    evaluation.visible_step_keys
                ),
            },
            commit=False,
        )

        db.commit()
        db.refresh(onboarding_session)

    except Exception:
        db.rollback()
        raise

    evaluation.session_status = (
        onboarding_session.status.value
    )
    evaluation.can_complete = True
    evaluation.progress_percent = 100

    return evaluation


def advance_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> CompletionEvaluation:
    """
    Validate the current step and advance to the next visible step.

    If no later visible step exists, the full session is evaluated. The
    session is completed only when every field and requirement is ready.
    Otherwise it remains blocked or in progress.
    """

    _require_modifiable_session(
        onboarding_session
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

    answer_map = answer_crud.get_answer_value_map(
        db,
        onboarding_session.id,
    )

    current_step = (
        conditions.resolve_current_visible_step(
            flow_version,
            answer_map,
            current_step_key=(
                onboarding_session.current_step_key
            ),
        )
    )

    if current_step is None:
        return complete_session(
            db,
            onboarding_session,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    step_validation = validation.validate_step(
        flow_version,
        current_step,
        answer_map,
    )

    blocking_fields = [
        result.field_key
        for result in step_validation.field_results
        if not validation.is_session_field_complete(
            result
        )
    ]

    if blocking_fields:
        raise ValueError(
            "the current step cannot be advanced "
            "because these fields are incomplete or "
            f"invalid: {', '.join(blocking_fields)}"
        )

    next_step = conditions.get_next_visible_step(
        flow_version,
        answer_map,
        current_step_key=current_step.step_key,
    )

    if next_step is None:
        return complete_session(
            db,
            onboarding_session,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    evaluation = evaluate_completion(
        db,
        onboarding_session,
        persist_validation=True,
        commit=False,
    )

    try:
        session_crud.set_session_runtime_state(
            db,
            onboarding_session,
            status=models.SessionStatus.IN_PROGRESS,
            current_step_key=next_step.step_key,
            progress_percent=(
                evaluation.progress_percent
            ),
            actor_id=actor_id,
            correlation_id=correlation_id,
            payload_json={
                "action": "advanced",
                "from_step_key": (
                    current_step.step_key
                ),
                "to_step_key": next_step.step_key,
            },
            commit=False,
        )

        db.commit()
        db.refresh(onboarding_session)

    except Exception:
        db.rollback()
        raise

    evaluation.current_step_key = next_step.step_key
    evaluation.session_status = (
        onboarding_session.status.value
    )

    return evaluation


def retreat_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> CompletionEvaluation:
    """
    Move a session to its previous visible step.
    """

    _require_modifiable_session(
        onboarding_session
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

    answer_map = answer_crud.get_answer_value_map(
        db,
        onboarding_session.id,
    )

    current_step = (
        conditions.resolve_current_visible_step(
            flow_version,
            answer_map,
            current_step_key=(
                onboarding_session.current_step_key
            ),
        )
    )

    if current_step is None:
        previous_step = (
            conditions.get_first_visible_step(
                flow_version,
                answer_map,
            )
        )
    else:
        previous_step = (
            conditions.get_previous_visible_step(
                flow_version,
                answer_map,
                current_step_key=current_step.step_key,
            )
        )

    if previous_step is None:
        raise ValueError(
            "the session is already at its first "
            "visible step"
        )

    evaluation = evaluate_completion(
        db,
        onboarding_session,
        persist_validation=False,
        commit=False,
    )

    try:
        session_crud.set_session_runtime_state(
            db,
            onboarding_session,
            status=models.SessionStatus.IN_PROGRESS,
            current_step_key=previous_step.step_key,
            progress_percent=(
                evaluation.progress_percent
            ),
            actor_id=actor_id,
            correlation_id=correlation_id,
            payload_json={
                "action": "retreated",
                "from_step_key": (
                    current_step.step_key
                    if current_step is not None
                    else None
                ),
                "to_step_key": previous_step.step_key,
            },
            commit=False,
        )

        db.commit()
        db.refresh(onboarding_session)

    except Exception:
        db.rollback()
        raise

    evaluation.current_step_key = (
        previous_step.step_key
    )
    evaluation.session_status = (
        onboarding_session.status.value
    )

    return evaluation


def calculate_overall_progress(
    *,
    completed_field_count: int,
    total_field_count: int,
    satisfied_requirement_count: int,
    total_required_requirement_count: int,
) -> int:
    """
    Calculate completion progress across fields and required requirements.

    Every visible field and visible required requirement receives equal
    weight.
    """

    completed_items = (
        completed_field_count
        + satisfied_requirement_count
    )

    total_items = (
        total_field_count
        + total_required_requirement_count
    )

    if total_items == 0:
        return 100

    return max(
        0,
        min(
            100,
            round(
                completed_items
                / total_items
                * 100
            ),
        ),
    )


def _build_step_results(
    *,
    visible_steps: list[models.OnboardingStep],
    field_results_by_key: dict[
        str,
        validation.FieldValidationResult,
    ],
) -> list[StepCompletionResult]:
    results: list[StepCompletionResult] = []

    for step in visible_steps:
        ordered_fields = sorted(
            step.fields,
            key=lambda item: (
                item.position,
                item.id,
            ),
        )

        visible_field_results = [
            field_results_by_key[field.field_key]
            for field in ordered_fields
            if field.field_key
            in field_results_by_key
            and field_results_by_key[
                field.field_key
            ].visible
        ]

        total_field_count = len(
            visible_field_results
        )

        completed_field_count = sum(
            1
            for result in visible_field_results
            if validation.is_session_field_complete(
                result
            )
        )

        blocking_field_keys = [
            result.field_key
            for result in visible_field_results
            if not validation.is_session_field_complete(
                result
            )
        ]

        progress_percent = (
            100
            if total_field_count == 0
            else round(
                completed_field_count
                / total_field_count
                * 100
            )
        )

        results.append(
            StepCompletionResult(
                step_key=step.step_key,
                title=getattr(
                    step,
                    "title",
                    None,
                ),
                visible=True,
                completed=not blocking_field_keys,
                completed_field_count=(
                    completed_field_count
                ),
                total_field_count=(
                    total_field_count
                ),
                progress_percent=progress_percent,
                blocking_field_keys=(
                    blocking_field_keys
                ),
            )
        )

    return results


def _build_requirement_results(
    *,
    visible_requirements: list[
        models.OnboardingRequirement
    ],
    states_by_key: dict[
        str,
        models.OnboardingSessionRequirement,
    ],
) -> list[RequirementCompletionResult]:
    results: list[
        RequirementCompletionResult
    ] = []

    for requirement in visible_requirements:
        state = states_by_key.get(
            requirement.requirement_key
        )

        if state is None:
            status_name = "MISSING"
            satisfied = False
            details = {
                "error": (
                    "runtime requirement state is missing"
                )
            }
        else:
            status_name = state.status.value
            satisfied = _is_nonblocking_status(
                state.status
            )
            details = dict(
                state.details_json or {}
            )

        blocking = (
            requirement.required
            and not satisfied
        )

        results.append(
            RequirementCompletionResult(
                requirement_key=(
                    requirement.requirement_key
                ),
                title=getattr(
                    requirement,
                    "title",
                    getattr(
                        requirement,
                        "label",
                        None,
                    ),
                ),
                required=requirement.required,
                visible=True,
                status=status_name,
                satisfied=satisfied,
                blocking=blocking,
                details=details,
            )
        )

    return results


def _is_nonblocking_status(
    status: models.RequirementStatus,
) -> bool:
    if (
        status
        == models.RequirementStatus.SATISFIED
    ):
        return True

    waived_status = (
        models.RequirementStatus.__members__.get(
            "WAIVED"
        )
    )

    return (
        waived_status is not None
        and status == waived_status
    )


def _resolve_runtime_status(
    *,
    onboarding_session: models.OnboardingSession,
    fields_valid: bool,
    requirements_satisfied: bool,
) -> models.SessionStatus:
    if (
        not fields_valid
        or not requirements_satisfied
    ):
        return models.SessionStatus.BLOCKED

    if (
        onboarding_session.status
        == models.SessionStatus.NOT_STARTED
    ):
        return models.SessionStatus.NOT_STARTED

    return models.SessionStatus.IN_PROGRESS


def _completion_failure_message(
    evaluation: CompletionEvaluation,
) -> str:
    parts: list[str] = []

    if evaluation.blocking_field_keys:
        parts.append(
            "incomplete or invalid fields: "
            + ", ".join(
                evaluation.blocking_field_keys
            )
        )

    if evaluation.blocking_requirement_keys:
        parts.append(
            "unsatisfied requirements: "
            + ", ".join(
                evaluation.blocking_requirement_keys
            )
        )

    if not parts:
        return (
            "the onboarding session is not ready "
            "for completion"
        )

    return (
        "the onboarding session cannot be "
        "completed because of "
        + "; ".join(parts)
    )


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
            "and can no longer be modified"
        )
