"""Alembic 마이그레이션 검증: 왕복 적용, 모델과 스키마 일치, 보안 설정."""

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.db.conftest import run_alembic

_INSERT_PROFILE = "INSERT INTO profiles (id, display_name, user_type) VALUES"


def _asyncpg_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def test_upgrade_downgrade_roundtrip_and_no_model_drift(migrated_database: str) -> None:
    for args in (("downgrade", "base"), ("upgrade", "head"), ("check",)):
        result = run_alembic(*args)
        assert result.returncode == 0, f"alembic {' '.join(args)}: {result.stderr[-2000:]}"
    assert "No new upgrade operations detected" in result.stdout + result.stderr


async def test_schema_security_and_constraints(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY($1::text[])",
                ["profiles", "academies", "academy_memberships", "academy_join_requests"],
            )
        )
        constraints = {
            row["conname"]
            for row in await conn.fetch(
                "SELECT conname FROM pg_constraint WHERE conrelid = ANY(ARRAY["
                "'profiles'::regclass, 'academy_memberships'::regclass, "
                "'academy_join_requests'::regclass])"
            )
        }
        indexes = {
            row["indexname"]
            for row in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'academy_join_requests'"
            )
        }
    finally:
        await conn.close()

    assert rls == dict.fromkeys(rls, True) and len(rls) == 4
    assert {
        "uq_academy_memberships_academy_id_user_id",
        "ck_academy_join_requests_requested_role_allowed",
        "ck_profiles_display_name_not_blank",
        "ck_profiles_user_type",
    } <= constraints
    assert "uq_academy_join_requests_pending" in indexes


@pytest.mark.parametrize(
    "sql",
    [
        f"{_INSERT_PROFILE} (gen_random_uuid(), 'x', 'ROOT')",
        f"{_INSERT_PROFILE} (gen_random_uuid(), '  ', 'STUDENT')",
    ],
)
async def test_database_rejects_invalid_values(migrated_database: str, sql: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(sql)
    finally:
        await conn.close()


V03_TABLES = [
    "classes",
    "class_memberships",
    "class_schedules",
    "schedule_exceptions",
    "attendance_records",
    "attendance_audit_logs",
    "lesson_topics",
    "tasks",
    "task_assignments",
    "personal_todos",
]


async def test_v03_schema_rls_constraints_and_indexes(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class "
                "WHERE relname = ANY($1::text[]) AND relkind = 'r'",
                V03_TABLES,
            )
        )
        constraints = {
            row["conname"]
            for row in await conn.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid::regclass::text = ANY($1::text[])",
                [*V03_TABLES, "academy_memberships"],
            )
        }
        indexes = {
            row["indexname"]
            for row in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", V03_TABLES
            )
        }
        timestamps = await conn.fetch(
            "SELECT table_name, count(*) FROM information_schema.columns "
            "WHERE table_name = ANY($1::text[]) AND column_name IN ('created_at', 'updated_at') "
            "AND data_type = 'timestamp with time zone' GROUP BY table_name",
            V03_TABLES,
        )
        uuid_pks = await conn.fetch(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_name = ANY($1::text[]) AND column_name = 'id' AND data_type = 'uuid'",
            V03_TABLES,
        )
    finally:
        await conn.close()

    assert rls == dict.fromkeys(V03_TABLES, True)
    assert {row["table_name"]: row["count"] for row in timestamps} == dict.fromkeys(V03_TABLES, 2)
    assert {row["table_name"] for row in uuid_pks} == set(V03_TABLES)
    assert {
        # 중복 출석 방지
        "uq_attendance_records_student_membership_id_attendance_date",
        # 학원 격리 복합 FK와 그 대상
        "uq_academy_memberships_academy_id_id",
        "uq_classes_academy_id_id",
        "fk_class_memberships_academy_id_classes",
        "fk_class_memberships_academy_id_academy_memberships",
        "fk_attendance_records_academy_id_academy_memberships",
        "fk_task_assignments_academy_id_tasks",
        "fk_schedule_exceptions_class_id_class_schedules",
        # 유니크·검증
        "uq_class_memberships_class_id_membership_id",
        "uq_task_assignments_task_id_student_membership_id",
        "uq_lesson_topics_class_id_lesson_date",
        "ck_class_schedules_time_order",
        "ck_class_schedules_weekday_range",
        "ck_schedule_exceptions_kind_fields",
    } <= constraints
    assert {
        "uq_schedule_exceptions_occurrence",
        "ix_attendance_records_academy_date",
        "ix_class_memberships_membership_status",
        "ix_task_assignments_student_completed",
        "ix_personal_todos_user_due_date",
    } <= indexes


_RANDOM_IDS = "gen_random_uuid(), gen_random_uuid(), gen_random_uuid()"


@pytest.mark.parametrize(
    "sql",
    [
        # 요일 범위
        "INSERT INTO class_schedules (id, academy_id, class_id, weekday, start_time, end_time, "
        f"effective_from) VALUES ({_RANDOM_IDS}, 7, '10:00', '11:00', '2026-01-01')",
        # 시간 순서
        "INSERT INTO class_schedules (id, academy_id, class_id, weekday, start_time, end_time, "
        f"effective_from) VALUES ({_RANDOM_IDS}, 1, '11:00', '10:00', '2026-01-01')",
        # 휴강인데 시간 지정
        "INSERT INTO schedule_exceptions (id, academy_id, class_id, schedule_id, kind, "
        f"original_date, session_date, start_time, end_time) VALUES ({_RANDOM_IDS}, "
        "gen_random_uuid(), 'CANCELLATION', '2026-01-01', '2026-01-02', '10:00', '11:00')",
        # 알 수 없는 출석 상태
        "INSERT INTO attendance_records (id, academy_id, student_membership_id, attendance_date, "
        f"status, source) VALUES ({_RANDOM_IDS}, '2026-01-01', 'SLEEPING', 'INSTRUCTOR')",
    ],
)
async def test_v03_database_rejects_invalid_values(migrated_database: str, sql: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(sql)
    finally:
        await conn.close()
