from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models
from app.crud import answers as answer_crud
from app.crud import sessions as session_crud
from app.services import conditions


EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

PHONE_PATTERN = re.compile(
    r"^\+?[0-9\s().-]{7,25}$"
)


@dataclass(slots=True)
class ValidationIssue:
    """
    One validation failure associated with a field or session.
    """

    code: str
    message: str
    field_key: str | None = None
    step_key: str | None = None
    value: Any = None
    details: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_key": self.field_key,
            "step_key": self.step_key,
            "value": self.value,
            "details": self.details,
        }


@dataclass(slots=True)
class FieldValidationResult:
    """
    Validation result for one onboarding field.
    """

    field_key: str
    step_key: str | None
    visible: bool
    required: bool
    valid: bool
    normalized_value: Any
    issues: list[ValidationIssue] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_key": self.field_key,
            "step_key": self.step_key,
            "visible": self.visible,
            "required": self.required,
            "valid": self.valid,
            "normalized_value": self.normalized_value,
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
        }


@dataclass(slots=True)
class StepValidationResult:
    """
    Validation result for one onboarding step.
    """

    step_key: str
    visible: bool
    valid: bool
    field_results: list[
        FieldValidationResult
    ] = field(default_factory=list)

    @property
    def issues(self) -> list[ValidationIssue]:
        return [
            issue
            for result in self.field_results
            for issue in result.issues
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_key": self.step_key,
            "visible": self.visible,
            "valid": self.valid,
            "field_results": [
                result.to_dict()
                for result in self.field_results
            ],
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
        }


@dataclass(slots=True)
class SessionValidationResult:
    """
    Validation result for a complete onboarding session.
    """

    session_id: str
    session_key: str
    valid: bool
    field_results: list[
        FieldValidationResult
    ] = field(default_factory=list)
    issues: list[ValidationIssue] = field(
        default_factory=list
    )
    visible_step_keys: list[str] = field(
        default_factory=list
    )
    visible_field_keys: list[str] = field(
        default_factory=list
    )

    @property
    def error_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_key": self.session_key,
            "valid": self.valid,
            "error_count": self.error_count,
            "visible_step_keys": self.visible_step_keys,
            "visible_field_keys": self.visible_field_keys,
            "field_results": [
                result.to_dict()
                for result in self.field_results
            ],
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
        }


def validate_field_value(
    onboarding_field: models.OnboardingField,
    value: Any,
    *,
    visible: bool = True,
) -> FieldValidationResult:
    """
    Validate one value against an onboarding field definition.

    Hidden fields are ignored and therefore considered valid.

    Validation includes:

    - required-value checks
    - field-type coercion
    - length limits
    - numeric limits
    - regular expressions
    - allowed option values
    - date and datetime ranges
    - custom file-reference constraints
    """

    step_key = (
        onboarding_field.step.step_key
        if onboarding_field.step is not None
        else None
    )

    if not visible:
        return FieldValidationResult(
            field_key=onboarding_field.field_key,
            step_key=step_key,
            visible=False,
            required=False,
            valid=True,
            normalized_value=value,
            issues=[],
        )

    issues: list[ValidationIssue] = []

    if conditions.is_empty_value(value):
        if onboarding_field.required:
            issues.append(
                _issue(
                    code="REQUIRED",
                    message=(
                        f"'{onboarding_field.label}' "
                        "is required."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )

        return FieldValidationResult(
            field_key=onboarding_field.field_key,
            step_key=step_key,
            visible=True,
            required=onboarding_field.required,
            valid=not issues,
            normalized_value=None,
            issues=issues,
        )

    try:
        normalized_value = normalize_field_value(
            onboarding_field,
            value,
        )
    except ValueError as exc:
        issues.append(
            _issue(
                code="INVALID_TYPE",
                message=str(exc),
                onboarding_field=onboarding_field,
                value=value,
            )
        )

        return FieldValidationResult(
            field_key=onboarding_field.field_key,
            step_key=step_key,
            visible=True,
            required=onboarding_field.required,
            valid=False,
            normalized_value=value,
            issues=issues,
        )

    rules = _normalize_validation_rules(
        onboarding_field.validation_json
    )

    issues.extend(
        _validate_common_rules(
            onboarding_field,
            normalized_value,
            rules,
        )
    )

    issues.extend(
        _validate_type_specific_rules(
            onboarding_field,
            normalized_value,
            rules,
        )
    )

    return FieldValidationResult(
        field_key=onboarding_field.field_key,
        step_key=step_key,
        visible=True,
        required=onboarding_field.required,
        valid=not issues,
        normalized_value=normalized_value,
        issues=issues,
    )


def validate_step(
    flow_version: models.OnboardingFlowVersion,
    step: models.OnboardingStep,
    answers: Mapping[str, Any],
) -> StepValidationResult:
    """
    Validate every currently visible field in one step.
    """

    step_visible = conditions.is_step_visible(
        step,
        answers,
    )

    if not step_visible:
        return StepValidationResult(
            step_key=step.step_key,
            visible=False,
            valid=True,
            field_results=[],
        )

    field_results: list[
        FieldValidationResult
    ] = []

    ordered_fields = sorted(
        step.fields,
        key=lambda item: (
            item.position,
            item.id,
        ),
    )

    for onboarding_field in ordered_fields:
        field_visible = conditions.is_field_visible(
            onboarding_field,
            answers,
            step_visible=True,
        )

        result = validate_field_value(
            onboarding_field,
            answers.get(
                onboarding_field.field_key
            ),
            visible=field_visible,
        )

        field_results.append(result)

    return StepValidationResult(
        step_key=step.step_key,
        visible=True,
        valid=all(
            result.valid
            for result in field_results
        ),
        field_results=field_results,
    )


def validate_session(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    persist_results: bool = True,
    commit: bool = True,
) -> SessionValidationResult:
    """
    Validate all currently visible fields in a session.

    Existing answer rows receive their current validation state when
    persist_results=True.

    Missing required answers appear in the returned validation result even
    though no answer row exists to update.
    """

    flow_version = (
        session_crud.get_session_flow_version(
            db,
            onboarding_session,
            include_definition=True,
        )
    )

    if flow_version is None:
        issue = ValidationIssue(
            code="FLOW_VERSION_NOT_FOUND",
            message=(
                "The session's flow version "
                "could not be found."
            ),
        )

        return SessionValidationResult(
            session_id=onboarding_session.id,
            session_key=(
                onboarding_session.session_key
            ),
            valid=False,
            issues=[issue],
        )

    answer_rows = answer_crud.list_answers(
        db,
        onboarding_session.id,
    )

    answer_map = {
        answer.field_key: answer.value_json
        for answer in answer_rows
    }

    answers_by_field_key = {
        answer.field_key: answer
        for answer in answer_rows
    }

    visible_steps = conditions.list_visible_steps(
        flow_version,
        answer_map,
    )

    visible_step_keys = [
        step.step_key
        for step in visible_steps
    ]

    field_results: list[
        FieldValidationResult
    ] = []

    visible_field_keys: list[str] = []

    for step in visible_steps:
        step_result = validate_step(
            flow_version,
            step,
            answer_map,
        )

        for result in step_result.field_results:
            field_results.append(result)

            if result.visible:
                visible_field_keys.append(
                    result.field_key
                )

            if not persist_results:
                continue

            answer = answers_by_field_key.get(
                result.field_key
            )

            if answer is None:
                continue

            answer_crud.set_answer_validation(
                db,
                answer,
                is_valid=result.valid,
                validation_errors=[
                    issue.to_dict()
                    for issue in result.issues
                ],
                commit=False,
            )

    if persist_results:
        hidden_answer_keys = (
            set(answers_by_field_key)
            - set(visible_field_keys)
        )

        for field_key in hidden_answer_keys:
            answer_crud.set_answer_validation(
                db,
                answers_by_field_key[field_key],
                is_valid=True,
                validation_errors=[],
                commit=False,
            )

    issues = [
        issue
        for result in field_results
        for issue in result.issues
    ]

    validation_result = SessionValidationResult(
        session_id=onboarding_session.id,
        session_key=(
            onboarding_session.session_key
        ),
        valid=not issues,
        field_results=field_results,
        issues=issues,
        visible_step_keys=visible_step_keys,
        visible_field_keys=visible_field_keys,
    )

    if persist_results and commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return validation_result


def validate_current_step(
    db: Session,
    onboarding_session: models.OnboardingSession,
    *,
    persist_results: bool = True,
    commit: bool = True,
) -> StepValidationResult:
    """
    Validate only the session's current visible step.
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
        return StepValidationResult(
            step_key=(
                onboarding_session.current_step_key
                or ""
            ),
            visible=False,
            valid=True,
            field_results=[],
        )

    result = validate_step(
        flow_version,
        current_step,
        answer_map,
    )

    if persist_results:
        answers_by_key = {
            answer.field_key: answer
            for answer in answer_rows
        }

        for field_result in result.field_results:
            answer = answers_by_key.get(
                field_result.field_key
            )

            if answer is None:
                continue

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

        if commit:
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise

    return result


def normalize_field_value(
    onboarding_field: models.OnboardingField,
    value: Any,
) -> Any:
    """
    Normalize a submitted value according to its field type.

    The returned value is JSON-compatible except for Decimal, date, and
    datetime values, which are converted to strings or primitive values.
    """

    field_type = onboarding_field.field_type

    if field_type in {
        models.FieldType.TEXT,
        models.FieldType.TEXTAREA,
        models.FieldType.EMAIL,
        models.FieldType.PHONE,
        models.FieldType.FILE_REFERENCE,
    }:
        if not isinstance(value, str):
            raise ValueError(
                f"'{onboarding_field.label}' "
                "must be text."
            )

        normalized = value.strip()

        if field_type == models.FieldType.EMAIL:
            normalized = normalized.casefold()

        return normalized

    if field_type == models.FieldType.INTEGER:
        return _normalize_integer(
            value,
            onboarding_field.label,
        )

    if field_type == models.FieldType.DECIMAL:
        decimal_value = _normalize_decimal(
            value,
            onboarding_field.label,
        )

        return str(decimal_value)

    if field_type == models.FieldType.BOOLEAN:
        return _normalize_boolean(
            value,
            onboarding_field.label,
        )

    if field_type == models.FieldType.DATE:
        return _normalize_date(
            value,
            onboarding_field.label,
        ).isoformat()

    if field_type == models.FieldType.DATETIME:
        return _normalize_datetime(
            value,
            onboarding_field.label,
        ).isoformat()

    if field_type == models.FieldType.SELECT:
        return _normalize_select_value(
            onboarding_field,
            value,
        )

    if field_type == models.FieldType.MULTISELECT:
        return _normalize_multiselect_value(
            onboarding_field,
            value,
        )

    raise ValueError(
        f"Unsupported field type "
        f"'{field_type.value}'."
    )


def is_session_field_complete(
    result: FieldValidationResult,
) -> bool:
    """
    Return whether a visible field is complete and valid.
    """

    if not result.visible:
        return True

    if not result.required:
        return result.valid

    return (
        result.valid
        and not conditions.is_empty_value(
            result.normalized_value
        )
    )


def calculate_field_completion(
    validation_result: SessionValidationResult,
) -> tuple[int, int, int]:
    """
    Return completed, total, and percentage for visible fields.

    Optional valid blank fields count as complete because they do not block
    the user.
    """

    visible_results = [
        result
        for result in validation_result.field_results
        if result.visible
    ]

    total = len(visible_results)

    if total == 0:
        return 0, 0, 100

    completed = sum(
        1
        for result in visible_results
        if is_session_field_complete(result)
    )

    percentage = round(
        completed / total * 100
    )

    return completed, total, percentage


def _validate_common_rules(
    onboarding_field: models.OnboardingField,
    value: Any,
    rules: Mapping[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    comparable_length = _value_length(value)

    minimum_length = _first_defined(
        rules,
        "min_length",
        "minimum_length",
    )

    maximum_length = _first_defined(
        rules,
        "max_length",
        "maximum_length",
    )

    if (
        minimum_length is not None
        and comparable_length is not None
        and comparable_length < int(minimum_length)
    ):
        issues.append(
            _issue(
                code="MIN_LENGTH",
                message=(
                    f"'{onboarding_field.label}' must "
                    f"contain at least "
                    f"{minimum_length} characters or items."
                ),
                onboarding_field=onboarding_field,
                value=value,
                details={
                    "minimum_length": minimum_length,
                    "actual_length": comparable_length,
                },
            )
        )

    if (
        maximum_length is not None
        and comparable_length is not None
        and comparable_length > int(maximum_length)
    ):
        issues.append(
            _issue(
                code="MAX_LENGTH",
                message=(
                    f"'{onboarding_field.label}' may "
                    f"contain no more than "
                    f"{maximum_length} characters or items."
                ),
                onboarding_field=onboarding_field,
                value=value,
                details={
                    "maximum_length": maximum_length,
                    "actual_length": comparable_length,
                },
            )
        )

    pattern = _first_defined(
        rules,
        "pattern",
        "regex",
    )

    if pattern is not None:
        if not isinstance(value, str):
            issues.append(
                _issue(
                    code="PATTERN_TYPE",
                    message=(
                        f"'{onboarding_field.label}' "
                        "cannot be checked against a "
                        "text pattern."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )
        else:
            try:
                matched = re.fullmatch(
                    str(pattern),
                    value,
                )
            except re.error as exc:
                issues.append(
                    _issue(
                        code="INVALID_PATTERN",
                        message=(
                            "The field definition contains "
                            "an invalid regular expression."
                        ),
                        onboarding_field=onboarding_field,
                        value=value,
                        details={
                            "pattern_error": str(exc),
                        },
                    )
                )
            else:
                if matched is None:
                    issues.append(
                        _issue(
                            code="PATTERN_MISMATCH",
                            message=(
                                f"'{onboarding_field.label}' "
                                "does not match the required "
                                "format."
                            ),
                            onboarding_field=onboarding_field,
                            value=value,
                        )
                    )

    return issues


def _validate_type_specific_rules(
    onboarding_field: models.OnboardingField,
    value: Any,
    rules: Mapping[str, Any],
) -> list[ValidationIssue]:
    field_type = onboarding_field.field_type
    issues: list[ValidationIssue] = []

    if field_type == models.FieldType.EMAIL:
        if not EMAIL_PATTERN.fullmatch(value):
            issues.append(
                _issue(
                    code="INVALID_EMAIL",
                    message=(
                        f"'{onboarding_field.label}' "
                        "must contain a valid email address."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )

    elif field_type == models.FieldType.PHONE:
        if not PHONE_PATTERN.fullmatch(value):
            issues.append(
                _issue(
                    code="INVALID_PHONE",
                    message=(
                        f"'{onboarding_field.label}' "
                        "must contain a valid phone number."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )

    elif field_type in {
        models.FieldType.INTEGER,
        models.FieldType.DECIMAL,
    }:
        issues.extend(
            _validate_numeric_rules(
                onboarding_field,
                value,
                rules,
            )
        )

    elif field_type in {
        models.FieldType.DATE,
        models.FieldType.DATETIME,
    }:
        issues.extend(
            _validate_temporal_rules(
                onboarding_field,
                value,
                rules,
            )
        )

    elif field_type == models.FieldType.FILE_REFERENCE:
        issues.extend(
            _validate_file_reference(
                onboarding_field,
                value,
                rules,
            )
        )

    elif field_type == models.FieldType.SELECT:
        if not _option_value_allowed(
            onboarding_field,
            value,
        ):
            issues.append(
                _issue(
                    code="INVALID_OPTION",
                    message=(
                        f"'{onboarding_field.label}' "
                        "contains an unsupported option."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )

    elif field_type == models.FieldType.MULTISELECT:
        invalid_values = [
            item
            for item in value
            if not _option_value_allowed(
                onboarding_field,
                item,
            )
        ]

        if invalid_values:
            issues.append(
                _issue(
                    code="INVALID_OPTIONS",
                    message=(
                        f"'{onboarding_field.label}' "
                        "contains one or more unsupported "
                        "options."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                    details={
                        "invalid_values": invalid_values,
                    },
                )
            )

    return issues


def _validate_numeric_rules(
    onboarding_field: models.OnboardingField,
    value: Any,
    rules: Mapping[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    try:
        numeric_value = Decimal(str(value))
    except InvalidOperation:
        return [
            _issue(
                code="INVALID_NUMBER",
                message=(
                    f"'{onboarding_field.label}' "
                    "must contain a valid number."
                ),
                onboarding_field=onboarding_field,
                value=value,
            )
        ]

    minimum = _first_defined(
        rules,
        "min_value",
        "minimum",
        "min",
    )

    maximum = _first_defined(
        rules,
        "max_value",
        "maximum",
        "max",
    )

    if minimum is not None:
        minimum_decimal = Decimal(str(minimum))

        if numeric_value < minimum_decimal:
            issues.append(
                _issue(
                    code="MIN_VALUE",
                    message=(
                        f"'{onboarding_field.label}' "
                        f"must be at least {minimum}."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                    details={
                        "minimum": minimum,
                    },
                )
            )

    if maximum is not None:
        maximum_decimal = Decimal(str(maximum))

        if numeric_value > maximum_decimal:
            issues.append(
                _issue(
                    code="MAX_VALUE",
                    message=(
                        f"'{onboarding_field.label}' "
                        f"must be no greater than "
                        f"{maximum}."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                    details={
                        "maximum": maximum,
                    },
                )
            )

    multiple_of = rules.get("multiple_of")

    if multiple_of is not None:
        divisor = Decimal(str(multiple_of))

        if divisor == 0:
            issues.append(
                _issue(
                    code="INVALID_MULTIPLE_OF",
                    message=(
                        "The field definition contains "
                        "an invalid multiple_of value."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )
        elif numeric_value % divisor != 0:
            issues.append(
                _issue(
                    code="MULTIPLE_OF",
                    message=(
                        f"'{onboarding_field.label}' "
                        f"must be a multiple of "
                        f"{multiple_of}."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                    details={
                        "multiple_of": multiple_of,
                    },
                )
            )

    return issues


def _validate_temporal_rules(
    onboarding_field: models.OnboardingField,
    value: str,
    rules: Mapping[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if (
        onboarding_field.field_type
        == models.FieldType.DATE
    ):
        actual_value: date | datetime = (
            date.fromisoformat(value)
        )
        parser = date.fromisoformat
    else:
        actual_value = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        def parser(raw: str) -> datetime:
            return datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            )

    minimum = _first_defined(
        rules,
        "min_date",
        "minimum",
        "min_value",
    )

    maximum = _first_defined(
        rules,
        "max_date",
        "maximum",
        "max_value",
    )

    if minimum is not None:
        try:
            minimum_value = parser(str(minimum))
        except ValueError:
            issues.append(
                _issue(
                    code="INVALID_MIN_DATE",
                    message=(
                        "The field definition contains "
                        "an invalid minimum date."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )
        else:
            if actual_value < minimum_value:
                issues.append(
                    _issue(
                        code="MIN_DATE",
                        message=(
                            f"'{onboarding_field.label}' "
                            f"must be on or after "
                            f"{minimum}."
                        ),
                        onboarding_field=onboarding_field,
                        value=value,
                        details={
                            "minimum": minimum,
                        },
                    )
                )

    if maximum is not None:
        try:
            maximum_value = parser(str(maximum))
        except ValueError:
            issues.append(
                _issue(
                    code="INVALID_MAX_DATE",
                    message=(
                        "The field definition contains "
                        "an invalid maximum date."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )
        else:
            if actual_value > maximum_value:
                issues.append(
                    _issue(
                        code="MAX_DATE",
                        message=(
                            f"'{onboarding_field.label}' "
                            f"must be on or before "
                            f"{maximum}."
                        ),
                        onboarding_field=onboarding_field,
                        value=value,
                        details={
                            "maximum": maximum,
                        },
                    )
                )

    return issues


def _validate_file_reference(
    onboarding_field: models.OnboardingField,
    value: str,
    rules: Mapping[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    require_url = bool(
        rules.get("require_url", False)
    )

    allowed_schemes = rules.get(
        "allowed_schemes",
        ["https"],
    )

    if require_url:
        parsed = urlparse(value)

        if (
            not parsed.scheme
            or not parsed.netloc
        ):
            issues.append(
                _issue(
                    code="INVALID_FILE_REFERENCE",
                    message=(
                        f"'{onboarding_field.label}' "
                        "must contain a valid file URL."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                )
            )
        elif (
            allowed_schemes
            and parsed.scheme
            not in set(allowed_schemes)
        ):
            issues.append(
                _issue(
                    code="INVALID_FILE_SCHEME",
                    message=(
                        f"'{onboarding_field.label}' "
                        "uses an unsupported URL scheme."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                    details={
                        "allowed_schemes": (
                            allowed_schemes
                        ),
                    },
                )
            )

    allowed_extensions = rules.get(
        "allowed_extensions"
    )

    if allowed_extensions:
        normalized_extensions = {
            str(extension)
            .lower()
            .lstrip(".")
            for extension in allowed_extensions
        }

        suffix = (
            value.rsplit(".", 1)[-1].lower()
            if "." in value
            else ""
        )

        if suffix not in normalized_extensions:
            issues.append(
                _issue(
                    code="INVALID_FILE_EXTENSION",
                    message=(
                        f"'{onboarding_field.label}' "
                        "uses an unsupported file type."
                    ),
                    onboarding_field=onboarding_field,
                    value=value,
                    details={
                        "allowed_extensions": sorted(
                            normalized_extensions
                        ),
                    },
                )
            )

    return issues


def _normalize_integer(
    value: Any,
    label: str,
) -> int:
    if isinstance(value, bool):
        raise ValueError(
            f"'{label}' must be a whole number."
        )

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if value.is_integer():
            return int(value)

        raise ValueError(
            f"'{label}' must be a whole number."
        )

    if isinstance(value, str):
        stripped = value.strip()

        try:
            decimal_value = Decimal(stripped)
        except InvalidOperation as exc:
            raise ValueError(
                f"'{label}' must be a whole number."
            ) from exc

        if decimal_value != decimal_value.to_integral_value():
            raise ValueError(
                f"'{label}' must be a whole number."
            )

        return int(decimal_value)

    raise ValueError(
        f"'{label}' must be a whole number."
    )


def _normalize_decimal(
    value: Any,
    label: str,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            f"'{label}' must be a number."
        )

    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(
            f"'{label}' must be a number."
        ) from exc


def _normalize_boolean(
    value: Any,
    label: str,
) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        if value == 1:
            return True

        if value == 0:
            return False

    if isinstance(value, str):
        normalized = value.strip().casefold()

        if normalized in {
            "true",
            "yes",
            "y",
            "1",
            "on",
        }:
            return True

        if normalized in {
            "false",
            "no",
            "n",
            "0",
            "off",
        }:
            return False

    raise ValueError(
        f"'{label}' must be true or false."
    )


def _normalize_date(
    value: Any,
    label: str,
) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(
                value.strip()
            )
        except ValueError as exc:
            raise ValueError(
                f"'{label}' must contain a valid "
                "ISO date."
            ) from exc

    raise ValueError(
        f"'{label}' must contain a valid date."
    )


def _normalize_datetime(
    value: Any,
    label: str,
) -> datetime:
    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        normalized = (
            value.strip()
            .replace("Z", "+00:00")
        )

        try:
            return datetime.fromisoformat(
                normalized
            )
        except ValueError as exc:
            raise ValueError(
                f"'{label}' must contain a valid "
                "ISO datetime."
            ) from exc

    raise ValueError(
        f"'{label}' must contain a valid datetime."
    )


def _normalize_select_value(
    onboarding_field: models.OnboardingField,
    value: Any,
) -> Any:
    if isinstance(
        value,
        (
            list,
            tuple,
            set,
            dict,
        ),
    ):
        raise ValueError(
            f"'{onboarding_field.label}' must "
            "contain one selected value."
        )

    return value


def _normalize_multiselect_value(
    onboarding_field: models.OnboardingField,
    value: Any,
) -> list[Any]:
    if not isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        raise ValueError(
            f"'{onboarding_field.label}' must "
            "contain a list of selected values."
        )

    normalized: list[Any] = []

    for item in value:
        if item not in normalized:
            normalized.append(item)

    return normalized


def _option_value_allowed(
    onboarding_field: models.OnboardingField,
    value: Any,
) -> bool:
    allowed_values = {
        _freeze_value(
            option.get("value")
        )
        for option in (
            onboarding_field.options_json or []
        )
        if isinstance(option, Mapping)
        and "value" in option
    }

    return _freeze_value(value) in allowed_values


def _normalize_validation_rules(
    validation_json: Any,
) -> dict[str, Any]:
    if validation_json is None:
        return {}

    if hasattr(validation_json, "model_dump"):
        validation_json = (
            validation_json.model_dump(
                mode="json"
            )
        )

    if not isinstance(
        validation_json,
        Mapping,
    ):
        raise ValueError(
            "field validation rules must be a mapping"
        )

    return dict(validation_json)


def _first_defined(
    values: Mapping[str, Any],
    *keys: str,
) -> Any:
    for key in keys:
        if (
            key in values
            and values[key] is not None
        ):
            return values[key]

    return None


def _value_length(
    value: Any,
) -> int | None:
    if isinstance(
        value,
        (
            str,
            list,
            tuple,
            set,
            frozenset,
            dict,
        ),
    ):
        return len(value)

    return None


def _freeze_value(
    value: Any,
) -> Any:
    if isinstance(value, list):
        return tuple(
            _freeze_value(item)
            for item in value
        )

    if isinstance(value, dict):
        return tuple(
            sorted(
                (
                    key,
                    _freeze_value(item),
                )
                for key, item in value.items()
            )
        )

    return value


def _issue(
    *,
    code: str,
    message: str,
    onboarding_field: models.OnboardingField,
    value: Any,
    details: dict[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        field_key=onboarding_field.field_key,
        step_key=(
            onboarding_field.step.step_key
            if onboarding_field.step is not None
            else None
        ),
        value=(
            {"redacted": True}
            if onboarding_field.sensitive
            and value is not None
            else value
        ),
        details=details or {},
    )
