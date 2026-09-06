# Changelog

All notable changes and verified production milestones for SageWire Onboarding are recorded here.

This changelog was created on 2026-09-06. Earlier history is reconstructed only where it is known from the running service and production records.

## [0.1.0] — 2026-09-06

### Added

- Created the first project README and CHANGELOG documentation.
- Added and published the platform-owned `ellis-setup` flow.
- Added `ellis-setup` version 1 with subject type `ORGANIZATION`.
- Added `operation` step with:
  - `operation_name`
  - `contact_email`
- Added `sheet_setup` step with:
  - `has_existing_sheet`
  - `existing_sheet_id`
- Added conditional visibility so `existing_sheet_id` is visible and required only when `has_existing_sheet == true`.
- Added required external requirement:
  - `requirement_key`: `ellis_sheet_provisioned`
  - `provider_key`: `ellis-sheet-provisioner`
- Published `ellis-setup` v1 on 2026-09-06 at `12:06:19Z`.

### Fixed

- Fixed `GET /api/v1/sessions/{session_identifier}/requirements` response validation.
- `SessionRequirementListResponse` previously rejected router-supplied `limit` and `offset` fields because the Pydantic response schema forbade them as extras.
- Added `limit` and `offset` to `SessionRequirementListResponse`.
- Redeployed and verified the corrected paginated requirements response through the SageWire API Gateway.

### Verified

Production verification through:

```text
https://api.sagewire.dev/onboarding
```

confirmed:

- Onboarding service health
- database readiness
- flow listing
- flow creation
- draft flow-version retrieval
- flow-version publication
- session creation
- session retrieval by UUID
- session retrieval by stable session key
- bulk answer writes
- answer listing and persistence
- field validation
- Boolean answer handling
- conditional visibility
- suppression of hidden required fields
- runtime requirement materialization
- requirement listing
- requirement satisfaction
- persisted requirement state transition from `PENDING` to `SATISFIED`
- step completion calculation
- session progress calculation
- persisted 100% progress
- explicit session completion
- persisted `COMPLETED` state
- persisted `completed_at`
- clearing of `current_step_key` after completion

### Ellis production verification record

Flow:

```text
flow_key: ellis-setup
flow_id: 200c119c-52da-4bce-8d66-ae9eea0d9606
version_number: 1
version_id: 69322c8a-1852-44ca-b740-295425e3b5a3
version_status: PUBLISHED
```

Test session:

```text
session_key: ellis_setup_test_20260906_001
session_id: 450ef0e4-1a02-4fb8-97ac-c69c92f87488
final_status: COMPLETED
progress_percent: 100
```

Runtime requirement:

```text
requirement_key: ellis_sheet_provisioned
runtime_requirement_id: bc18d2ed-4bbf-4b8d-9eef-a473ac8507a8
final_status: SATISFIED
```

The requirement was satisfied using a smoke-test reference with `test_only: true`. This verified the platform route and persistence behavior only; it did not represent a real Google Sheet provisioning action.

### Observed behavior

- A session can have `progress_percent: 100` while remaining `IN_PROGRESS`.
- Session completion is explicit through `POST /api/v1/sessions/{session_identifier}/complete`.
- `status` is the authoritative lifecycle state.
- `current_step_key` should not be treated as the authoritative completion signal.
- After completion persisted, `current_step_key` was cleared to `null`.
- When `has_existing_sheet` was `false`, `existing_sheet_id` became invisible, non-blocking, and effectively non-required.

### Gateway contract confirmed for Ellis

Ellis runtime should use:

```text
https://api.sagewire.dev/onboarding/api/v1
```

Confirmed runtime routes include:

```text
POST /sessions
GET  /sessions/{session_identifier}
PUT  /sessions/{session_identifier}/answers
GET  /sessions/{session_identifier}/answers
GET  /sessions/{session_identifier}/requirements
POST /sessions/{session_identifier}/requirements/{requirement_key}/satisfy
POST /sessions/{session_identifier}/complete
```

Ellis does not own flow creation or publication.

### Remaining work outside Onboarding

The Onboarding platform path is complete enough for Ellis to proceed.

Still to be verified in Ellis itself:

- real Google Sheet creation
- adding the Ellis tab to an existing Sheet
- Google Drive sharing
- writing the real Sheet ID to `ellis_sheet_provisioned.external_reference`
- running the complete provisioning loop with a real customer/test Sheet

## Historical note

An existing production flow named `production.smoke-test` was already present before this changelog was created.

Known record:

```text
flow_key: production.smoke-test
flow_id: 009fbe82-610f-4b79-b654-a003025fc2a4
status: ACTIVE
created_at: 2026-08-09T09:36:46.093744
```

It was used for earlier production and Gateway smoke testing.
