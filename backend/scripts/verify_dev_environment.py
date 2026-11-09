"""Supabase 개발 DB·Storage 적용 상태 점검 (읽기 전용).

프론트엔드 담당자가 개발 DB에 Alembic 0002~0004 와 storage-setup.sql 을 적용한 뒤,
백엔드 담당자가 결과를 **수정 없이** 확인하기 위한 스크립트다.

- 모든 쿼리는 `SET TRANSACTION READ ONLY` 트랜잭션 안에서 SELECT만 실행한다.
  (마이그레이션·버킷 생성·정책 적용을 하지 않는다 → 중복 실행·충돌 없음)
- 접속 URL, 호스트, 키 값은 출력하지 않는다. 키는 "설정됨/비어 있음"만 표시한다.
- 제외 기능(출석·오늘 할 일·질문 콜·시험 타이머) 테이블의 행 수를 보여 준다.
  물리 삭제 마이그레이션 설계 전 데이터 보존 여부 판단용.

실행 (backend/ 에서):
    uv run python -m scripts.verify_dev_environment            # backend/.env 의 DATABASE_URL
    uv run python -m scripts.verify_dev_environment --json     # 기계 판독용

종료 코드: 0 = 필수 항목 모두 통과, 1 = 실패 항목 있음, 2 = DB 미설정/접속 실패.
실제 사진·녹음 업로드, Signed URL, 학생·강사 권한 격리는 사용자 토큰이 필요하므로
docs/supabase-dev-verification.md 의 수동 절차로 확인한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db.session import build_engine

# 0001~0004 가 만든 앱 테이블 (RLS 활성화 대상)
REQUIRED_TABLES = (
    "profiles",
    "academies",
    "academy_memberships",
    "academy_join_requests",
    "classes",
    "class_memberships",
    "class_schedules",
    "schedule_exceptions",
    "lesson_topics",
    "tasks",
    "task_assignments",
    "artworks",
    "artwork_photos",
    "feedback_recordings",
    "recording_consents",
)
# v0.5.1에서 서비스에서 제외했지만 테이블은 보존 중인 것
EXCLUDED_FEATURE_TABLES = (
    "attendance_records",
    "attendance_audit_logs",
    "personal_todos",
    "exam_templates",
    "exam_stage_targets",
    "exam_sessions",
    "exam_session_stages",
    "exam_participants",
    "help_requests",
    "help_queue_events",
)
REQUIRED_FUNCTIONS = (
    "can_access_artwork_object",
    "manages_student",
    "can_access_recording_object",
)
REQUIRED_BUCKETS = ("artworks", "feedback-audio")
REQUIRED_POLICIES = tuple(
    f"artmate_{bucket}_{cmd}"
    for bucket in ("artworks", "audio")
    for cmd in ("select", "insert", "delete")
)
# 이 브랜치가 아는 최신 리비전. 0005(v0.5.1)는 승인 전까지 개발 DB에 적용하지 않는다.
FRONTEND_TARGET_REVISION = "0004"
LATEST_REVISION = "0006"
# 승인 후 적용될 리비전들 (0005 v0.5.1, 0006 v0.6)
KNOWN_REVISIONS = ("0004", "0005", "0006")
# 0006(v0.6 AI 첨삭)이 적용됐을 때만 필수
V06_TABLES = (
    "ai_processing_consents",
    "ai_processing_jobs",
    "feedback_transcripts",
    "feedback_summaries",
    "feedback_items",
    "feedback_categories",
    "feedback_review_history",
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    excluded_table_rows: dict[str, int | None] = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str = "", *, required: bool = True) -> None:
        self.checks.append(Check(name, ok, detail, required))

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks if c.required)


def check_settings(settings: Settings, report: Report) -> None:
    """키 값은 출력하지 않고 설정 여부만 기록한다."""
    report.add("env.DATABASE_URL", settings.database_url is not None, "설정됨/비어 있음만 확인")
    report.add("env.SUPABASE_URL", settings.supabase_url is not None)
    anon = settings.supabase_anon_key
    report.add(
        "env.SUPABASE_ANON_KEY",
        anon is not None and bool(anon.get_secret_value().strip()),
        "비어 있으면 사진·녹음 업로드/Signed URL API가 503 STORAGE_NOT_CONFIGURED",
    )


async def check_database(settings: Settings, report: Report) -> None:
    engine = build_engine(settings, use_null_pool=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("BEGIN READ ONLY"))

            async def scalar(sql: str, **params: Any) -> Any:
                return (await conn.execute(text(sql), params)).scalar()

            async def rows(sql: str, **params: Any) -> list[Any]:
                return list((await conn.execute(text(sql), params)).all())

            has_version_table = await scalar("SELECT to_regclass('public.alembic_version')")
            revision = (
                await scalar("SELECT version_num FROM alembic_version")
                if has_version_table
                else None
            )
            report.add(
                "alembic.current",
                revision in KNOWN_REVISIONS,
                f"현재 {revision or '없음'} (프론트 적용 목표 {FRONTEND_TARGET_REVISION},"
                f" 승인 후 최신 {LATEST_REVISION})",
            )

            present = {
                r[0]: r[1]
                for r in await rows(
                    "SELECT relname, relrowsecurity FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = 'public' AND c.relkind = 'r'"
                    " AND relname = ANY(:names)",
                    names=list(REQUIRED_TABLES + EXCLUDED_FEATURE_TABLES + V06_TABLES),
                )
            }
            required = REQUIRED_TABLES + (V06_TABLES if revision == "0006" else ())
            missing = [t for t in required if t not in present]
            report.add("tables.required", not missing, f"누락: {missing}" if missing else "")
            no_rls = [t for t in required if t in present and not present[t]]
            report.add("tables.rls_enabled", not no_rls, f"RLS 꺼짐: {no_rls}" if no_rls else "")

            functions = {
                r[0]: (r[1], r[2])
                for r in await rows(
                    "SELECT p.proname, p.prosecdef,"
                    " has_function_privilege('public', p.oid, 'EXECUTE')"
                    " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                    " WHERE n.nspname = 'artmate_private'"
                )
            }
            bad = [
                f
                for f in REQUIRED_FUNCTIONS
                if f not in functions or not functions[f][0] or functions[f][1]
            ]
            report.add(
                "functions.artmate_private",
                not bad,
                f"누락 또는 SECURITY DEFINER/PUBLIC 권한 이상: {bad}" if bad else "",
            )

            has_storage = await scalar("SELECT to_regclass('storage.buckets')")
            if not has_storage:
                report.add("storage.schema", False, "storage 스키마 없음 (Supabase DB가 아님)")
            else:
                buckets = {
                    r[0]: r[1]
                    for r in await rows(
                        "SELECT id, public FROM storage.buckets WHERE id = ANY(:ids)",
                        ids=list(REQUIRED_BUCKETS),
                    )
                }
                missing_buckets = [b for b in REQUIRED_BUCKETS if b not in buckets]
                public = [b for b, is_public in buckets.items() if is_public]
                report.add(
                    "storage.buckets",
                    not missing_buckets and not public,
                    f"누락 {missing_buckets}, 공개 버킷 {public}"
                    if missing_buckets or public
                    else "",
                )
                policies = {
                    r[0]
                    for r in await rows(
                        "SELECT policyname FROM pg_policies"
                        " WHERE schemaname = 'storage' AND tablename = 'objects'"
                        " AND policyname LIKE 'artmate_%'"
                    )
                }
                missing_policies = [p for p in REQUIRED_POLICIES if p not in policies]
                report.add(
                    "storage.policies",
                    not missing_policies,
                    f"누락: {missing_policies}" if missing_policies else "",
                )
                granted = await scalar(
                    "SELECT bool_and(has_function_privilege('authenticated', p.oid, 'EXECUTE'))"
                    " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                    " WHERE n.nspname = 'artmate_private' AND p.proname = ANY(:names)",
                    names=list(REQUIRED_FUNCTIONS),
                )
                report.add(
                    "storage.authenticated_execute",
                    bool(granted),
                    "authenticated 역할에 권한 함수 EXECUTE 부여 여부",
                )

            for table in EXCLUDED_FEATURE_TABLES:
                report.excluded_table_rows[table] = (
                    await scalar(f'SELECT count(*) FROM public."{table}"')
                    if table in present
                    else None
                )
            await conn.execute(text("ROLLBACK"))
    finally:
        await engine.dispose()


def print_report(report: Report) -> None:
    for c in report.checks:
        mark = "PASS" if c.ok else ("FAIL" if c.required else "WARN")
        print(f"[{mark}] {c.name}" + (f" — {c.detail}" if c.detail else ""))
    if report.excluded_table_rows:
        print("\n제외 기능 테이블 행 수 (물리 삭제 전 데이터 보존 판단용):")
        for table, count in report.excluded_table_rows.items():
            print(f"  {table}: {'테이블 없음' if count is None else count}")
    print("\n결과:", "통과" if report.passed else "실패 항목 있음")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = parser.parse_args()

    settings = get_settings()
    report = Report()
    check_settings(settings, report)
    if settings.database_url is None:
        print("DATABASE_URL이 비어 있어 DB 점검을 건너뜁니다.", file=sys.stderr)
        print_report(report)
        return 2
    try:
        await check_database(settings, report)
    except Exception as exc:
        print(f"DB 접속 또는 조회 실패: {type(exc).__name__}", file=sys.stderr)
        print_report(report)
        return 2
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
