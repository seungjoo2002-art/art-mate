"""v0.5.1 API 표면: 제외 기능 라우터 미노출, 선택지 API, 신규 필드 스키마 (DB 없이)."""

import httpx
import pytest

from app.main import create_app
from app.models.enums import (
    PRACTICAL_TYPE_LABELS,
    WORK_CATEGORY_LABELS,
    WORK_STATUS_LABELS,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    PracticalType,
)
from tests.conftest import make_settings, running_client

# 기획 변경으로 제외한 기능의 경로 조각 (OpenAPI에 나오면 안 된다)
REMOVED_PATH_PARTS = (
    "/attendance",
    "/personal-todos",
    "/users/me/today",
    "/dashboard",
    "/exam-templates",
    "/exam-sessions",
    "/exams",
    "/help-queue",
    "/help-requests",
    "/help",
)
REMOVED_TAGS = {"attendance", "personal-todos", "dashboard", "exams", "help"}


@pytest.fixture
def openapi() -> dict:  # type: ignore[type-arg]
    return create_app(make_settings(app_env="development")).openapi()


def test_removed_features_are_not_in_openapi(openapi: dict) -> None:  # type: ignore[type-arg]
    paths = list(openapi["paths"])
    leaked = [p for p in paths if any(part in p for part in REMOVED_PATH_PARTS)]
    assert leaked == []
    tags = {tag for op in openapi["paths"].values() for spec in op.values() for tag in spec["tags"]}
    assert not (tags & REMOVED_TAGS)
    schemas = set(openapi["components"]["schemas"])
    for name in ("Attendance", "PersonalTodo", "Dashboard", "Exam", "HelpRequest", "StudentToday"):
        assert not [s for s in schemas if s.startswith(name)], name


def test_kept_features_are_still_exposed(openapi: dict) -> None:  # type: ignore[type-arg]
    paths = set(openapi["paths"])
    for path in (
        "/api/v1/users/me",
        "/api/v1/meta/options",
        "/api/v1/artworks",
        "/api/v1/artworks/{artwork_id}/complete",
        "/api/v1/artworks/{artwork_id}/reopen",
        "/api/v1/artworks/{artwork_id}/recordings",
        "/api/v1/academies/{academy_id}/artworks",
        "/api/v1/academies/{academy_id}/classes",
        "/api/v1/academies/{academy_id}/tasks",
        "/api/v1/academies/{academy_id}/schedules",
        "/api/v1/recording-consents",
    ):
        assert path in paths, path


def test_new_fields_in_openapi(openapi: dict) -> None:  # type: ignore[type-arg]
    schemas = openapi["components"]["schemas"]
    artwork = schemas["ArtworkRead"]
    for field in (
        "practical_type",
        "work_category",
        "work_status",
        "completed_at",
        "recording_count",
    ):
        assert field in artwork["required"], field
    assert "practical_type" in schemas["MeRead"]["properties"]
    assert "practical_type" in schemas["ProfileUpdate"]["properties"]
    assert "practical_type" in schemas["ProfileCreate"]["properties"]
    assert "practical_type" not in schemas["ProfileCreate"].get("required", [])
    params = {p["name"] for p in openapi["paths"]["/api/v1/artworks"]["get"]["parameters"]}
    assert {"practical_type", "work_category", "work_status", "limit", "offset"} <= params


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/academies/00000000-0000-0000-0000-000000000000/attendance/check-in"),
        ("GET", "/api/v1/users/me/today"),
        ("GET", "/api/v1/personal-todos"),
        ("GET", "/api/v1/academies/00000000-0000-0000-0000-000000000000/dashboard"),
        ("GET", "/api/v1/academies/00000000-0000-0000-0000-000000000000/exam-templates"),
        ("POST", "/api/v1/academies/00000000-0000-0000-0000-000000000000/classes/x/help-requests"),
    ],
)
async def test_removed_routes_return_404(method: str, path: str) -> None:
    async with running_client(create_app(make_settings())) as client:
        response = await client.request(method, path)
    assert response.status_code in (404, 405), response.text


async def test_options_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/meta/options")
    assert response.status_code == 200
    assert "max-age" in response.headers["cache-control"]
    body = response.json()
    assert body["practical_types"] == [
        {"code": "BASIC_DESIGN", "label": "기초디자인"},
        {"code": "THINKING_SHIFT", "label": "사고의 전환"},
        {"code": "IDEA_EXPRESSION", "label": "발상과 표현"},
        {"code": "DRAWING", "label": "소묘"},
        {"code": "WATERCOLOR", "label": "수채화"},
        {"code": "OTHER", "label": "기타"},
    ]
    assert [o["code"] for o in body["work_categories"]] == [
        "MOCK_EXAM",
        "PERSONAL_PRACTICE",
        "CLASS_WORK",
    ]
    assert [o["code"] for o in body["work_statuses"]] == ["IN_PROGRESS", "COMPLETED"]


def test_every_enum_value_has_a_label() -> None:
    assert set(PRACTICAL_TYPE_LABELS) == set(PracticalType)
    assert set(WORK_CATEGORY_LABELS) == set(ArtworkWorkCategory)
    assert set(WORK_STATUS_LABELS) == set(ArtworkWorkStatus)
    # DB CHECK 제약 컬럼 길이(varchar 20) 안에 들어가야 한다
    for enum in (PracticalType, ArtworkWorkCategory, ArtworkWorkStatus):
        assert all(len(v.value) <= 20 for v in enum)
