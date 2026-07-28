from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app import models


SUPPORTED_OPERATORS = {
    "EQUALS",
    "NOT_EQUALS",
    "IN",
    "NOT_IN",
    "CONTAINS",
    "NOT_CONTAINS",
    "STARTS_WITH",
    "ENDS_WITH",
    "GREATER_THAN",
    "GREATER_THAN_OR_EQUAL",
    "LESS_THAN",
    "LESS_THAN_OR_EQUAL",
    "IS_EMPTY",
    "IS_NOT_EMPTY",
    "IS_TRUE",
    "IS_FALSE",
}


@dataclass(slots=True)
class ConditionEvaluation:
    """
    Result of evaluating one visibility condition.
    """

    field_key: str
    operator: str
    expected_value: Any
    actual_value: Any
    matched: bool
    error: str | None = None


@dataclass(slots=True)
class VisibilityEvaluation:
    """
    Result of evaluating a complete visibility rule.
    """

    visible: bool
    match_mode: str
    condition_results: list[ConditionEvaluation]
    error: str | None = None


def normalize_visibility_rule(
    visibility_json: Any,
) -> dict[str, Any] | None:
    """
    Normalize a Pydantic model or JSON-compatible object into a visibility
    rule dictionary.

    Expected shape:

    {
        "match": "ALL",
        "conditions": [
            {
                "field_key": "country",
                "operator": "EQUALS",
                "value": "US"
            }
        ]
    }

    The service also accepts common aliases such as match_mode,
    expected_value, and values.
    """

    if visibility_json is None:
        return None

    if hasattr(visibility_json, "model_dump"):
        visibility_json = visibility_json.model_dump(
            mode="json"
        )

    if not isinstance(visibility_json, Mapping):
        raise ValueError(
            "visibility rule must be a mapping"
        )

    rule = dict(visibility_json)

    raw_conditions = rule.get("conditions", [])

    if raw_conditions is None:
        raw_conditions = []

    if not isinstance(raw_conditions, list):
        raise ValueError(
            "visibility rule conditions must be a list"
        )

    normalized_conditions: list[dict[str, Any]] = []

    for raw_condition in raw_conditions:
        if hasattr(raw_condition, "model_dump"):
            raw_condition = raw_condition.model_dump(
                mode="json"
            )

        if not isinstance(raw_condition, Mapping):
            raise ValueError(
                "each visibility condition must be a mapping"
            )

        condition = dict(raw_condition)

        field_key = condition.get("field_key")

        if not isinstance(field_key, str) or not field_key:
            raise ValueError(
                "each visibility condition requires field_key"
            )

        operator = _normalize_operator(
            condition.get("operator", "EQUALS")
        )

        expected_value = _extract_expected_value(
            condition
        )

        normalized_conditions.append(
            {
                "field_key": field_key,
                "operator": operator,
                "value": expected_value,
            }
        )

    match_mode = _normalize_match_mode(
        rule.get(
            "match",
            rule.get(
                "match_mode",
                rule.get("mode", "ALL"),
            ),
        )
    )

    return {
        "match": match_mode,
        "conditions": normalized_conditions,
    }


def evaluate_visibility(
    visibility_json: Any,
    answers: Mapping[str, Any] | None,
    *,
    default_visible: bool = True,
    strict: bool = False,
) -> VisibilityEvaluation:
    """
    Evaluate a visibility rule against a field-key-to-value answer map.

    No rule means visible by default.

    ALL:
        Every condition must match.

    ANY:
        At least one condition must match.

    NONE:
        No condition may match.

    strict=False converts malformed rules or comparison errors into a
    nonvisible result rather than raising.
    """

    try:
        rule = normalize_visibility_rule(
            visibility_json
        )
    except (TypeError, ValueError) as exc:
        if strict:
            raise

        return VisibilityEvaluation(
            visible=False,
            match_mode="ALL",
            condition_results=[],
            error=str(exc),
        )

    if rule is None:
        return VisibilityEvaluation(
            visible=default_visible,
            match_mode="ALL",
            condition_results=[],
        )

    conditions = rule["conditions"]
    match_mode = rule["match"]

    if not conditions:
        return VisibilityEvaluation(
            visible=default_visible,
            match_mode=match_mode,
            condition_results=[],
        )

    answer_map = answers or {}
    condition_results: list[ConditionEvaluation] = []

    for condition in conditions:
        result = evaluate_condition(
            field_key=condition["field_key"],
            operator=condition["operator"],
            expected_value=condition["value"],
            answers=answer_map,
            strict=strict,
        )

        condition_results.append(result)

    matched_values = [
        result.matched
        for result in condition_results
    ]

    if match_mode == "ALL":
        visible = all(matched_values)
    elif match_mode == "ANY":
        visible = any(matched_values)
    elif match_mode == "NONE":
        visible = not any(matched_values)
    else:
        if strict:
            raise ValueError(
                f"unsupported visibility match mode "
                f"'{match_mode}'"
            )

        visible = False

    return VisibilityEvaluation(
        visible=visible,
        match_mode=match_mode,
        condition_results=condition_results,
    )


def is_visible(
    visibility_json: Any,
    answers: Mapping[str, Any] | None,
    *,
    default_visible: bool = True,
    strict: bool = False,
) -> bool:
    """
    Convenience wrapper returning only the visibility boolean.
    """

    return evaluate_visibility(
        visibility_json,
        answers,
        default_visible=default_visible,
        strict=strict,
    ).visible


def evaluate_condition(
    *,
    field_key: str,
    operator: str,
    expected_value: Any,
    answers: Mapping[str, Any],
    strict: bool = False,
) -> ConditionEvaluation:
    """
    Evaluate one condition against the answer map.
    """

    normalized_operator = _normalize_operator(
        operator
    )

    actual_value = answers.get(field_key)

    try:
        matched = compare_values(
            actual_value=actual_value,
            operator=normalized_operator,
            expected_value=expected_value,
        )

        return ConditionEvaluation(
            field_key=field_key,
            operator=normalized_operator,
            expected_value=expected_value,
            actual_value=actual_value,
            matched=matched,
        )

    except (TypeError, ValueError) as exc:
        if strict:
            raise

        return ConditionEvaluation(
            field_key=field_key,
            operator=normalized_operator,
            expected_value=expected_value,
            actual_value=actual_value,
            matched=False,
            error=str(exc),
        )


def compare_values(
    *,
    actual_value: Any,
    operator: str,
    expected_value: Any = None,
) -> bool:
    """
    Apply one supported comparison operator.
    """

    normalized_operator = _normalize_operator(
        operator
    )

    if normalized_operator not in SUPPORTED_OPERATORS:
        raise ValueError(
            f"unsupported condition operator "
            f"'{normalized_operator}'"
        )

    if normalized_operator == "IS_EMPTY":
        return is_empty_value(actual_value)

    if normalized_operator == "IS_NOT_EMPTY":
        return not is_empty_value(actual_value)

    if normalized_operator == "IS_TRUE":
        return _coerce_boolean(actual_value) is True

    if normalized_operator == "IS_FALSE":
        return _coerce_boolean(actual_value) is False

    if normalized_operator == "EQUALS":
        return _values_equal(
            actual_value,
            expected_value,
        )

    if normalized_operator == "NOT_EQUALS":
        return not _values_equal(
            actual_value,
            expected_value,
        )

    if normalized_operator == "IN":
        return _operator_in(
            actual_value,
            expected_value,
        )

    if normalized_operator == "NOT_IN":
        return not _operator_in(
            actual_value,
            expected_value,
        )

    if normalized_operator == "CONTAINS":
        return _operator_contains(
            actual_value,
            expected_value,
        )

    if normalized_operator == "NOT_CONTAINS":
        return not _operator_contains(
            actual_value,
            expected_value,
        )

    if normalized_operator == "STARTS_WITH":
        return _as_text(actual_value).startswith(
            _as_text(expected_value)
        )

    if normalized_operator == "ENDS_WITH":
        return _as_text(actual_value).endswith(
            _as_text(expected_value)
        )

    comparable_actual, comparable_expected = (
        _coerce_comparable_pair(
            actual_value,
            expected_value,
        )
    )

    if normalized_operator == "GREATER_THAN":
        return comparable_actual > comparable_expected

    if (
        normalized_operator
        == "GREATER_THAN_OR_EQUAL"
    ):
        return comparable_actual >= comparable_expected

    if normalized_operator == "LESS_THAN":
        return comparable_actual < comparable_expected

    if (
        normalized_operator
        == "LESS_THAN_OR_EQUAL"
    ):
        return comparable_actual <= comparable_expected

    raise ValueError(
        f"unsupported condition operator "
        f"'{normalized_operator}'"
    )


def is_step_visible(
    step: models.OnboardingStep,
    answers: Mapping[str, Any],
    *,
    strict: bool = False,
) -> bool:
    """
    Evaluate one step's visibility rule.
    """

    return is_visible(
        step.visibility_json,
        answers,
        default_visible=True,
        strict=strict,
    )


def is_field_visible(
    field: models.OnboardingField,
    answers: Mapping[str, Any],
    *,
    step_visible: bool = True,
    strict: bool = False,
) -> bool:
    """
    A field is visible only when its parent step is visible and its own
    visibility rule matches.
    """

    if not step_visible:
        return False

    return is_visible(
        field.visibility_json,
        answers,
        default_visible=True,
        strict=strict,
    )


def is_requirement_visible(
    requirement: models.OnboardingRequirement,
    answers: Mapping[str, Any],
    *,
    strict: bool = False,
) -> bool:
    """
    Evaluate one requirement definition's visibility rule.
    """

    return is_visible(
        requirement.visibility_json,
        answers,
        default_visible=True,
        strict=strict,
    )


def list_visible_steps(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    strict: bool = False,
) -> list[models.OnboardingStep]:
    """
    Return visible steps in definition order.
    """

    ordered_steps = sorted(
        flow_version.steps,
        key=lambda step: (
            step.position,
            step.id,
        ),
    )

    return [
        step
        for step in ordered_steps
        if is_step_visible(
            step,
            answers,
            strict=strict,
        )
    ]


def list_visible_fields(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    step_key: str | None = None,
    strict: bool = False,
) -> list[models.OnboardingField]:
    """
    Return visible fields in step and field order.

    Supplying step_key restricts the result to one step.
    """

    visible_fields: list[
        models.OnboardingField
    ] = []

    for step in sorted(
        flow_version.steps,
        key=lambda item: (
            item.position,
            item.id,
        ),
    ):
        if (
            step_key is not None
            and step.step_key != step_key
        ):
            continue

        step_is_visible = is_step_visible(
            step,
            answers,
            strict=strict,
        )

        if not step_is_visible:
            continue

        ordered_fields = sorted(
            step.fields,
            key=lambda field: (
                field.position,
                field.id,
            ),
        )

        for field in ordered_fields:
            if is_field_visible(
                field,
                answers,
                step_visible=True,
                strict=strict,
            ):
                visible_fields.append(field)

    return visible_fields


def list_visible_requirements(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    strict: bool = False,
) -> list[models.OnboardingRequirement]:
    """
    Return visible requirement definitions in definition order.
    """

    ordered_requirements = sorted(
        flow_version.requirements,
        key=lambda requirement: (
            requirement.position,
            requirement.id,
        ),
    )

    return [
        requirement
        for requirement in ordered_requirements
        if is_requirement_visible(
            requirement,
            answers,
            strict=strict,
        )
    ]


def get_visible_step_keys(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    strict: bool = False,
) -> list[str]:
    """
    Return ordered keys for every visible step.
    """

    return [
        step.step_key
        for step in list_visible_steps(
            flow_version,
            answers,
            strict=strict,
        )
    ]


def get_first_visible_step(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    strict: bool = False,
) -> models.OnboardingStep | None:
    """
    Return the first currently visible step.
    """

    visible_steps = list_visible_steps(
        flow_version,
        answers,
        strict=strict,
    )

    if not visible_steps:
        return None

    return visible_steps[0]


def get_next_visible_step(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    current_step_key: str | None,
    strict: bool = False,
) -> models.OnboardingStep | None:
    """
    Return the next visible step after current_step_key.

    When the current step is no longer visible, this returns the first
    visible step appearing after its original position. When no current key
    is supplied, it returns the first visible step.
    """

    ordered_steps = sorted(
        flow_version.steps,
        key=lambda step: (
            step.position,
            step.id,
        ),
    )

    if current_step_key is None:
        return get_first_visible_step(
            flow_version,
            answers,
            strict=strict,
        )

    current_index: int | None = None

    for index, step in enumerate(ordered_steps):
        if step.step_key == current_step_key:
            current_index = index
            break

    if current_index is None:
        raise ValueError(
            f"step '{current_step_key}' does not belong "
            "to this flow version"
        )

    for step in ordered_steps[current_index + 1 :]:
        if is_step_visible(
            step,
            answers,
            strict=strict,
        ):
            return step

    return None


def get_previous_visible_step(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    current_step_key: str,
    strict: bool = False,
) -> models.OnboardingStep | None:
    """
    Return the visible step preceding current_step_key.
    """

    ordered_steps = sorted(
        flow_version.steps,
        key=lambda step: (
            step.position,
            step.id,
        ),
    )

    current_index: int | None = None

    for index, step in enumerate(ordered_steps):
        if step.step_key == current_step_key:
            current_index = index
            break

    if current_index is None:
        raise ValueError(
            f"step '{current_step_key}' does not belong "
            "to this flow version"
        )

    for step in reversed(
        ordered_steps[:current_index]
    ):
        if is_step_visible(
            step,
            answers,
            strict=strict,
        ):
            return step

    return None


def resolve_current_visible_step(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    current_step_key: str | None,
    strict: bool = False,
) -> models.OnboardingStep | None:
    """
    Resolve a safe current step after answers change.

    If the stored current step remains visible, it is returned unchanged.

    If it becomes hidden, the service prefers the next visible step. If no
    later step is visible, it falls back to the nearest previous visible
    step.
    """

    visible_steps = list_visible_steps(
        flow_version,
        answers,
        strict=strict,
    )

    if not visible_steps:
        return None

    if current_step_key is None:
        return visible_steps[0]

    for step in visible_steps:
        if step.step_key == current_step_key:
            return step

    ordered_steps = sorted(
        flow_version.steps,
        key=lambda step: (
            step.position,
            step.id,
        ),
    )

    current_index: int | None = None

    for index, step in enumerate(ordered_steps):
        if step.step_key == current_step_key:
            current_index = index
            break

    if current_index is None:
        return visible_steps[0]

    for step in ordered_steps[current_index + 1 :]:
        if is_step_visible(
            step,
            answers,
            strict=strict,
        ):
            return step

    for step in reversed(
        ordered_steps[:current_index]
    ):
        if is_step_visible(
            step,
            answers,
            strict=strict,
        ):
            return step

    return None


def build_visibility_map(
    flow_version: models.OnboardingFlowVersion,
    answers: Mapping[str, Any],
    *,
    strict: bool = False,
) -> dict[str, dict[str, bool]]:
    """
    Build a client-friendly visibility map.

    Example:

    {
        "steps": {
            "profile": true
        },
        "fields": {
            "email": true
        },
        "requirements": {
            "email_verified": true
        }
    }
    """

    step_map: dict[str, bool] = {}
    field_map: dict[str, bool] = {}
    requirement_map: dict[str, bool] = {}

    for step in sorted(
        flow_version.steps,
        key=lambda item: (
            item.position,
            item.id,
        ),
    ):
        step_visible = is_step_visible(
            step,
            answers,
            strict=strict,
        )

        step_map[step.step_key] = step_visible

        for field in sorted(
            step.fields,
            key=lambda item: (
                item.position,
                item.id,
            ),
        ):
            field_map[field.field_key] = (
                is_field_visible(
                    field,
                    answers,
                    step_visible=step_visible,
                    strict=strict,
                )
            )

    for requirement in sorted(
        flow_version.requirements,
        key=lambda item: (
            item.position,
            item.id,
        ),
    ):
        requirement_map[
            requirement.requirement_key
        ] = is_requirement_visible(
            requirement,
            answers,
            strict=strict,
        )

    return {
        "steps": step_map,
        "fields": field_map,
        "requirements": requirement_map,
    }


def extract_visibility_field_keys(
    visibility_json: Any,
) -> set[str]:
    """
    Return every field key referenced by a visibility rule.
    """

    rule = normalize_visibility_rule(
        visibility_json
    )

    if rule is None:
        return set()

    return {
        condition["field_key"]
        for condition in rule["conditions"]
    }


def validate_visibility_references(
    visibility_json: Any,
    *,
    valid_field_keys: Iterable[str],
) -> list[str]:
    """
    Return unknown field keys referenced by a visibility rule.
    """

    valid_keys = set(valid_field_keys)

    referenced_keys = extract_visibility_field_keys(
        visibility_json
    )

    return sorted(
        referenced_keys - valid_keys
    )


def is_empty_value(value: Any) -> bool:
    """
    Determine whether a value should count as unanswered or empty.
    """

    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
            frozenset,
            dict,
        ),
    ):
        return len(value) == 0

    return False


def _extract_expected_value(
    condition: Mapping[str, Any],
) -> Any:
    if "value" in condition:
        return condition["value"]

    if "expected_value" in condition:
        return condition["expected_value"]

    if "values" in condition:
        return condition["values"]

    return None


def _normalize_operator(
    operator: Any,
) -> str:
    if hasattr(operator, "value"):
        operator = operator.value

    normalized = str(operator).strip().upper()

    aliases = {
        "EQ": "EQUALS",
        "==": "EQUALS",
        "NE": "NOT_EQUALS",
        "!=": "NOT_EQUALS",
        "GT": "GREATER_THAN",
        ">": "GREATER_THAN",
        "GTE": "GREATER_THAN_OR_EQUAL",
        ">=": "GREATER_THAN_OR_EQUAL",
        "LT": "LESS_THAN",
        "<": "LESS_THAN",
        "LTE": "LESS_THAN_OR_EQUAL",
        "<=": "LESS_THAN_OR_EQUAL",
        "EMPTY": "IS_EMPTY",
        "NOT_EMPTY": "IS_NOT_EMPTY",
        "TRUE": "IS_TRUE",
        "FALSE": "IS_FALSE",
    }

    return aliases.get(
        normalized,
        normalized,
    )


def _normalize_match_mode(
    match_mode: Any,
) -> str:
    if hasattr(match_mode, "value"):
        match_mode = match_mode.value

    normalized = str(
        match_mode or "ALL"
    ).strip().upper()

    aliases = {
        "AND": "ALL",
        "OR": "ANY",
        "NOT": "NONE",
    }

    normalized = aliases.get(
        normalized,
        normalized,
    )

    if normalized not in {
        "ALL",
        "ANY",
        "NONE",
    }:
        raise ValueError(
            f"unsupported visibility match mode "
            f"'{normalized}'"
        )

    return normalized


def _values_equal(
    actual_value: Any,
    expected_value: Any,
) -> bool:
    if actual_value == expected_value:
        return True

    if isinstance(
        actual_value,
        (
            bool,
        ),
    ) or isinstance(
        expected_value,
        (
            bool,
        ),
    ):
        try:
            return (
                _coerce_boolean(actual_value)
                == _coerce_boolean(expected_value)
            )
        except ValueError:
            return False

    try:
        actual_number = _coerce_decimal(
            actual_value
        )
        expected_number = _coerce_decimal(
            expected_value
        )

        return actual_number == expected_number
    except (TypeError, ValueError):
        pass

    actual_temporal = _coerce_temporal(
        actual_value
    )
    expected_temporal = _coerce_temporal(
        expected_value
    )

    if (
        actual_temporal is not None
        and expected_temporal is not None
    ):
        return actual_temporal == expected_temporal

    if (
        isinstance(actual_value, str)
        and isinstance(expected_value, str)
    ):
        return (
            actual_value.strip().casefold()
            == expected_value.strip().casefold()
        )

    return False


def _operator_in(
    actual_value: Any,
    expected_value: Any,
) -> bool:
    expected_collection = _as_collection(
        expected_value
    )

    if isinstance(
        actual_value,
        (
            list,
            tuple,
            set,
            frozenset,
        ),
    ):
        return any(
            any(
                _values_equal(
                    actual_item,
                    expected_item,
                )
                for expected_item
                in expected_collection
            )
            for actual_item in actual_value
        )

    return any(
        _values_equal(
            actual_value,
            expected_item,
        )
        for expected_item in expected_collection
    )


def _operator_contains(
    actual_value: Any,
    expected_value: Any,
) -> bool:
    if actual_value is None:
        return False

    if isinstance(actual_value, str):
        return (
            _as_text(expected_value).casefold()
            in actual_value.casefold()
        )

    if isinstance(actual_value, Mapping):
        return any(
            _values_equal(
                key,
                expected_value,
            )
            for key in actual_value
        )

    if isinstance(
        actual_value,
        (
            list,
            tuple,
            set,
            frozenset,
        ),
    ):
        expected_collection = _as_collection(
            expected_value
        )

        return all(
            any(
                _values_equal(
                    actual_item,
                    expected_item,
                )
                for actual_item in actual_value
            )
            for expected_item in expected_collection
        )

    return False


def _as_collection(
    value: Any,
) -> Sequence[Any]:
    if isinstance(
        value,
        (
            list,
            tuple,
            set,
            frozenset,
        ),
    ):
        return list(value)

    return [value]


def _as_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    return str(value)


def _coerce_boolean(
    value: Any,
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
        f"value '{value}' cannot be interpreted "
        "as a boolean"
    )


def _coerce_decimal(
    value: Any,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            "boolean values are not numeric"
        )

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        return Decimal(str(value))

    if isinstance(value, str):
        stripped = value.strip()

        if not stripped:
            raise ValueError(
                "empty text is not numeric"
            )

        return Decimal(stripped)

    raise TypeError(
        f"value of type {type(value).__name__} "
        "is not numeric"
    )


def _coerce_temporal(
    value: Any,
) -> datetime | date | None:
    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        return None

    stripped = value.strip()

    if not stripped:
        return None

    iso_value = stripped.replace(
        "Z",
        "+00:00",
    )

    try:
        return datetime.fromisoformat(
            iso_value
        )
    except ValueError:
        pass

    try:
        return date.fromisoformat(
            stripped
        )
    except ValueError:
        return None


def _coerce_comparable_pair(
    actual_value: Any,
    expected_value: Any,
) -> tuple[Any, Any]:
    try:
        return (
            _coerce_decimal(actual_value),
            _coerce_decimal(expected_value),
        )
    except (TypeError, ValueError):
        pass

    actual_temporal = _coerce_temporal(
        actual_value
    )
    expected_temporal = _coerce_temporal(
        expected_value
    )

    if (
        actual_temporal is not None
        and expected_temporal is not None
    ):
        if isinstance(
            actual_temporal,
            datetime,
        ) != isinstance(
            expected_temporal,
            datetime,
        ):
            raise ValueError(
                "date and datetime values cannot be "
                "ordered against each other"
            )

        return (
            actual_temporal,
            expected_temporal,
        )

    if (
        isinstance(actual_value, str)
        and isinstance(expected_value, str)
    ):
        return (
            actual_value.casefold(),
            expected_value.casefold(),
        )

    raise ValueError(
        "values cannot be converted into a "
        "compatible ordered pair"
    )
