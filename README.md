# SageWire Onboarding

Reusable onboarding engine for SageWire applications.

**Service:** `sagewire-onboarding`  
**Current production version:** `0.1.0`  
**Production service:** `https://onboarding.sagewire.dev`  
**Application gateway:** `https://api.sagewire.dev/onboarding`  
**API base through Gateway:** `https://api.sagewire.dev/onboarding/api/v1`

> Consumer applications should use the SageWire API Gateway. They should not call the Onboarding service origin directly.

## Purpose

SageWire Onboarding provides a shared, versioned onboarding engine so individual SageWire applications do not need to rebuild their own setup workflow system.

The service owns:

- stable flow identities
- immutable published flow versions
- ordered steps and fields
- field validation
- conditional visibility
- runtime onboarding sessions
- answer storage
- external/internal requirements
- completion evaluation
- session lifecycle state

A product may depend on this service. This service must not depend on a product.

## Stack

- Python
- FastAPI
- SQLAlchemy
- Pydantic
- SQLite
- Uvicorn
- Docker
- Coolify

Production database readiness is exposed through `/ready`.

## Service health

Direct service health endpoints:

```text
GET https://onboarding.sagewire.dev/health
GET https://onboarding.sagewire.dev/ready
```

Verified production responses as of 2026-09-06:

```json
{
  "service": "sagewire-onboarding",
  "status": "ok",
  "version": "0.1.0"
}
```

```json
{
  "service": "sagewire-onboarding",
  "status": "ready",
  "version": "0.1.0",
  "database": "available"
}
```

Interactive API documentation:

```text
https://onboarding.sagewire.dev/docs
https://onboarding.sagewire.dev/redoc
https://onboarding.sagewire.dev/openapi.json
```

## Gateway integration

SageWire API Gateway v1.1.0 exposes the Onboarding service through the bounded namespace:

```text
https://api.sagewire.dev/onboarding
```

The Gateway is not an arbitrary open proxy. The Onboarding upstream is fixed by the Gateway service registry.

Verified Gateway paths include:

```text
GET  /onboarding/health
GET  /onboarding/ready
GET  /onboarding/api/v1/flows
POST /onboarding/api/v1/flows

GET  /onboarding/api/v1/flows/{flow_identifier}/versions
GET  /onboarding/api/v1/flows/{flow_identifier}/versions/{version_identifier}
POST /onboarding/api/v1/flows/{flow_identifier}/versions/{version_identifier}/publish

POST /onboarding/api/v1/sessions
GET  /onboarding/api/v1/sessions/{session_identifier}

PUT  /onboarding/api/v1/sessions/{session_identifier}/answers
GET  /onboarding/api/v1/sessions/{session_identifier}/answers

GET  /onboarding/api/v1/sessions/{session_identifier}/requirements
POST /onboarding/api/v1/sessions/{session_identifier}/requirements/{requirement_key}/satisfy

POST /onboarding/api/v1/sessions/{session_identifier}/complete
```

The list above records routes specifically exercised during production verification.

## Flow model

A flow is the stable top-level identity. Its editable definition lives in separately versioned flow-version records.

Typical lifecycle:

```text
Flow
  └── Version 1 (DRAFT)
        ├── Steps
        │     └── Fields
        └── Requirements

DRAFT
  ↓ publish
PUBLISHED
  ↓ later retirement if needed
RETIRED
```

Published versions are immutable and can be assigned to new onboarding sessions.

## Runtime model

An onboarding session is bound to one immutable flow version.

Observed runtime state includes:

- `NOT_STARTED`
- `IN_PROGRESS`
- `COMPLETED`

Runtime processing includes:

1. create a session against a published flow
2. write answers
3. validate visible fields
4. evaluate conditional visibility
5. evaluate requirements
6. calculate progress and completion readiness
7. explicitly complete the session when ready

A session may reach `progress_percent: 100` and still remain `IN_PROGRESS` until `/complete` is called.

Use `status` as the authoritative lifecycle state. `current_step_key` is a navigation/runtime cursor, not the completion signal. After persisted completion, `current_step_key` is cleared to `null`.

## Current production flows

### `production.smoke-test`

Existing production verification flow.

- Flow ID: `009fbe82-610f-4b79-b654-a003025fc2a4`
- Status: `ACTIVE`

### `ellis-setup`

Platform-owned onboarding flow for Ellis.

- Flow ID: `200c119c-52da-4bce-8d66-ae9eea0d9606`
- Version: `1`
- Version ID: `69322c8a-1852-44ca-b740-295425e3b5a3`
- Version status: `PUBLISHED`
- Published: `2026-09-06T12:06:19.085066Z`
- Subject type: `ORGANIZATION`

#### Steps and fields

**Step: `operation` — Your Operation**

- `operation_name` — required `TEXT`
- `contact_email` — required `TEXT`

**Step: `sheet_setup` — Google Sheet Setup**

- `has_existing_sheet` — required `BOOLEAN`
- `existing_sheet_id` — required `TEXT` only when visible

Visibility rule for `existing_sheet_id`:

```json
{
  "mode": "all",
  "conditions": [
    {
      "field_key": "has_existing_sheet",
      "operator": "equals",
      "value": true
    }
  ]
}
```

When `has_existing_sheet` is `false`, `existing_sheet_id` is hidden and is not treated as required.

#### External requirement

```text
requirement_key: ellis_sheet_provisioned
source: EXTERNAL
provider_key: ellis-sheet-provisioner
required: true
```

Ellis should satisfy this requirement only after Google Sheets provisioning succeeds. The real Google Sheet ID should be written back as `external_reference`.

## Ellis ownership boundary

SageWire owns the `ellis-setup` flow definition and publication lifecycle.

Ellis must not create, modify, or publish onboarding flows at runtime.

Ellis should:

1. create or retrieve an `ellis-setup` session through the Gateway
2. read/write session answers through the Gateway
3. provision the customer's Google Sheet
4. satisfy `ellis_sheet_provisioned` with the real Sheet ID
5. complete the onboarding session when the service reports `can_complete: true`

Ellis should use:

```text
https://api.sagewire.dev/onboarding/api/v1
```

and must not use the Onboarding service origin directly for normal application runtime access.

## Production verification — 2026-09-06

`ellis-setup` v1 passed platform-side end-to-end verification through `api.sagewire.dev`.

Verified:

- flow creation
- draft version retrieval
- flow-version publication
- session creation
- session retrieval by UUID
- session retrieval by stable session key
- bulk answer writes
- answer persistence
- `TEXT` validation
- `BOOLEAN` validation
- conditional field visibility
- hidden required-field suppression
- runtime requirement materialization
- requirement listing
- requirement satisfaction
- persisted `PENDING → SATISFIED` transition
- validation calculation
- step completion calculation
- progress calculation
- progress persistence
- explicit session completion
- persisted `COMPLETED` lifecycle state
- persisted `completed_at`
- clearing `current_step_key` after completion

Production verification session:

```text
session_key: ellis_setup_test_20260906_001
session_id: 450ef0e4-1a02-4fb8-97ac-c69c92f87488
final status: COMPLETED
progress_percent: 100
```

The requirement satisfaction used during this platform smoke test was explicitly marked `test_only: true`. It verified the Onboarding/Gateway path, not real Google Sheets provisioning.

## Known implementation note

The requirements-list response previously failed with a Pydantic `ValidationError` because the router returned pagination fields that were not declared by `SessionRequirementListResponse`.

The response schema was corrected to include:

```python
class SessionRequirementListResponse(SchemaBase):
    items: list[SessionRequirementDetail]
    total: int = Field(ge=0)
    limit: int
    offset: int
```

After redeployment, the route was re-tested through the Gateway and returned the expected paginated response.

A later hardening pass may align the schema constraints with the endpoint contract:

- `limit`: minimum 1, maximum 1000
- `offset`: minimum 0

This is not currently a production blocker.

## Current boundary of verification

The Onboarding platform path for Ellis is verified.

The remaining Ellis-specific integration work is outside this service:

- actually creating or modifying the Google Sheet
- sharing it with the customer
- reporting the real Sheet ID back through `ellis_sheet_provisioned`

Those actions belong to Ellis, not SageWire Onboarding.
