import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceAuditLog, AttendanceRecord
from app.models.enums import AttendanceSource, AttendanceStatus
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.common import PaginationParams


class AttendanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_if_absent(
        self,
        *,
        academy_id: uuid.UUID,
        student_membership_id: uuid.UUID,
        attendance_date: date,
        status: AttendanceStatus,
        source: AttendanceSource,
        checked_in_at: datetime | None,
        note: str | None = None,
        updated_by: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """같은 날 기록이 없을 때만 생성 (uq(student_membership_id, attendance_date)).

        이미 있거나 동시에 다른 요청이 먼저 생성했으면 None → 중복 출석 방지.
        """
        stmt = (
            insert(AttendanceRecord)
            .values(
                id=uuid.uuid4(),
                academy_id=academy_id,
                student_membership_id=student_membership_id,
                attendance_date=attendance_date,
                status=status,
                source=source,
                checked_in_at=checked_in_at,
                note=note,
                updated_by=updated_by,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AttendanceRecord.student_membership_id,
                    AttendanceRecord.attendance_date,
                ]
            )
            .returning(AttendanceRecord.id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, record_id: uuid.UUID) -> AttendanceRecord:
        record = await self.session.get(AttendanceRecord, record_id, populate_existing=True)
        assert record is not None
        return record

    async def get_in_academy(
        self, academy_id: uuid.UUID, record_id: uuid.UUID, *, for_update: bool = False
    ) -> AttendanceRecord | None:
        stmt = select(AttendanceRecord).where(
            AttendanceRecord.academy_id == academy_id, AttendanceRecord.id == record_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_day(
        self, student_membership_id: uuid.UUID, day: date
    ) -> AttendanceRecord | None:
        stmt = select(AttendanceRecord).where(
            AttendanceRecord.student_membership_id == student_membership_id,
            AttendanceRecord.attendance_date == day,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_records(
        self,
        academy_id: uuid.UUID,
        params: PaginationParams,
        *,
        start: date,
        end: date,
        students: Select[tuple[uuid.UUID]] | None = None,
        student_membership_id: uuid.UUID | None = None,
    ) -> tuple[list[AttendanceRecord], int]:
        stmt = select(AttendanceRecord).where(
            AttendanceRecord.academy_id == academy_id,
            AttendanceRecord.attendance_date >= start,
            AttendanceRecord.attendance_date <= end,
        )
        if students is not None:
            stmt = stmt.where(AttendanceRecord.student_membership_id.in_(students))
        if student_membership_id is not None:
            stmt = stmt.where(AttendanceRecord.student_membership_id == student_membership_id)
        stmt = stmt.order_by(
            AttendanceRecord.attendance_date.desc(),
            AttendanceRecord.student_membership_id,
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def day_status(
        self, students: Select[tuple[uuid.UUID]], day: date, params: PaginationParams
    ) -> tuple[list[tuple[AcademyMembership, Profile, AttendanceRecord | None]], int]:
        """학생 목록(이름순) + 그날 출석 기록 (없으면 None)."""
        stmt = (
            select(AcademyMembership, Profile, AttendanceRecord)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .outerjoin(
                AttendanceRecord,
                (AttendanceRecord.student_membership_id == AcademyMembership.id)
                & (AttendanceRecord.attendance_date == day),
            )
            .where(AcademyMembership.id.in_(students))
            .order_by(Profile.display_name, AcademyMembership.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1], row[2]) for row in rows], total

    async def records_for_day(
        self, students: Select[tuple[uuid.UUID]], day: date
    ) -> dict[uuid.UUID, AttendanceRecord]:
        stmt = select(AttendanceRecord).where(
            AttendanceRecord.student_membership_id.in_(students),
            AttendanceRecord.attendance_date == day,
        )
        return {r.student_membership_id: r for r in (await self.session.execute(stmt)).scalars()}

    # ------------------------------------------------------------------ audit

    def add_audit(self, log: AttendanceAuditLog) -> None:
        self.session.add(log)

    async def list_audit(
        self, record_id: uuid.UUID, params: PaginationParams
    ) -> tuple[list[tuple[AttendanceAuditLog, str | None]], int]:
        stmt = (
            select(AttendanceAuditLog, Profile.display_name)
            .outerjoin(AcademyMembership, AcademyMembership.id == AttendanceAuditLog.changed_by)
            .outerjoin(Profile, Profile.id == AcademyMembership.user_id)
            .where(AttendanceAuditLog.attendance_record_id == record_id)
            .order_by(AttendanceAuditLog.created_at, AttendanceAuditLog.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1]) for row in rows], total


def snapshot(record: AttendanceRecord) -> dict[str, Any]:
    return {"status": str(record.status), "note": record.note}
