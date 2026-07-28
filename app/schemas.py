from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models import (
    EventType,
    FieldType,
    FlowStatus,
    FlowVersionStatus,
    RequirementSource,
    RequirementStatus,
    SessionStatus,
    SubjectType,
)


KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class SchemaBase(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        extra="forbid",
        use_enum_values=False,
    )


class PaginationMeta(SchemaBase):
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class ServiceHealthResponse(SchemaBase):
    service: str
    status: Literal["ok"]
    version: str
    database: str | None = None
    timestamp: datetime


class ServiceVersionResponse(SchemaBase):
    service: str
    version: str


class ServiceInfoResponse(SchemaBase):
    service: str
    version: str
    description: str
    database_url: str | None = None
    supported_subject_types: list[SubjectType]
    supported_field_types: list[FieldType]


# ---------------------------------------------------------------------------
# Shared condition, option, and validation schemas
# ---------------------------------------------------------------------------


class FieldOption(SchemaBase):
    value: str | int | float | bool
    label: str
    description: str | None = None
    disabled: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class VisibilityCondition(SchemaBase):
    field_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )
    operator: Literal[
        "equals",
        "not_equals",
        "in",
        "not_in",
        "exists",
    ]
    value: Any | None = None

    @model_validator(mode="after")
    def validate_operator_value(self) -> VisibilityCondition:
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list):
                raise ValueError(
                    f"operator '{self.operator}' requires a list value"
                )

        if self.operator == "exists" and self.value is not None:
            raise ValueError(
                "operator 'exists' must not include a comparison value"
            )

        return self


class VisibilityRule(SchemaBase):
    mode: Literal["all", "any"] = "all"
    conditions: list[VisibilityCondition] = Field(
        default_factory=list,
        min_length=1,
    )


class FieldValidationRule(SchemaBase):
    minimum: int | float | Decimal | None = None
    maximum: int | float | Decimal | None = None

    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)

    regex: str | None = None

    allowed_values: list[Any] | None = None

    earliest_date: date | None = None
    latest_date: date | None = None

    earliest_datetime: datetime | None = None
    latest_datetime: datetime | None = None

    custom_message: str | None = Field(
        default=None,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> FieldValidationRule:
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError(
                "minimum cannot be greater than maximum"
            )

        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError(
                "min_length cannot be greater than max_length"
            )

        if (
            self.earliest_date is not None
            and self.latest_date is not None
            and self.earliest_date > self.latest_date
        ):
            raise ValueError(
                "earliest_date cannot be later than latest_date"
            )

        if (
            self.earliest_datetime is not None
            and self.latest_datetime is not None
            and self.earliest_datetime > self.latest_datetime
        ):
            raise ValueError(
                "earliest_datetime cannot be later than latest_datetime"
            )

        return self


# ---------------------------------------------------------------------------
# Onboarding field schemas
# ---------------------------------------------------------------------------


class OnboardingFieldBase(SchemaBase):
    field_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    label: str = Field(
        min_length=1,
        max_length=250,
    )

    description: str | None = None

    placeholder: str | None = Field(
        default=None,
        max_length=250,
    )

    field_type: FieldType

    position: int = Field(
        ge=0,
        le=100000,
    )

    required: bool = False
    sensitive: bool = False

    default_value_json: Any | None = None

    options_json: list[FieldOption] = Field(
        default_factory=list,
    )

    validation_json: FieldValidationRule = Field(
        default_factory=FieldValidationRule,
    )

    visibility_json: VisibilityRule | None = None

    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_field_configuration(self) -> OnboardingFieldBase:
        option_field_types = {
            FieldType.SELECT,
            FieldType.MULTISELECT,
        }

        if self.field_type in option_field_types and not self.options_json:
            raise ValueError(
                f"{self.field_type.value} fields require options_json"
            )

        if (
            self.field_type not in option_field_types
            and self.options_json
        ):
            raise ValueError(
                "options_json is only supported for SELECT "
                "and MULTISELECT fields"
            )

        option_values = [
            str(option.value)
            for option in self.options_json
        ]

        if len(option_values) != len(set(option_values)):
            raise ValueError(
                "field option values must be unique"
            )

        return self


class OnboardingFieldCreate(OnboardingFieldBase):
    pass


class OnboardingFieldUpdate(SchemaBase):
    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=250,
    )

    description: str | None = None

    placeholder: str | None = Field(
        default=None,
        max_length=250,
    )

    field_type: FieldType | None = None

    position: int | None = Field(
        default=None,
        ge=0,
        le=100000,
    )

    required: bool | None = None
    sensitive: bool | None = None

    default_value_json: Any | None = None

    options_json: list[FieldOption] | None = None

    validation_json: FieldValidationRule | None = None

    visibility_json: VisibilityRule | None = None

    metadata_json: dict[str, Any] | None = None


class OnboardingFieldRead(OnboardingFieldBase):
    id: str
    flow_version_id: str
    step_id: str

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Onboarding step schemas
# ---------------------------------------------------------------------------


class OnboardingStepBase(SchemaBase):
    step_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    title: str = Field(
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    position: int = Field(
        ge=0,
        le=100000,
    )

    optional: bool = False

    visibility_json: VisibilityRule | None = None

    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )


class OnboardingStepCreate(OnboardingStepBase):
    fields: list[OnboardingFieldCreate] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_unique_fields(self) -> OnboardingStepCreate:
        field_keys = [
            field.field_key
            for field in self.fields
        ]

        if len(field_keys) != len(set(field_keys)):
            raise ValueError(
                "field keys must be unique within a step"
            )

        positions = [
            field.position
            for field in self.fields
        ]

        if len(positions) != len(set(positions)):
            raise ValueError(
                "field positions must be unique within a step"
            )

        return self


class OnboardingStepUpdate(SchemaBase):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    position: int | None = Field(
        default=None,
        ge=0,
        le=100000,
    )

    optional: bool | None = None

    visibility_json: VisibilityRule | None = None

    metadata_json: dict[str, Any] | None = None


class OnboardingStepRead(OnboardingStepBase):
    id: str
    flow_version_id: str

    created_at: datetime
    updated_at: datetime

    fields: list[OnboardingFieldRead] = Field(
        default_factory=list,
    )


# ---------------------------------------------------------------------------
# Requirement definition schemas
# ---------------------------------------------------------------------------


class OnboardingRequirementBase(SchemaBase):
    requirement_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    position: int = Field(
        ge=0,
        le=100000,
    )

    required: bool = True

    source: RequirementSource = RequirementSource.INTERNAL

    provider_key: str | None = Field(
        default=None,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    configuration_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    visibility_json: VisibilityRule | None = None

    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_requirement_source(
        self,
    ) -> OnboardingRequirementBase:
        if (
            self.source == RequirementSource.EXTERNAL
            and not self.provider_key
        ):
            raise ValueError(
                "external requirements require provider_key"
            )

        return self


class OnboardingRequirementCreate(OnboardingRequirementBase):
    pass


class OnboardingRequirementUpdate(SchemaBase):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    position: int | None = Field(
        default=None,
        ge=0,
        le=100000,
    )

    required: bool | None = None

    source: RequirementSource | None = None

    provider_key: str | None = Field(
        default=None,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    configuration_json: dict[str, Any] | None = None

    visibility_json: VisibilityRule | None = None

    metadata_json: dict[str, Any] | None = None


class OnboardingRequirementRead(OnboardingRequirementBase):
    id: str
    flow_version_id: str

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Flow-version schemas
# ---------------------------------------------------------------------------


class OnboardingFlowVersionBase(SchemaBase):
    title: str = Field(
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    subject_type: SubjectType

    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )


class OnboardingFlowVersionCreate(
    OnboardingFlowVersionBase
):
    version_number: int | None = Field(
        default=None,
        ge=1,
    )

    steps: list[OnboardingStepCreate] = Field(
        default_factory=list,
    )

    requirements: list[OnboardingRequirementCreate] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_version_definition(
        self,
    ) -> OnboardingFlowVersionCreate:
        step_keys = [
            step.step_key
            for step in self.steps
        ]

        if len(step_keys) != len(set(step_keys)):
            raise ValueError(
                "step keys must be unique within a flow version"
            )

        step_positions = [
            step.position
            for step in self.steps
        ]

        if len(step_positions) != len(set(step_positions)):
            raise ValueError(
                "step positions must be unique within a flow version"
            )

        all_field_keys: list[str] = []

        for step in self.steps:
            all_field_keys.extend(
                field.field_key
                for field in step.fields
            )

        if len(all_field_keys) != len(set(all_field_keys)):
            raise ValueError(
                "field keys must be unique across the entire flow version"
            )

        requirement_keys = [
            requirement.requirement_key
            for requirement in self.requirements
        ]

        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError(
                "requirement keys must be unique within a flow version"
            )

        requirement_positions = [
            requirement.position
            for requirement in self.requirements
        ]

        if (
            len(requirement_positions)
            != len(set(requirement_positions))
        ):
            raise ValueError(
                "requirement positions must be unique "
                "within a flow version"
            )

        return self


class OnboardingFlowVersionUpdate(SchemaBase):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    subject_type: SubjectType | None = None

    metadata_json: dict[str, Any] | None = None


class OnboardingFlowVersionSummary(SchemaBase):
    id: str
    flow_id: str

    version_number: int
    status: FlowVersionStatus

    title: str
    description: str | None

    subject_type: SubjectType

    published_at: datetime | None
    retired_at: datetime | None

    created_at: datetime
    updated_at: datetime


class OnboardingFlowVersionRead(
    OnboardingFlowVersionSummary
):
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    steps: list[OnboardingStepRead] = Field(
        default_factory=list,
    )

    requirements: list[OnboardingRequirementRead] = Field(
        default_factory=list,
    )


class PublishFlowVersionRequest(SchemaBase):
    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


class RetireFlowVersionRequest(SchemaBase):
    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    reason: str | None = Field(
        default=None,
        max_length=1000,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


# ---------------------------------------------------------------------------
# Flow schemas
# ---------------------------------------------------------------------------


class OnboardingFlowBase(SchemaBase):
    flow_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )


class OnboardingFlowCreate(OnboardingFlowBase):
    initial_version: OnboardingFlowVersionCreate | None = None


class OnboardingFlowUpdate(SchemaBase):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    description: str | None = None

    status: FlowStatus | None = None

    metadata_json: dict[str, Any] | None = None


class OnboardingFlowSummary(OnboardingFlowBase):
    id: str
    status: FlowStatus

    created_at: datetime
    updated_at: datetime


class OnboardingFlowRead(OnboardingFlowSummary):
    versions: list[OnboardingFlowVersionSummary] = Field(
        default_factory=list,
    )


class OnboardingFlowDetail(OnboardingFlowSummary):
    versions: list[OnboardingFlowVersionRead] = Field(
        default_factory=list,
    )


class OnboardingFlowListResponse(SchemaBase):
    items: list[OnboardingFlowSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class OnboardingFlowVersionListResponse(SchemaBase):
    items: list[OnboardingFlowVersionSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Answer schemas
# ---------------------------------------------------------------------------


class OnboardingAnswerWrite(SchemaBase):
    value_json: Any | None = None

    answered_by: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


class OnboardingAnswerBulkItem(SchemaBase):
    field_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    value_json: Any | None = None


class OnboardingAnswerBulkWrite(SchemaBase):
    answers: list[OnboardingAnswerBulkItem] = Field(
        min_length=1,
        max_length=500,
    )

    answered_by: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )

    @field_validator("answers")
    @classmethod
    def validate_unique_answer_keys(
        cls,
        answers: list[OnboardingAnswerBulkItem],
    ) -> list[OnboardingAnswerBulkItem]:
        field_keys = [
            answer.field_key
            for answer in answers
        ]

        if len(field_keys) != len(set(field_keys)):
            raise ValueError(
                "bulk answers must contain unique field keys"
            )

        return answers


class ValidationErrorDetail(SchemaBase):
    code: str
    message: str

    field_key: str | None = None
    requirement_key: str | None = None

    details_json: dict[str, Any] = Field(
        default_factory=dict,
    )


class OnboardingAnswerRead(SchemaBase):
    id: str
    session_id: str
    field_id: str
    field_key: str

    value_json: Any | None

    is_valid: bool

    validation_errors_json: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    answered_by: str | None
    answered_at: datetime

    created_at: datetime
    updated_at: datetime


class OnboardingAnswerWriteResponse(SchemaBase):
    answer: OnboardingAnswerRead
    session_status: SessionStatus
    progress_percent: int = Field(ge=0, le=100)
    current_step_key: str | None = None


class OnboardingAnswerBulkWriteResponse(SchemaBase):
    answers: list[OnboardingAnswerRead]
    session_status: SessionStatus
    progress_percent: int = Field(ge=0, le=100)
    current_step_key: str | None = None


# ---------------------------------------------------------------------------
# Session requirement-state schemas
# ---------------------------------------------------------------------------


class SessionRequirementUpdate(SchemaBase):
    status: RequirementStatus

    external_reference: str | None = Field(
        default=None,
        max_length=250,
    )

    details_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    satisfied_by: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )

    @model_validator(mode="after")
    def validate_requirement_update(
        self,
    ) -> SessionRequirementUpdate:
        if (
            self.status == RequirementStatus.SATISFIED
            and not self.satisfied_by
        ):
            raise ValueError(
                "satisfied requirements require satisfied_by"
            )

        return self


class SessionRequirementRead(SchemaBase):
    id: str
    session_id: str
    requirement_id: str
    requirement_key: str

    status: RequirementStatus

    external_reference: str | None

    details_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    satisfied_by: str | None
    satisfied_at: datetime | None

    created_at: datetime
    updated_at: datetime


class SessionRequirementDetail(
    SessionRequirementRead
):
    definition: OnboardingRequirementRead | None = None


class SessionRequirementListResponse(SchemaBase):
    items: list[SessionRequirementDetail]
    total: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------


class OnboardingSessionCreate(SchemaBase):
    flow_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    version_number: int | None = Field(
        default=None,
        ge=1,
    )

    session_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    subject_type: SubjectType

    subject_id: str = Field(
        min_length=1,
        max_length=200,
    )

    context_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


class OnboardingSessionUpdate(SchemaBase):
    current_step_key: str | None = Field(
        default=None,
        max_length=120,
        pattern=KEY_PATTERN,
    )

    context_json: dict[str, Any] | None = None

    metadata_json: dict[str, Any] | None = None

    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


class OnboardingSessionSummary(SchemaBase):
    id: str
    session_key: str

    flow_id: str
    flow_version_id: str

    subject_type: SubjectType
    subject_id: str

    status: SessionStatus

    current_step_key: str | None
    progress_percent: int = Field(ge=0, le=100)

    started_at: datetime | None
    completed_at: datetime | None
    abandoned_at: datetime | None

    created_at: datetime
    updated_at: datetime


class OnboardingSessionRead(
    OnboardingSessionSummary
):
    context_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
    )


class OnboardingSessionDetail(
    OnboardingSessionRead
):
    flow: OnboardingFlowSummary | None = None

    flow_version: OnboardingFlowVersionRead | None = None

    answers: list[OnboardingAnswerRead] = Field(
        default_factory=list,
    )

    requirements: list[SessionRequirementDetail] = Field(
        default_factory=list,
    )


class OnboardingSessionListResponse(SchemaBase):
    items: list[OnboardingSessionSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class CurrentStepResponse(SchemaBase):
    session_id: str
    session_key: str

    status: SessionStatus

    progress_percent: int = Field(
        ge=0,
        le=100,
    )

    current_step: OnboardingStepRead | None

    answers: list[OnboardingAnswerRead] = Field(
        default_factory=list,
    )

    blocking_requirements: list[SessionRequirementDetail] = Field(
        default_factory=list,
    )


class SessionValidationResponse(SchemaBase):
    session_id: str

    valid: bool
    complete: bool

    status: SessionStatus

    progress_percent: int = Field(
        ge=0,
        le=100,
    )

    current_step_key: str | None

    errors: list[ValidationErrorDetail] = Field(
        default_factory=list,
    )

    blocking_requirements: list[SessionRequirementDetail] = Field(
        default_factory=list,
    )


class SessionAdvanceRequest(SchemaBase):
    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


class SessionAdvanceResponse(SchemaBase):
    session: OnboardingSessionRead

    previous_step_key: str | None
    current_step: OnboardingStepRead | None

    advanced: bool

    errors: list[ValidationErrorDetail] = Field(
        default_factory=list,
    )


class SessionCompleteRequest(SchemaBase):
    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


class SessionCompleteResponse(SchemaBase):
    session: OnboardingSessionRead

    completed: bool

    errors: list[ValidationErrorDetail] = Field(
        default_factory=list,
    )

    blocking_requirements: list[SessionRequirementDetail] = Field(
        default_factory=list,
    )


class SessionAbandonRequest(SchemaBase):
    reason: str | None = Field(
        default=None,
        max_length=1000,
    )

    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


# ---------------------------------------------------------------------------
# Event schemas
# ---------------------------------------------------------------------------


class OnboardingEventCreate(SchemaBase):
    event_type: EventType

    session_id: str | None = None
    flow_id: str | None = None
    flow_version_id: str | None = None

    subject_type: SubjectType | None = None

    subject_id: str | None = Field(
        default=None,
        max_length=200,
    )

    actor_id: str | None = Field(
        default=None,
        max_length=200,
    )

    payload_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=120,
    )


class OnboardingEventRead(SchemaBase):
    id: str
    event_key: str

    session_id: str | None
    flow_id: str | None
    flow_version_id: str | None

    event_type: EventType

    subject_type: SubjectType | None
    subject_id: str | None

    actor_id: str | None

    payload_json: dict[str, Any] = Field(
        default_factory=dict,
    )

    correlation_id: str | None

    created_at: datetime


class OnboardingEventListResponse(SchemaBase):
    items: list[OnboardingEventRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)

# ---------------------------------------------------------------------------
# Router compatibility aliases
# ---------------------------------------------------------------------------

OnboardingFlowResponse = OnboardingFlowRead
OnboardingFlowVersionResponse = OnboardingFlowVersionRead
OnboardingStepResponse = OnboardingStepRead
OnboardingFieldResponse = OnboardingFieldRead
OnboardingRequirementResponse = OnboardingRequirementRead
OnboardingSessionResponse = OnboardingSessionRead
OnboardingAnswerResponse = OnboardingAnswerRead
OnboardingEventResponse = OnboardingEventRead
SessionRequirementResponse = SessionRequirementRead

OnboardingFlowVersionPublish = PublishFlowVersionRequest
OnboardingFlowVersionRetire = RetireFlowVersionRequest


# ---------------------------------------------------------------------------
# General API response schemas
# ---------------------------------------------------------------------------


class ActionResponse(SchemaBase):
    success: bool
    message: str


class ErrorResponse(SchemaBase):
    detail: str


class ValidationErrorResponse(SchemaBase):
    detail: str
    errors: list[ValidationErrorDetail] = Field(
        default_factory=list,
  )
