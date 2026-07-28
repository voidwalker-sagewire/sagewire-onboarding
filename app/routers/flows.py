from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.crud import flows as flow_crud
from app.database import get_db


router = APIRouter(
    prefix="/flows",
    tags=["Onboarding Flows"],
)


@router.post(
    "",
    response_model=schemas.OnboardingFlowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_flow(
    flow_in: schemas.OnboardingFlowCreate,
    db: Session = Depends(get_db),
) -> models.OnboardingFlow:
    """
    Create a new onboarding flow.

    A flow is the stable top-level identity. Its editable definition lives
    inside separately versioned flow-version records.
    """

    try:
        return flow_crud.create_flow(
            db,
            flow_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=schemas.OnboardingFlowListResponse,
)
def list_flows(
    flow_status: models.FlowStatus | None = Query(
        default=None,
        alias="status",
    ),
    subject_type: models.SubjectType | None = None,
    search: str | None = Query(
        default=None,
        min_length=1,
        max_length=200,
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
) -> schemas.OnboardingFlowListResponse:
    """
    List onboarding flows with optional filters.
    """

    items = flow_crud.list_flows(
        db,
        status=flow_status,
        subject_type=subject_type,
        search=search,
        limit=limit,
        offset=offset,
    )

    total = flow_crud.count_flows(
        db,
        status=flow_status,
        subject_type=subject_type,
        search=search,
    )

    return schemas.OnboardingFlowListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{flow_identifier}",
    response_model=schemas.OnboardingFlowResponse,
)
def get_flow(
    flow_identifier: str,
    db: Session = Depends(get_db),
) -> models.OnboardingFlow:
    """
    Retrieve a flow by UUID or stable flow key.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    return flow


@router.patch(
    "/{flow_identifier}",
    response_model=schemas.OnboardingFlowResponse,
)
def update_flow(
    flow_identifier: str,
    flow_in: schemas.OnboardingFlowUpdate,
    db: Session = Depends(get_db),
) -> models.OnboardingFlow:
    """
    Update mutable flow metadata.

    Versioned steps, fields, and requirements are not modified through this
    route.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    try:
        return flow_crud.update_flow(
            db,
            flow,
            flow_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{flow_identifier}/activate",
    response_model=schemas.OnboardingFlowResponse,
)
def activate_flow(
    flow_identifier: str,
    db: Session = Depends(get_db),
) -> models.OnboardingFlow:
    """
    Activate a flow so applications may begin new sessions from its
    published version.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    try:
        return flow_crud.set_flow_status(
            db,
            flow,
            models.FlowStatus.ACTIVE,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{flow_identifier}/deactivate",
    response_model=schemas.OnboardingFlowResponse,
)
def deactivate_flow(
    flow_identifier: str,
    db: Session = Depends(get_db),
) -> models.OnboardingFlow:
    """
    Deactivate a flow.

    Existing sessions remain attached to their immutable published
    versions, but new sessions cannot be created while the flow is
    inactive.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    try:
        return flow_crud.set_flow_status(
            db,
            flow,
            models.FlowStatus.INACTIVE,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{flow_identifier}/versions",
    response_model=schemas.OnboardingFlowVersionListResponse,
)
def list_flow_versions(
    flow_identifier: str,
    version_status: models.FlowVersionStatus | None = Query(
        default=None,
        alias="status",
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
) -> schemas.OnboardingFlowVersionListResponse:
    """
    List versions belonging to one onboarding flow.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    items = flow_crud.list_flow_versions(
        db,
        flow.id,
        status=version_status,
        limit=limit,
        offset=offset,
    )

    total = flow_crud.count_flow_versions(
        db,
        flow.id,
        status=version_status,
    )

    return schemas.OnboardingFlowVersionListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{flow_identifier}/versions",
    response_model=schemas.OnboardingFlowVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_flow_version(
    flow_identifier: str,
    version_in: schemas.OnboardingFlowVersionCreate,
    db: Session = Depends(get_db),
) -> models.OnboardingFlowVersion:
    """
    Create a new draft version for a flow.

    A version may optionally be copied from an existing version when the
    schema and CRUD layer support a source-version identifier.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    try:
        return flow_crud.create_flow_version(
            db,
            flow,
            version_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{flow_identifier}/versions/{version_identifier}",
    response_model=schemas.OnboardingFlowVersionResponse,
)
def get_flow_version(
    flow_identifier: str,
    version_identifier: str,
    include_definition: bool = Query(
        default=True,
    ),
    db: Session = Depends(get_db),
) -> models.OnboardingFlowVersion:
    """
    Retrieve a flow version by UUID, version number, or version key.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    return _resolve_version_or_404(
        db,
        flow=flow,
        version_identifier=version_identifier,
        include_definition=include_definition,
    )


@router.patch(
    "/{flow_identifier}/versions/{version_identifier}",
    response_model=schemas.OnboardingFlowVersionResponse,
)
def update_flow_version(
    flow_identifier: str,
    version_identifier: str,
    version_in: schemas.OnboardingFlowVersionUpdate,
    db: Session = Depends(get_db),
) -> models.OnboardingFlowVersion:
    """
    Update draft-version metadata.

    Published and retired versions are immutable.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    flow_version = _resolve_version_or_404(
        db,
        flow=flow,
        version_identifier=version_identifier,
        include_definition=False,
    )

    try:
        return flow_crud.update_flow_version(
            db,
            flow_version,
            version_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{flow_identifier}/versions/{version_identifier}/publish",
    response_model=schemas.OnboardingFlowVersionResponse,
)
def publish_flow_version(
    flow_identifier: str,
    version_identifier: str,
    publish_in: schemas.OnboardingFlowVersionPublish | None = None,
    db: Session = Depends(get_db),
) -> models.OnboardingFlowVersion:
    """
    Validate and publish a draft flow version.

    Publishing makes the definition immutable and available for new
    onboarding sessions.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    flow_version = _resolve_version_or_404(
        db,
        flow=flow,
        version_identifier=version_identifier,
        include_definition=True,
    )

    try:
        return flow_crud.publish_flow_version(
            db,
            flow_version,
            actor_id=(
                publish_in.actor_id
                if publish_in is not None
                else None
            ),
            correlation_id=(
                publish_in.correlation_id
                if publish_in is not None
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{flow_identifier}/versions/{version_identifier}/retire",
    response_model=schemas.OnboardingFlowVersionResponse,
)
def retire_flow_version(
    flow_identifier: str,
    version_identifier: str,
    retire_in: schemas.OnboardingFlowVersionRetire | None = None,
    db: Session = Depends(get_db),
) -> models.OnboardingFlowVersion:
    """
    Retire a published flow version.

    Existing sessions remain attached to it, but it is no longer selected
    for new sessions.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    flow_version = _resolve_version_or_404(
        db,
        flow=flow,
        version_identifier=version_identifier,
        include_definition=False,
    )

    try:
        return flow_crud.retire_flow_version(
            db,
            flow_version,
            actor_id=(
                retire_in.actor_id
                if retire_in is not None
                else None
            ),
            correlation_id=(
                retire_in.correlation_id
                if retire_in is not None
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{flow_identifier}/published",
    response_model=schemas.OnboardingFlowVersionResponse,
)
def get_published_flow_version(
    flow_identifier: str,
    db: Session = Depends(get_db),
) -> models.OnboardingFlowVersion:
    """
    Retrieve the currently published version selected for new sessions.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    flow_version = (
        flow_crud.get_published_flow_version(
            db,
            flow.id,
            include_definition=True,
        )
    )

    if flow_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "this flow does not have a published "
                "version"
            ),
        )

    return flow_version


@router.post(
    "/{flow_identifier}/versions/{version_identifier}/steps",
    response_model=schemas.OnboardingStepResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_step(
    flow_identifier: str,
    version_identifier: str,
    step_in: schemas.OnboardingStepCreate,
    db: Session = Depends(get_db),
) -> models.OnboardingStep:
    """
    Add a step to a draft flow version.
    """

    flow, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    try:
        return flow_crud.create_step(
            db,
            flow_version,
            step_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{flow_identifier}/versions/{version_identifier}/steps/{step_identifier}",
    response_model=schemas.OnboardingStepResponse,
)
def update_step(
    flow_identifier: str,
    version_identifier: str,
    step_identifier: str,
    step_in: schemas.OnboardingStepUpdate,
    db: Session = Depends(get_db),
) -> models.OnboardingStep:
    """
    Update a step inside a draft flow version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    step = _resolve_step_or_404(
        db,
        flow_version=flow_version,
        step_identifier=step_identifier,
    )

    try:
        return flow_crud.update_step(
            db,
            step,
            step_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{flow_identifier}/versions/{version_identifier}/steps/{step_identifier}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_step(
    flow_identifier: str,
    version_identifier: str,
    step_identifier: str,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a step from a draft version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    step = _resolve_step_or_404(
        db,
        flow_version=flow_version,
        step_identifier=step_identifier,
    )

    try:
        flow_crud.delete_step(
            db,
            step,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{flow_identifier}/versions/{version_identifier}/steps/{step_identifier}/fields",
    response_model=schemas.OnboardingFieldResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_field(
    flow_identifier: str,
    version_identifier: str,
    step_identifier: str,
    field_in: schemas.OnboardingFieldCreate,
    db: Session = Depends(get_db),
) -> models.OnboardingField:
    """
    Add a field to a step in a draft flow version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    step = _resolve_step_or_404(
        db,
        flow_version=flow_version,
        step_identifier=step_identifier,
    )

    try:
        return flow_crud.create_field(
            db,
            flow_version,
            step,
            field_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{flow_identifier}/versions/{version_identifier}/fields/{field_identifier}",
    response_model=schemas.OnboardingFieldResponse,
)
def update_field(
    flow_identifier: str,
    version_identifier: str,
    field_identifier: str,
    field_in: schemas.OnboardingFieldUpdate,
    db: Session = Depends(get_db),
) -> models.OnboardingField:
    """
    Update a field in a draft flow version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    onboarding_field = _resolve_field_or_404(
        db,
        flow_version=flow_version,
        field_identifier=field_identifier,
    )

    try:
        return flow_crud.update_field(
            db,
            onboarding_field,
            field_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{flow_identifier}/versions/{version_identifier}/fields/{field_identifier}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_field(
    flow_identifier: str,
    version_identifier: str,
    field_identifier: str,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a field from a draft flow version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    onboarding_field = _resolve_field_or_404(
        db,
        flow_version=flow_version,
        field_identifier=field_identifier,
    )

    try:
        flow_crud.delete_field(
            db,
            onboarding_field,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/{flow_identifier}/versions/{version_identifier}/requirements",
    response_model=schemas.OnboardingRequirementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement(
    flow_identifier: str,
    version_identifier: str,
    requirement_in: schemas.OnboardingRequirementCreate,
    db: Session = Depends(get_db),
) -> models.OnboardingRequirement:
    """
    Add a requirement definition to a draft flow version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    try:
        return flow_crud.create_requirement(
            db,
            flow_version,
            requirement_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{flow_identifier}/versions/{version_identifier}/requirements/{requirement_identifier}",
    response_model=schemas.OnboardingRequirementResponse,
)
def update_requirement(
    flow_identifier: str,
    version_identifier: str,
    requirement_identifier: str,
    requirement_in: schemas.OnboardingRequirementUpdate,
    db: Session = Depends(get_db),
) -> models.OnboardingRequirement:
    """
    Update a requirement definition in a draft flow version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    requirement = _resolve_requirement_or_404(
        db,
        flow_version=flow_version,
        requirement_identifier=requirement_identifier,
    )

    try:
        return flow_crud.update_requirement(
            db,
            requirement,
            requirement_in,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{flow_identifier}/versions/{version_identifier}/requirements/{requirement_identifier}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_requirement(
    flow_identifier: str,
    version_identifier: str,
    requirement_identifier: str,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a requirement definition from a draft flow version.
    """

    _, flow_version = _resolve_draft_version(
        db,
        flow_identifier,
        version_identifier,
    )

    requirement = _resolve_requirement_or_404(
        db,
        flow_version=flow_version,
        requirement_identifier=requirement_identifier,
    )

    try:
        flow_crud.delete_requirement(
            db,
            requirement,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{flow_identifier}/versions/{version_identifier}/definition",
    response_model=schemas.OnboardingFlowDefinitionResponse,
)
def get_flow_definition(
    flow_identifier: str,
    version_identifier: str,
    db: Session = Depends(get_db),
) -> Any:
    """
    Retrieve the complete immutable application-facing definition for a
    flow version.
    """

    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    flow_version = _resolve_version_or_404(
        db,
        flow=flow,
        version_identifier=version_identifier,
        include_definition=True,
    )

    return flow_crud.build_flow_definition(
        flow_version
    )


def _resolve_flow_or_404(
    db: Session,
    flow_identifier: str,
) -> models.OnboardingFlow:
    flow = flow_crud.get_flow(
        db,
        flow_identifier,
    )

    if flow is None:
        flow = flow_crud.get_flow_by_key(
            db,
            flow_identifier,
        )

    if flow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"onboarding flow "
                f"'{flow_identifier}' was not found"
            ),
        )

    return flow


def _resolve_version_or_404(
    db: Session,
    *,
    flow: models.OnboardingFlow,
    version_identifier: str,
    include_definition: bool,
) -> models.OnboardingFlowVersion:
    flow_version = flow_crud.get_flow_version(
        db,
        version_identifier,
        include_definition=include_definition,
    )

    if flow_version is None:
        try:
            version_number = int(
                version_identifier
            )
        except ValueError:
            version_number = None

        if version_number is not None:
            flow_version = (
                flow_crud.get_flow_version_by_number(
                    db,
                    flow_id=flow.id,
                    version_number=version_number,
                    include_definition=(
                        include_definition
                    ),
                )
            )

    if (
        flow_version is None
        or flow_version.flow_id != flow.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"flow version "
                f"'{version_identifier}' was not found "
                f"for flow '{flow.flow_key}'"
            ),
        )

    return flow_version


def _resolve_draft_version(
    db: Session,
    flow_identifier: str,
    version_identifier: str,
) -> tuple[
    models.OnboardingFlow,
    models.OnboardingFlowVersion,
]:
    flow = _resolve_flow_or_404(
        db,
        flow_identifier,
    )

    flow_version = _resolve_version_or_404(
        db,
        flow=flow,
        version_identifier=version_identifier,
        include_definition=True,
    )

    if (
        flow_version.status
        != models.FlowVersionStatus.DRAFT
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "only draft flow versions may be "
                "modified"
            ),
        )

    return flow, flow_version


def _resolve_step_or_404(
    db: Session,
    *,
    flow_version: models.OnboardingFlowVersion,
    step_identifier: str,
) -> models.OnboardingStep:
    step = flow_crud.get_step(
        db,
        step_identifier,
    )

    if step is None:
        step = flow_crud.get_step_by_key(
            db,
            flow_version_id=flow_version.id,
            step_key=step_identifier,
        )

    if (
        step is None
        or step.flow_version_id != flow_version.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"step '{step_identifier}' was not "
                "found in this flow version"
            ),
        )

    return step


def _resolve_field_or_404(
    db: Session,
    *,
    flow_version: models.OnboardingFlowVersion,
    field_identifier: str,
) -> models.OnboardingField:
    onboarding_field = flow_crud.get_field(
        db,
        field_identifier,
    )

    if onboarding_field is None:
        onboarding_field = (
            flow_crud.get_field_by_key(
                db,
                flow_version_id=flow_version.id,
                field_key=field_identifier,
            )
        )

    if (
        onboarding_field is None
        or onboarding_field.flow_version_id
        != flow_version.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"field '{field_identifier}' was not "
                "found in this flow version"
            ),
        )

    return onboarding_field


def _resolve_requirement_or_404(
    db: Session,
    *,
    flow_version: models.OnboardingFlowVersion,
    requirement_identifier: str,
) -> models.OnboardingRequirement:
    requirement = flow_crud.get_requirement(
        db,
        requirement_identifier,
    )

    if requirement is None:
        requirement = (
            flow_crud.get_requirement_by_key(
                db,
                flow_version_id=flow_version.id,
                requirement_key=(
                    requirement_identifier
                ),
            )
        )

    if (
        requirement is None
        or requirement.flow_version_id
        != flow_version.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"requirement "
                f"'{requirement_identifier}' was not "
                "found in this flow version"
            ),
        )

    return requirement
