from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class FlowStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FlowVersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SubjectType(str, enum.Enum):
    USER = "USER"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    DEVICE = "DEVICE"


class FieldType(str, enum.Enum):
    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    SELECT = "SELECT"
    MULTISELECT = "MULTISELECT"
    FILE_REFERENCE = "FILE_REFERENCE"


class SessionStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class RequirementStatus(str, enum.Enum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class RequirementSource(str, enum.Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"
    MANUAL = "MANUAL"


class EventType(str, enum.Enum):
    FLOW_CREATED = "onboarding.flow.created"
    FLOW_VERSION_CREATED = "onboarding.flow_version.created"
    FLOW_VERSION_PUBLISHED = "onboarding.flow_version.published"
    FLOW_VERSION_RETIRED = "onboarding.flow_version.retired"

    SESSION_CREATED = "onboarding.session.created"
    SESSION_STARTED = "onboarding.session.started"
    SESSION_UPDATED = "onboarding.session.updated"
    SESSION_BLOCKED = "onboarding.session.blocked"
    SESSION_COMPLETED = "onboarding.session.completed"
    SESSION_ABANDONED = "onboarding.session.abandoned"

    ANSWER_CREATED = "onboarding.answer.created"
    ANSWER_UPDATED = "onboarding.answer.updated"

    REQUIREMENT_UPDATED = "onboarding.requirement.updated"


class OnboardingFlow(Base):
    __tablename__ = "onboarding_flows"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    flow_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        unique=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[FlowStatus] = mapped_column(
        Enum(
            FlowStatus,
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=FlowStatus.ACTIVE,
        index=True,
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    versions: Mapped[list[OnboardingFlowVersion]] = relationship(
        back_populates="flow",
        cascade="all, delete-orphan",
        order_by="OnboardingFlowVersion.version_number",
    )

    sessions: Mapped[list[OnboardingSession]] = relationship(
        back_populates="flow",
    )


class OnboardingFlowVersion(Base):
    __tablename__ = "onboarding_flow_versions"

    __table_args__ = (
        UniqueConstraint(
            "flow_id",
            "version_number",
            name="uq_onboarding_flow_version",
        ),
        Index(
            "ix_onboarding_flow_versions_flow_status",
            "flow_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    flow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flows.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[FlowVersionStatus] = mapped_column(
        Enum(
            FlowVersionStatus,
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=FlowVersionStatus.DRAFT,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(
            SubjectType,
            native_enum=False,
            length=30,
        ),
        nullable=False,
        index=True,
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    flow: Mapped[OnboardingFlow] = relationship(
        back_populates="versions",
    )

    steps: Mapped[list[OnboardingStep]] = relationship(
        back_populates="flow_version",
        cascade="all, delete-orphan",
        order_by="OnboardingStep.position",
    )

    requirements: Mapped[list[OnboardingRequirement]] = relationship(
        back_populates="flow_version",
        cascade="all, delete-orphan",
        order_by="OnboardingRequirement.position",
    )

    sessions: Mapped[list[OnboardingSession]] = relationship(
        back_populates="flow_version",
    )


class OnboardingStep(Base):
    __tablename__ = "onboarding_steps"

    __table_args__ = (
        UniqueConstraint(
            "flow_version_id",
            "step_key",
            name="uq_onboarding_step_key",
        ),
        UniqueConstraint(
            "flow_version_id",
            "position",
            name="uq_onboarding_step_position",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    flow_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flow_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    step_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    optional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    visibility_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    flow_version: Mapped[OnboardingFlowVersion] = relationship(
        back_populates="steps",
    )

    fields: Mapped[list[OnboardingField]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="OnboardingField.position",
    )


class OnboardingField(Base):
    __tablename__ = "onboarding_fields"

    __table_args__ = (
        UniqueConstraint(
            "flow_version_id",
            "field_key",
            name="uq_onboarding_field_key",
        ),
        UniqueConstraint(
            "step_id",
            "position",
            name="uq_onboarding_field_position",
        ),
        Index(
            "ix_onboarding_fields_version_step",
            "flow_version_id",
            "step_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    flow_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flow_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    step_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_steps.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    field_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    label: Mapped[str] = mapped_column(
        String(250),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    placeholder: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    field_type: Mapped[FieldType] = mapped_column(
        Enum(
            FieldType,
            native_enum=False,
            length=30,
        ),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    sensitive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    default_value_json: Mapped[Any | None] = mapped_column(
        JSON,
        nullable=True,
    )

    options_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    validation_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    visibility_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    step: Mapped[OnboardingStep] = relationship(
        back_populates="fields",
    )

    answers: Mapped[list[OnboardingAnswer]] = relationship(
        back_populates="field",
    )


class OnboardingRequirement(Base):
    __tablename__ = "onboarding_requirements"

    __table_args__ = (
        UniqueConstraint(
            "flow_version_id",
            "requirement_key",
            name="uq_onboarding_requirement_key",
        ),
        UniqueConstraint(
            "flow_version_id",
            "position",
            name="uq_onboarding_requirement_position",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    flow_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flow_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    requirement_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    source: Mapped[RequirementSource] = mapped_column(
        Enum(
            RequirementSource,
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=RequirementSource.INTERNAL,
    )

    provider_key: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    configuration_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    visibility_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    flow_version: Mapped[OnboardingFlowVersion] = relationship(
        back_populates="requirements",
    )

    session_requirements: Mapped[list[OnboardingSessionRequirement]] = (
        relationship(
            back_populates="requirement",
        )
    )


class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"

    __table_args__ = (
        Index(
            "ix_onboarding_sessions_subject",
            "subject_type",
            "subject_id",
        ),
        Index(
            "ix_onboarding_sessions_flow_status",
            "flow_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    session_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        unique=True,
        index=True,
        default=new_uuid,
    )

    flow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flows.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    flow_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flow_versions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(
            SubjectType,
            native_enum=False,
            length=30,
        ),
        nullable=False,
        index=True,
    )

    subject_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )

    status: Mapped[SessionStatus] = mapped_column(
        Enum(
            SessionStatus,
            native_enum=False,
            length=30,
        ),
        nullable=False,
        default=SessionStatus.NOT_STARTED,
        index=True,
    )

    current_step_key: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    progress_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    context_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    abandoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    flow: Mapped[OnboardingFlow] = relationship(
        back_populates="sessions",
    )

    flow_version: Mapped[OnboardingFlowVersion] = relationship(
        back_populates="sessions",
    )

    answers: Mapped[list[OnboardingAnswer]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    requirements: Mapped[list[OnboardingSessionRequirement]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    events: Mapped[list[OnboardingEvent]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="OnboardingEvent.created_at",
    )


class OnboardingAnswer(Base):
    __tablename__ = "onboarding_answers"

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "field_id",
            name="uq_onboarding_answer_session_field",
        ),
        Index(
            "ix_onboarding_answers_session_field",
            "session_id",
            "field_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    field_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_fields.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    field_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )

    value_json: Mapped[Any | None] = mapped_column(
        JSON,
        nullable=True,
    )

    is_valid: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    validation_errors_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    answered_by: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    session: Mapped[OnboardingSession] = relationship(
        back_populates="answers",
    )

    field: Mapped[OnboardingField] = relationship(
        back_populates="answers",
    )


class OnboardingSessionRequirement(Base):
    __tablename__ = "onboarding_session_requirements"

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "requirement_id",
            name="uq_onboarding_session_requirement",
        ),
        Index(
            "ix_onboarding_session_requirements_status",
            "session_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    requirement_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_requirements.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    requirement_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )

    status: Mapped[RequirementStatus] = mapped_column(
        Enum(
            RequirementStatus,
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=RequirementStatus.PENDING,
        index=True,
    )

    external_reference: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    details_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    satisfied_by: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    satisfied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    session: Mapped[OnboardingSession] = relationship(
        back_populates="requirements",
    )

    requirement: Mapped[OnboardingRequirement] = relationship(
        back_populates="session_requirements",
    )


class OnboardingEvent(Base):
    __tablename__ = "onboarding_events"

    __table_args__ = (
        Index(
            "ix_onboarding_events_session_created",
            "session_id",
            "created_at",
        ),
        Index(
            "ix_onboarding_events_type_created",
            "event_type",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    event_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        unique=True,
        index=True,
        default=new_uuid,
    )

    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )

    flow_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flows.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    flow_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "onboarding_flow_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    event_type: Mapped[EventType] = mapped_column(
        Enum(
            EventType,
            native_enum=False,
            length=80,
        ),
        nullable=False,
        index=True,
    )

    subject_type: Mapped[SubjectType | None] = mapped_column(
        Enum(
            SubjectType,
            native_enum=False,
            length=30,
        ),
        nullable=True,
        index=True,
    )

    subject_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )

    actor_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )

    session: Mapped[OnboardingSession | None] = relationship(
        back_populates="events",
  )
