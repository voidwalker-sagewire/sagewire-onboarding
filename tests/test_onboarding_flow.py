def test_full_user_onboarding_happy_path(client):
    # 1. Create the flow.
    response = client.post(
        "/api/v1/flows",
        json={
            "flow_key": "test.user-onboarding",
            "name": "Test User Onboarding",
            "description": "End-to-end onboarding regression test.",
            "metadata_json": {
                "test": True,
            },
        },
    )

    assert response.status_code == 201, response.text

    flow = response.json()

    assert flow["flow_key"] == "test.user-onboarding"


    # 2. Create version 1 with three steps and seven fields.
    response = client.post(
        "/api/v1/flows/test.user-onboarding/versions",
        json={
            "title": "Test User Onboarding v1",
            "description": "Happy-path regression definition.",
            "subject_type": "USER",
            "version_number": 1,
            "metadata_json": {
                "test": True,
            },
            "steps": [
                {
                    "step_key": "identity",
                    "title": "Your Identity",
                    "position": 1,
                    "fields": [
                        {
                            "field_key": "full_name",
                            "label": "Full Name",
                            "field_type": "TEXT",
                            "position": 1,
                            "required": True,
                        },
                        {
                            "field_key": "preferred_name",
                            "label": "Preferred Name",
                            "field_type": "TEXT",
                            "position": 2,
                            "required": False,
                        },
                        {
                            "field_key": "email",
                            "label": "Email",
                            "field_type": "EMAIL",
                            "position": 3,
                            "required": True,
                        },
                    ],
                },
                {
                    "step_key": "organization",
                    "title": "Organization",
                    "position": 2,
                    "fields": [
                        {
                            "field_key": "organization_name",
                            "label": "Organization Name",
                            "field_type": "TEXT",
                            "position": 1,
                            "required": True,
                        },
                        {
                            "field_key": "role",
                            "label": "Role",
                            "field_type": "TEXT",
                            "position": 2,
                            "required": True,
                        },
                    ],
                },
                {
                    "step_key": "preferences",
                    "title": "Preferences",
                    "position": 3,
                    "fields": [
                        {
                            "field_key": "timezone",
                            "label": "Timezone",
                            "field_type": "TEXT",
                            "position": 1,
                            "required": True,
                            "default_value_json": "America/New_York",
                        },
                        {
                            "field_key": "notifications_enabled",
                            "label": "Notifications Enabled",
                            "field_type": "BOOLEAN",
                            "position": 2,
                            "required": True,
                            "default_value_json": True,
                        },
                    ],
                },
            ],
            "requirements": [],
        },
    )

    assert response.status_code == 201, response.text

    version = response.json()

    assert version["version_number"] == 1


    # 3. Publish the version.
    response = client.post(
        "/api/v1/flows/test.user-onboarding/versions/1/publish",
        json={
            "actor_id": "pytest",
            "correlation_id": "publish-test-user-onboarding-v1",
        },
    )

    assert response.status_code == 200, response.text

    published = response.json()

    assert published["status"] == "PUBLISHED"


    # 4. Create a new onboarding session.
    response = client.post(
        "/api/v1/sessions",
        json={
            "session_key": "test-user-onboarding-session-001",
            "flow_key": "test.user-onboarding",
            "version_number": 1,
            "subject_type": "USER",
            "subject_id": "pytest-user",
            "context_json": {
                "environment": "test",
                "purpose": "happy-path integration test",
            },
            "metadata_json": {
                "test": True,
            },
            "correlation_id": "create-test-user-onboarding-session-001",
        },
    )

    assert response.status_code == 201, response.text

    session = response.json()

    assert session["status"] == "NOT_STARTED"
    assert session["current_step_key"] == "identity"
    assert session["progress_percent"] == 0


    # 5. Submit all seven answers atomically.
    response = client.put(
        "/api/v1/sessions/test-user-onboarding-session-001/answers",
        json={
            "answers": [
                {
                    "field_key": "full_name",
                    "value_json": "Test User",
                },
                {
                    "field_key": "preferred_name",
                    "value_json": "Tester",
                },
                {
                    "field_key": "email",
                    "value_json": "tester@example.com",
                },
                {
                    "field_key": "organization_name",
                    "value_json": "SageWire Test",
                },
                {
                    "field_key": "role",
                    "value_json": "Tester",
                },
                {
                    "field_key": "timezone",
                    "value_json": "America/New_York",
                },
                {
                    "field_key": "notifications_enabled",
                    "value_json": True,
                },
            ],
            "answered_by": "pytest",
            "correlation_id": "test-user-onboarding-answers-001",
        },
    )

    assert response.status_code == 200, response.text

    answer_result = response.json()

    assert answer_result["total"] == 7
    assert answer_result["validation"]["valid"] is True
    assert answer_result["completion"]["can_complete"] is True
    assert answer_result["completion"]["progress_percent"] == 100


    # 6. Complete the session.
    response = client.post(
        "/api/v1/sessions/test-user-onboarding-session-001/complete",
        json={
            "actor_id": "pytest",
            "correlation_id": "complete-test-user-onboarding-session-001",
        },
    )

    assert response.status_code == 200, response.text

    completion = response.json()

    assert completion["session_status"] == "COMPLETED"
    assert completion["can_complete"] is True
    assert completion["progress_percent"] == 100


    # 7. Verify persisted final session state.
    response = client.get(
        "/api/v1/sessions/test-user-onboarding-session-001"
    )

    assert response.status_code == 200, response.text

    session = response.json()

    assert session["status"] == "COMPLETED"
    assert session["progress_percent"] == 100
    assert session["current_step_key"] is None
    assert session["started_at"] is not None
    assert session["completed_at"] is not None


    # 8. Verify all answers are readable.
    response = client.get(
        "/api/v1/sessions/test-user-onboarding-session-001/answers"
    )

    assert response.status_code == 200, response.text

    answers = response.json()

    assert answers["total"] == 7

    field_keys = {
        item["field_key"]
        for item in answers["items"]
    }

    assert field_keys == {
        "full_name",
        "preferred_name",
        "email",
        "organization_name",
        "role",
        "timezone",
        "notifications_enabled",
    }


    # 9. Verify the session audit trail.
    response = client.get(
        "/api/v1/events/sessions/test-user-onboarding-session-001"
    )

    assert response.status_code == 200, response.text

    events = response.json()

    assert events["total"] >= 10

    event_types = [
        item["event_type"]
        for item in events["items"]
    ]

    assert "onboarding.session.created" in event_types
    assert "onboarding.answer.created" in event_types
    assert "onboarding.session.completed" in event_types

    completion_events = [
        item
        for item in events["items"]
        if item["event_type"] == "onboarding.session.completed"
    ]

    assert len(completion_events) == 1

    completed_event = completion_events[0]

    assert completed_event["actor_id"] == "pytest"
    assert (
        completed_event["correlation_id"]
        == "complete-test-user-onboarding-session-001"
    )
