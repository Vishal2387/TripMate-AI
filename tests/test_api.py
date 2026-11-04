"""API contract tests for the travel-planning endpoints."""


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert "supervisor_agent" in body["features"]


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "TripMate AI" in response.text


def test_travel_returns_draft_awaiting_approval(client, fake_planner):
    response = client.post(
        "/api/travel",
        json={"message": "Plan a 5 day trip to Japan."},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["requires_approval"] is True
    assert body["thread_id"]
    assert fake_planner.start_calls == [
        {"user_input": "Plan a 5 day trip to Japan.", "thread_id": None}
    ]


def test_travel_message_is_stripped(client, fake_planner):
    client.post("/api/travel", json={"message": "  Tokyo trip  "})
    assert fake_planner.start_calls[0]["user_input"] == "Tokyo trip"


def test_travel_rejects_blank_message(client, fake_planner):
    response = client.post("/api/travel", json={"message": "   "})
    assert response.status_code == 400

    body = response.json()
    assert body["success"] is False
    assert "empty" in body["error"].lower()
    assert fake_planner.start_calls == []


def test_travel_rejects_missing_message(client):
    response = client.post("/api/travel", json={})
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_approve_resumes_thread(client, fake_planner):
    response = client.post(
        "/api/travel/approve",
        json={"thread_id": "thread-1", "approved": True},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["requires_approval"] is False
    assert fake_planner.resume_calls == [
        {"thread_id": "thread-1", "approved": True, "feedback": ""}
    ]


def test_reject_without_feedback_fails(client, fake_planner):
    response = client.post(
        "/api/travel/approve",
        json={"thread_id": "thread-1", "approved": False, "feedback": "  "},
    )
    assert response.status_code == 400
    assert response.json()["success"] is False
    assert fake_planner.resume_calls == []


def test_reject_with_feedback_resumes(client, fake_planner):
    response = client.post(
        "/api/travel/approve",
        json={
            "thread_id": "thread-1",
            "approved": False,
            "feedback": "Add one free day.",
        },
    )
    assert response.status_code == 200
    assert fake_planner.resume_calls[0]["feedback"] == "Add one free day."


def test_planner_error_returns_error_shape(client, fake_planner):
    async def broken_start(user_input, thread_id=None):
        raise RuntimeError("boom")

    fake_planner.start = broken_start

    response = client.post("/api/travel", json={"message": "Trip to Rome"})
    assert response.status_code == 500

    body = response.json()
    assert body["success"] is False
    assert "boom" in body["error"]
