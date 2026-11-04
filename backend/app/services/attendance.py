"""학원 출석 (학생 체크인, 강사 기록·수정과 수정 이력).

- 출석 단위: 학원 소속(학생) × 학원 현지 날짜 1건. DB 유니크 제약으로 중복·동시 요청을 막는다.
- 학생 체크인: 학원 소속이 ACTIVE이고 학원이 ACTIVE일 때만. 상태는 PRESENT, 시각 자동 기록.
- 강사 기록·수정: 담당 학생만 (학원 관리자는 전체). 변경할 때마다 attendance_audit_logs에
  변경 전·후 스냅샷과 사유를 같은 트랜잭션으로 남긴다.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import ConflictError, ErrorCode, ForbiddenError, NotFoundError
from app.models.academy_class import AcademyClass
from app.models.attendance import AttendanceAuditLog, AttendanceRecord
from app.models.enums import (
    AcademyStatus,
    AttendanceAuditAction,
    AttendanceSource,
    AttendanceStatus,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.academies import AcademyRepository
from app.repositories.attendance import AttendanceRepository, snapshot
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate
from app.schemas.common import PaginationParams
from app.services.access import (
    AccessService,
    class_student_ids,
    managed_student_ids,
)
from app.services.schedules import validate_range

DEFAULT_HISTORY_DAYS = 30
MAX_HISTORY_DAYS = 366


def resolve_range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or clock.local_today()
    start = start or end - timedelta(days=DEFAULT_HISTORY_DAYS - 1)
    validate_range(start, end, MAX_HISTORY_DAYS)
    return start, end


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = AttendanceRepository(session)
        self.academies = AcademyRepository(session)
        self.access = AccessService(session)

    # ------------------------------------------------------------------ student

    async def check_in(self, student: AcademyMembership) -> AttendanceRecord:
        academy = await self.academies.get(student.academy_id)
        if academy is None or academy.status != AcademyStatus.ACTIVE:
            raise ConflictError(
                "Attendance is not available for this academy", code=ErrorCode.ACADEMY_NOT_ACTIVE
            )
        now = clock.utc_now()
        record_id = await self.records.insert_if_absent(
            academy_id=student.academy_id,
            student_membership_id=student.id,
            attendance_date=clock.to_local(now).date(),
            status=AttendanceStatus.PRESENT,
            source=AttendanceSource.SELF_CHECK_IN,
            checked_in_at=now,
        )
        if record_id is None:
            await self.session.rollback()
            raise ConflictError("Already checked in today", code=ErrorCode.ALREADY_CHECKED_IN)
        await self.session.commit()
        return await self.records.get(record_id)

    async def today(self, student: AcademyMembership) -> tuple[date, AttendanceRecord | None]:
        today = clock.local_today()
        return today, await self.records.get_for_day(student.id, today)

    async def my_records(
        self,
        student: AcademyMembership,
        params: PaginationParams,
        start: date | None,
        end: date | None,
    ) -> tuple[list[AttendanceRecord], int]:
        start, end = resolve_range(start, end)
        return await self.records.list_records(
            student.academy_id, params, start=start, end=end, student_membership_id=student.id
        )

    # ------------------------------------------------------------------ staff

    async def day_status(
        self,
        actor: AcademyMembership,
        day: date | None,
        params: PaginationParams,
        class_id: uuid.UUID | None,
    ) -> tuple[date, list[tuple[AcademyMembership, Profile, AttendanceRecord | None]], int]:
        """날짜별 출석 현황: 담당 학생 전원 + 그날 기록 (미출석이면 None)."""
        day = day or clock.local_today()
        if class_id is not None:
            await self.access.require_class_manager(actor, class_id)
            students = class_student_ids(select(AcademyClass.id).where(AcademyClass.id == class_id))
        else:
            students = managed_student_ids(actor)
        rows, total = await self.records.day_status(students, day, params)
        return day, rows, total

    async def list_records(
        self,
        actor: AcademyMembership,
        params: PaginationParams,
        *,
        start: date | None,
        end: date | None,
        student_membership_id: uuid.UUID | None,
    ) -> tuple[list[AttendanceRecord], int]:
        start, end = resolve_range(start, end)
        if student_membership_id is not None:
            await self.access.require_managed_student(actor, student_membership_id)
            return await self.records.list_records(
                actor.academy_id,
                params,
                start=start,
                end=end,
                student_membership_id=student_membership_id,
            )
        return await self.records.list_records(
            actor.academy_id, params, start=start, end=end, students=managed_student_ids(actor)
        )

    async def create_record(
        self, actor: AcademyMembership, data: AttendanceCreate
    ) -> AttendanceRecord:
        await self.access.require_managed_student(actor, data.student_membership_id)
        record_id = await self.records.insert_if_absent(
            academy_id=actor.academy_id,
            student_membership_id=data.student_membership_id,
            attendance_date=data.attendance_date,
            status=data.status,
            source=AttendanceSource.INSTRUCTOR,
            checked_in_at=None,
            note=data.note,
            updated_by=actor.id,
        )
        if record_id is None:
            await self.session.rollback()
            raise ConflictError(
                "Attendance for this date already exists; update it instead",
                code=ErrorCode.ATTENDANCE_ALREADY_RECORDED,
            )
        record = await self.records.get(record_id)
        self.records.add_audit(
            AttendanceAuditLog(
                id=uuid.uuid4(),
                academy_id=actor.academy_id,
                attendance_record_id=record_id,
                action=AttendanceAuditAction.CREATED,
                changed_by=actor.id,
                previous=None,
                current=snapshot(record),
                reason=data.reason,
                # now()는 트랜잭션 시작 시각이라 잠금 대기 순서와 다를 수 있다.
                # 행 잠금을 얻은 뒤의 시각을 기록해 이력 순서 = 실제 변경 순서가 되게 한다.
                created_at=clock.utc_now(),
            )
        )
        await self.session.commit()
        return await self.records.get(record_id)

    async def _managed_record(
        self, actor: AcademyMembership, record_id: uuid.UUID, *, for_update: bool = False
    ) -> AttendanceRecord:
        record = await self.records.get_in_academy(
            actor.academy_id, record_id, for_update=for_update
        )
        if record is None:
            raise NotFoundError("Attendance record not found")
        if not await self.access.is_managed_student(actor, record.student_membership_id):
            raise ForbiddenError("This student is not in your classes")
        return record

    async def update_record(
        self, actor: AcademyMembership, record_id: uuid.UUID, data: AttendanceUpdate
    ) -> AttendanceRecord:
        # 행 잠금: 동시에 수정해도 이력의 '변경 전' 값이 정확하게 남는다
        record = await self._managed_record(actor, record_id, for_update=True)
        before = snapshot(record)
        changes = {k: v for k, v in data.changes().items() if k in {"status", "note"}}
        for field, value in changes.items():
            setattr(record, field, value)
        after = snapshot(record)
        if after == before:
            await self.session.rollback()
            return await self.records.get(record_id)
        record.updated_by = actor.id
        self.records.add_audit(
            AttendanceAuditLog(
                id=uuid.uuid4(),
                academy_id=actor.academy_id,
                attendance_record_id=record.id,
                action=AttendanceAuditAction.UPDATED,
                changed_by=actor.id,
                previous=before,
                current=after,
                reason=data.reason,
                # now()는 트랜잭션 시작 시각이라 잠금 대기 순서와 다를 수 있다.
                # 행 잠금을 얻은 뒤의 시각을 기록해 이력 순서 = 실제 변경 순서가 되게 한다.
                created_at=clock.utc_now(),
            )
        )
        await self.session.commit()
        return await self.records.get(record_id)

    async def history(
        self, actor: AcademyMembership, record_id: uuid.UUID, params: PaginationParams
    ) -> tuple[list[tuple[AttendanceAuditLog, str | None]], int]:
        await self._managed_record(actor, record_id)
        return await self.records.list_audit(record_id, params)
