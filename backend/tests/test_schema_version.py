"""v0.9.9 DB 스키마 버전 안전장치 (판정·배포 전 점검 스크립트·/health/db 응답)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.db import schema_version
from app.db.schema_version import CodeRevisions, code_revisions, compare
from app.main import create_app
from scripts import check_db_revision
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings, running_client

CODE = CodeRevisions(heads=("0015",), known=frozenset({"0013", "0014", "0015"}))


@pytest.mark.parametrize(
    ("db", "status", "failing"),
    [
        (["0015"], "ok", False),
        (["0014"], "behind", True),  # v0.9.8 장애: 코드가 마이그레이션보다 먼저 배포
        (["0013"], "behind", True),
        (["0016"], "ahead", False),  # 마이그레이션 선적용 (정상 순서)
        ([], "missing", True),
    ],
)
def test_compare(db: list[str], status: str, failing: bool) -> None:
    check = compare(db, CODE)
    assert (check.status, check.failing, check.code_revision) == (status, failing, "0015")
    assert check.db_revision == (db[0] if db else None)


def test_compare_without_migration_files_is_unknown_not_failing() -> None:
    check = compare(["0015"], None)
    assert (check.status, check.failing, check.code_revision) == ("unknown", False, None)


def test_code_revisions_reads_this_repository() -> None:
    revisions = code_revisions()
    assert revisions is not None
    versions = Path(schema_version.ALEMBIC_DIR, "versions").glob("*.py")
    latest = max(p.name.split("_")[2] for p in versions)  # YYYYMMDD_HHMM_NNNN_...
    assert revisions.heads == (latest,)
    assert latest in revisions.known and len(revisions.known) >= 15


def test_code_revisions_missing_directory(tmp_path: Path) -> None:
    assert code_revisions(str(tmp_path)) is None


@pytest.mark.parametrize(
    ("db", "exit_code"), [(["0015"], 0), (["0016"], 0), (["0014"], 1), ([], 1)]
)
def test_check_script_exit_codes(db, exit_code, capsys) -> None:  # type: ignore[no-untyped-def]
    with (
        patch.object(check_db_revision, "_db_revisions", AsyncMock(return_value=db)),
        patch.object(check_db_revision, "code_revisions", return_value=CODE),
    ):
        assert check_db_revision.main() == exit_code
    out = capsys.readouterr().out
    assert "schema_status=" in out and "postgresql" not in out


def test_check_script_hides_connection_errors(capsys) -> None:  # type: ignore[no-untyped-def]
    err = RuntimeError("postgresql://user:secret-pw@host/db refused")
    with patch.object(check_db_revision, "_db_revisions", AsyncMock(side_effect=err)):
        assert check_db_revision.main() == 2
    captured = capsys.readouterr()
    assert "secret-pw" not in captured.err + captured.out
    assert "RuntimeError" in captured.err


async def _health(revisions: list[str]):  # type: ignore[no-untyped-def]
    app = create_app(make_settings(database_url=UNREACHABLE_DATABASE_URL))
    async with running_client(app) as client:
        with (
            patch.object(app.state.database, "ping", AsyncMock(return_value=None)),
            patch.object(app.state.database, "schema_revisions", AsyncMock(return_value=revisions)),
            patch("app.api.v1.endpoints.health.code_revisions", return_value=CODE),
        ):
            return await client.get("/api/v1/health/db")


async def test_health_db_ok_and_ahead() -> None:
    ok = await _health(["0015"])
    assert ok.status_code == 200
    assert {k: ok.json()[k] for k in ("schema_status", "db_revision", "code_revision")} == {
        "schema_status": "ok",
        "db_revision": "0015",
        "code_revision": "0015",
    }
    ahead = await _health(["0016"])
    assert ahead.status_code == 200 and ahead.json()["schema_status"] == "ahead"


async def test_health_db_behind_is_503_with_clear_code() -> None:
    response = await _health(["0014"])
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DATABASE_SCHEMA_MISMATCH"
    assert "apply migrations" in error["message"]
    assert error["details"] == {
        "schema_status": "behind",
        "db_revision": "0014",
        "code_revision": "0015",
    }
    for secret in ("super-secret-pw", "artmate_user", "127.0.0.1", "postgresql"):
        assert secret not in response.text
