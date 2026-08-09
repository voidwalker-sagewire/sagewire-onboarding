def _create_published_flow(client):
    response = client.post(
        "/api/v1/flows",
        json={
            "flow_key": "test.failure-onboarding",
            "name": "Failure Test Onboarding",
        },
    )
    assert response.status_code == 201, response.text

    response = client.post(
        "/api/v1/flows/test.failure-onboarding/versions",
        json={
            "title": "Failure Test v1",
            "subject_type": "USER",
            "version_number": 1,
            "steps": [
                {
                    "step_key": "identity",
                    "title": "Identity",
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
                            "field_key": "email",
                            "label": "Email",
                            "field_type": "EMAIL",
                            "position": 2,
                            "required": True,
                        },
                    ],
                }
            ],
            "requirements": [],
        },
    )
    assert response.status_code == 201, response.text

    response = client.post(
        "/api/v1/flows/test.failure-onboarding/versions/1/publish",
        json={
            "actor_id": "pytest",
            "correlation_id": "publish-failure-test-v1",
        },
    )
    assert response.status_code == 200, response.text


def _create_session(client, session_key="failure-test-session"):
    response = client.post(
        "/api/v1/sessions",
        json={
            "session_key": session_key,
            "flow_key": "test.failure-onboarding",
            "version_number": 1,
            "subject_type": "USER",
            "subject_id": "pytest-user",
            "context_json": {"environment": "test"},
            "metadata_json": {"test": True},
            "correlation_id": f"create-{session_key}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_missing_required_field_blocks_completion(client):
    _create_published_flow(client)
    _create_session(client, "missing-required-session")

    response = client.put(
        "/api/v1/sessions/missing-required-session/answers",
        json={
            "answers": [
                {
                    "field_key": "full_name",
                    "value_json": "Test User",
                }
            ],
            "answered_by": "pytest",
            "correlation_id": "missing-required-answer",
        },
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["completion"]["can_complete"] is False
    assert "email" in body["completion"]["blocking_field_keys"]

    response = client.post(
        "/api/v1/sessions/missing-required-session/complete",
        json={
            "actor_id": "pytest",
            "correlation_id": "missing-required-complete",
        },
    )

    assert response.status_code == 422


def test_invalid_email_fails_validation(client):
    _create_published_flow(client)
    _create_session(client, "invalid-email-session")

    response = client.put(
        "/api/v1/sessions/invalid-email-session/answers",
        json={
            "answers": [
                {
                    "field_key": "full_name",
                    "value_json": "Test User",
                },
                {
                    "field_key": "email",
                    "value_json": "not-an-email",
                },
            ],
            "answered_by": "pytest",
            "correlation_id": "invalid-email-answers",
        },
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["validation"]["valid"] is False
    assert body["completion"]["can_complete"] is False
    assert "email" in body["completion"]["blocking_field_keys"]


def test_unknown_field_key_is_rejected(client):
    _create_published_flow(client)
    _create_session(client, "unknown-field-session")

    response = client.put(
        "/api/v1/sessions/unknown-field-session/answers",
        json={
            "answers": [
                {
                    "field_key": "does_not_exist",
                    "value_json": "bad",
                }
            ],
            "answered_by": "pytest",
            "correlation_id": "unknown-field-answer",
        },
    )

    assert response.status_code == 422


def test_premature_completion_is_rejected(client):
    _create_published_flow(client)
    _create_session(client, "premature-complete-session")

    response = client.post(
        "/api/v1/sessions/premature-complete-session/complete",
        json={
            "actor_id": "pytest",
            "correlation_id": "premature-complete",
        },
    )

    assert response.status_code == 422

    response = client.get(
        "/api/v1/sessions/premature-complete-session"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] != "COMPLETED"
    assert body["completed_at"] is None


def test_completed_session_rejects_answer_modification(client):
    _create_published_flow(client)
    _create_session(client, "completed-lock-session")

    response = client.put(
        "/api/v1/sessions/completed-lock-session/answers",
        json={
            "answers": [
                {
                    "field_key": "full_name",
                    "value_json": "Test User",
                },
                {
                    "field_key": "email",
                    "value_json": "tester@example.com",
                },
            ],
            "answered_by": "pytest",
            "correlation_id": "completed-lock-answers",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["completion"]["can_complete"] is True

    response = client.post(
        "/api/v1/sessions/completed-lock-session/complete",
        json={
            "actor_id": "pytest",
            "correlation_id": "completed-lock-complete",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["session_status"] == "COMPLETED"

    response = client.put(
        "/api/v1/sessions/completed-lock-session/answers/email",
        json={
            "value_json": "changed@example.com",
            "answered_by": "pytest",
            "correlation_id": "completed-lock-modification",
        },
    )

    assert response.status_code == 422
