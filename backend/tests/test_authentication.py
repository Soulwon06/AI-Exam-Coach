from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core import config
from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(config.settings, "demo_username", "demo")
    monkeypatch.setattr(config.settings, "demo_password", "demo-password-for-tests")
    monkeypatch.setattr(config.settings, "demo_user_id", "demo-user")
    monkeypatch.setattr(config.settings, "demo_course_id", "")
    app.dependency_overrides[get_db] = override_get_db
    app.state.test_session_factory = TestingSession
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()
    del app.state.test_session_factory
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_registration_creates_a_separate_user_and_cookie_session(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": " Student_One ", "password": "a-long-password-123"},
    )
    assert response.status_code == 200
    user = response.json()["data"]
    assert user["username"] == "student_one"
    assert user["is_demo"] is False
    assert response.cookies.get(config.settings.auth_cookie_name)
    assert response.headers["set-cookie"].lower().find("httponly") >= 0

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["id"] == user["id"]


def test_registration_accepts_eight_character_password_and_rejects_shorter(client: TestClient) -> None:
    too_short = client.post(
        "/api/v1/auth/register",
        json={"username": "short_pass", "password": "1234567"},
    )
    assert too_short.status_code == 422

    minimum_length = client.post(
        "/api/v1/auth/register",
        json={"username": "eight_pass", "password": "12345678"},
    )
    assert minimum_length.status_code == 200


def test_users_cannot_read_each_others_courses(client: TestClient) -> None:
    first = client.post(
        "/api/v1/auth/register",
        json={"username": "first_user", "password": "a-long-password-123"},
    ).json()["data"]
    created = client.post("/api/v1/courses", json={"name": "First user's course"})
    assert created.status_code == 200

    second = client.post(
        "/api/v1/auth/register",
        json={"username": "second_user", "password": "another-long-password"},
    ).json()["data"]
    assert second["id"] != first["id"]
    response = client.get(f"/api/v1/users/{first['id']}/courses")
    # The route intentionally hides whether another user's collection exists.
    assert response.status_code == 404


def test_normal_login_uses_configured_username_for_prepared_course_owner(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = client.post(
        "/api/v1/auth/register",
        json={"username": "course_owner", "password": "legacy-owner-password"},
    ).json()["data"]
    created = client.post("/api/v1/courses", json={"name": "Frozen database course"})
    course_id = created.json()["data"]["id"]
    client.post("/api/v1/auth/logout", json={})
    monkeypatch.setattr(config.settings, "demo_course_id", course_id)
    db = app.state.test_session_factory()
    try:
        from app.services.auth_service import provision_configured_account

        db.query(models.AuthAccount).filter_by(user_id=owner["id"]).delete()
        db.commit()
        provision_configured_account(db)
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "demo", "password": "demo-password-for-tests"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["id"] == owner["id"]
    assert response.json()["data"]["is_demo"] is True
    courses = client.get(f"/api/v1/users/{owner['id']}/courses")
    assert [item["id"] for item in courses.json()["data"]] == [course_id]


def test_legacy_user_id_header_does_not_authenticate(client: TestClient) -> None:
    response = client.get("/api/v1/users/any-user/courses", headers={"X-User-Id": "any-user"})
    assert response.status_code == 401


def test_logout_revokes_session(client: TestClient) -> None:
    password = "a-long-password-123"
    client.post(
        "/api/v1/auth/register",
        json={"username": "logout_user", "password": password},
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", json={}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "logout_user", "password": "wrong-password"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "logout_user", "password": password},
    ).status_code == 200
