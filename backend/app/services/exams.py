"""시험 템플릿·세션·참가자 (F-10).

권한
- 템플릿: 조회·생성 = 강사 이상, 수정·보관 = 학원 관리자 또는 만든 사람
- 세션 생성·시작·종료·취소·현황: 그 반의 담당 강사 또는 학원 관리자
- 세션 목록: 담당 반 (학원 관리자는 전체)
- 학생: 참가한 시험의 타이머·본인 단계 조회, 본인 단계 변경 (진행 중일 때만)

동시성
- 시작: 세션 행 잠금 + 부분 유니크(반당 RUNNING 1개) → 동시 시작 요청도 1개만 성공
- 단계 변경: 참가자 행 잠금
"""

import uuid
from collections import Counter
from datetime import timedelta
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from app.models.academy_class import AcademyClass
from app.models.enums import (
    ARTWORK_STAGE_ORDER,
    EXAM_WORK_STAGE_ORDER,
    ArtworkStage,
    ExamEndReason,
    ExamSessionStatus,
    ExamWorkStage,
)
from app.models.exam import (
    ExamParticipant,
    ExamSession,
    ExamSessionStage,
    ExamStageTarget,
    ExamTemplate,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.classes import ClassRepository
from app.repositories.pagination import fetch_page
from app.schemas.attendance import StudentRef
from app.schemas.common import PaginationParams
from app.schemas.exams import (
    ExamSessionCreate,
    ExamSessionDetail,
    ExamSessionSummary,
    ExamTemplateCreate,
    ExamTemplateRead,
    ExamTemplateUpdate,
    MyExam,
    MyParticipation,
    ParticipantRead,
    StageCount,
    StageTargetInput,
    StageTargetRead,
)
from app.services.access import AccessService, is_admin, scoped_class_ids
from app.services.classes import ensure_class_active
from app.services.exam_timer import build_timer, effective_state, is_behind

_STAGE_COLUMNS = {
    ExamWorkStage.SKETCH: "sketch_at",
    ExamWorkStage.PROGRESS: "progress_at",
    ExamWorkStage.FINAL: "final_at",
    ExamWorkStage.DONE: "done_at",
}


def validate_targets(
    total_minutes: int, targets: list[StageTargetInput]
) -> dict[ArtworkStage, int]:
    """SKETCH < PROGRESS < FINAL ≤ total_minutes, 각 단계 정확히 1개."""
    by_stage = {t.stage: t.offset_minutes for t in targets}
    if len(by_stage) != len(targets) or set(by_stage) != set(ARTWORK_STAGE_ORDER):
        raise UnprocessableError(
            "stage_targets must contain SKETCH, PROGRESS and FINAL exactly once",
            code=ErrorCode.INVALID_STAGE_TARGETS,
        )
    offsets = [by_stage[stage] for stage in ARTWORK_STAGE_ORDER]
    if any(a >= b for a, b in pairwise(offsets)):
        raise UnprocessableError(
            "Stage targets must increase: SKETCH < PROGRESS < FINAL",
            code=ErrorCode.INVALID_STAGE_TARGETS,
        )
    if offsets[-1] > total_minutes:
        raise UnprocessableError(
            "FINAL target must be within total_minutes", code=ErrorCode.INVALID_STAGE_TARGETS
        )
    return by_stage


def student_ref(membership: AcademyMembership, profile: Profile) -> StudentRef:
    return StudentRef(
        membership_id=membership.id,
        user_id=profile.id,
        display_name=profile.display_name,
        avatar_path=profile.avatar_path,
    )


class ExamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.access = AccessService(session)
        self.classes = ClassRepository(session)

    # ------------------------------------------------------------------ templates

    async def _targets(
        self, template_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[ExamStageTarget]]:
        result: dict[uuid.UUID, list[ExamStageTarget]] = {t: [] for t in template_ids}
        if template_ids:
            stmt = select(ExamStageTarget).where(ExamStageTarget.template_id.in_(template_ids))
            for target in (await self.session.execute(stmt)).scalars():
                result[target.template_id].append(target)
        return result

    @staticmethod
    def _template_read(template: ExamTemplate, targets: list[ExamStageTarget]) -> ExamTemplateRead:
        ordered = sorted(targets, key=lambda t: ARTWORK_STAGE_ORDER.index(t.stage))
        return ExamTemplateRead(
            id=template.id,
            academy_id=template.academy_id,
            name=template.name,
            exam_type=template.exam_type,
            description=template.description,
            total_minutes=template.total_minutes,
            stage_targets=[
                StageTargetRead(stage=t.stage, offset_minutes=t.offset_minutes) for t in ordered
            ],
            is_archived=template.is_archived,
            created_by=template.created_by,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )

    async def _template(
        self, actor: AcademyMembership, template_id: uuid.UUID, *, for_update: bool = False
    ) -> ExamTemplate:
        stmt = select(ExamTemplate).where(
            ExamTemplate.academy_id == actor.academy_id, ExamTemplate.id == template_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        template = (await self.session.execute(stmt)).scalar_one_or_none()
        if template is None:
            raise NotFoundError("Exam template not found")
        return template

    async def _replace_targets(
        self, template: ExamTemplate, by_stage: dict[ArtworkStage, int]
    ) -> None:
        for target in (await self._targets([template.id]))[template.id]:
            await self.session.delete(target)
        await self.session.flush()
        for stage, offset in by_stage.items():
            self.session.add(
                ExamStageTarget(
                    id=uuid.uuid4(),
                    academy_id=template.academy_id,
                    template_id=template.id,
                    stage=stage,
                    offset_minutes=offset,
                )
            )

    async def create_template(
        self, actor: AcademyMembership, data: ExamTemplateCreate
    ) -> ExamTemplateRead:
        by_stage = validate_targets(data.total_minutes, data.stage_targets)
        template = ExamTemplate(
            id=uuid.uuid4(),
            academy_id=actor.academy_id,
            name=data.name,
            exam_type=data.exam_type,
            description=data.description,
            total_minutes=data.total_minutes,
            is_archived=False,
            created_by=actor.id,
        )
        self.session.add(template)
        await self.session.flush()
        await self._replace_targets(template, by_stage)
        await self.session.commit()
        return await self.get_template(actor, template.id)

    async def list_templates(
        self, actor: AcademyMembership, params: PaginationParams, *, include_archived: bool
    ) -> tuple[list[ExamTemplateRead], int]:
        stmt = select(ExamTemplate).where(ExamTemplate.academy_id == actor.academy_id)
        if not include_archived:
            stmt = stmt.where(ExamTemplate.is_archived.is_(False))
        stmt = stmt.order_by(ExamTemplate.name, ExamTemplate.id)
        rows, total = await fetch_page(self.session, stmt, params)
        templates = [row[0] for row in rows]
        targets = await self._targets([t.id for t in templates])
        return [self._template_read(t, targets[t.id]) for t in templates], total

    async def get_template(
        self, actor: AcademyMembership, template_id: uuid.UUID
    ) -> ExamTemplateRead:
        template = await self._template(actor, template_id)
        await self.session.refresh(template)
        return self._template_read(template, (await self._targets([template.id]))[template.id])

    async def _editable_template(
        self, actor: AcademyMembership, template_id: uuid.UUID
    ) -> ExamTemplate:
        template = await self._template(actor, template_id, for_update=True)
        if not is_admin(actor) and template.created_by != actor.id:
            raise ForbiddenError("Only the creator or academy managers can edit this template")
        return template

    async def update_template(
        self, actor: AcademyMembership, template_id: uuid.UUID, data: ExamTemplateUpdate
    ) -> ExamTemplateRead:
        template = await self._editable_template(actor, template_id)
        if template.is_archived:
            raise ConflictError("This template is archived", code=ErrorCode.TEMPLATE_ARCHIVED)
        changes = data.changes()
        new_targets = changes.pop("stage_targets", None)
        for field, value in changes.items():
            setattr(template, field, value)
        if new_targets is not None:
            targets = data.stage_targets or []
        else:
            targets = [
                StageTargetInput(stage=t.stage, offset_minutes=t.offset_minutes)
                for t in (await self._targets([template.id]))[template.id]
            ]
        by_stage = validate_targets(template.total_minutes, targets)
        if new_targets is not None:
            await self._replace_targets(template, by_stage)
        await self.session.commit()
        return await self.get_template(actor, template.id)

    async def archive_template(self, actor: AcademyMembership, template_id: uuid.UUID) -> None:
        template = await self._editable_template(actor, template_id)
        template.is_archived = True
        await self.session.commit()

    # ------------------------------------------------------------------ sessions

    async def _session(
        self, actor: AcademyMembership, session_id: uuid.UUID, *, for_update: bool = False
    ) -> ExamSession:
        stmt = select(ExamSession).where(
            ExamSession.academy_id == actor.academy_id, ExamSession.id == session_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        exam = (await self.session.execute(stmt)).scalar_one_or_none()
        if exam is None:
            raise NotFoundError("Exam session not found")
        return exam

    async def _managed_session(
        self, actor: AcademyMembership, session_id: uuid.UUID, *, for_update: bool = False
    ) -> ExamSession:
        exam = await self._session(actor, session_id, for_update=for_update)
        await self.access.require_class_manager(actor, exam.class_id)
        return exam

    async def _stages(
        self, session_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[ExamSessionStage]]:
        result: dict[uuid.UUID, list[ExamSessionStage]] = {s: [] for s in session_ids}
        if session_ids:
            stmt = select(ExamSessionStage).where(ExamSessionStage.session_id.in_(session_ids))
            for stage in (await self.session.execute(stmt)).scalars():
                result[stage.session_id].append(stage)
        return result

    async def _summaries(self, sessions: list[ExamSession]) -> list[ExamSessionSummary]:
        now = clock.utc_now()
        stages = await self._stages([s.id for s in sessions])
        names = {
            c.id: c.name
            for c in await self.classes.classes_by_ids(
                select(AcademyClass.id).where(AcademyClass.id.in_([s.class_id for s in sessions]))
            )
        }
        return [
            ExamSessionSummary(
                id=s.id,
                academy_id=s.academy_id,
                class_id=s.class_id,
                class_name=names.get(s.class_id, ""),
                template_id=s.template_id,
                title=s.title,
                exam_type=s.exam_type,
                total_minutes=s.total_minutes,
                created_at=s.created_at,
                timer=build_timer(s, stages[s.id], now),
            )
            for s in sessions
        ]

    def _finalize_if_time_up(self, exam: ExamSession) -> bool:
        """진행 중인데 시간이 다 됐으면 DB에도 ENDED(TIME_UP)로 반영한다."""
        state = effective_state(exam, clock.utc_now())
        if exam.status == ExamSessionStatus.RUNNING and state.status == ExamSessionStatus.ENDED:
            exam.status = ExamSessionStatus.ENDED
            exam.ended_at = state.ended_at
            exam.end_reason = ExamEndReason.TIME_UP
            return True
        return False

    async def create_session(
        self, actor: AcademyMembership, data: ExamSessionCreate
    ) -> ExamSessionDetail:
        ensure_class_active(await self.access.require_class_manager(actor, data.class_id))
        template = await self._template(actor, data.template_id)
        if template.is_archived:
            raise ConflictError("This template is archived", code=ErrorCode.TEMPLATE_ARCHIVED)
        targets = (await self._targets([template.id]))[template.id]
        exam = ExamSession(
            id=uuid.uuid4(),
            academy_id=actor.academy_id,
            class_id=data.class_id,
            template_id=template.id,
            title=data.title or template.name,
            exam_type=template.exam_type,
            total_minutes=template.total_minutes,
            status=ExamSessionStatus.SCHEDULED,
            created_by=actor.id,
        )
        self.session.add(exam)
        await self.session.flush()
        for target in targets:
            self.session.add(
                ExamSessionStage(
                    id=uuid.uuid4(),
                    academy_id=actor.academy_id,
                    session_id=exam.id,
                    stage=target.stage,
                    offset_minutes=target.offset_minutes,
                )
            )
        await self.session.commit()
        if data.start_now:
            return await self.start(actor, exam.id)
        return await self.detail(actor, exam.id)

    async def start(self, actor: AcademyMembership, session_id: uuid.UUID) -> ExamSessionDetail:
        exam = await self._managed_session(actor, session_id, for_update=True)
        if exam.status != ExamSessionStatus.SCHEDULED:
            raise ConflictError(
                f"Only a scheduled exam can be started (now {exam.status})",
                code=ErrorCode.EXAM_INVALID_STATE,
            )
        academy_class = await self.access.get_class(actor.academy_id, exam.class_id)
        ensure_class_active(academy_class)

        # 같은 반에서 시간이 다 된 RUNNING 시험은 먼저 종료 처리
        running = (
            (
                await self.session.execute(
                    select(ExamSession)
                    .where(
                        ExamSession.class_id == exam.class_id,
                        ExamSession.status == ExamSessionStatus.RUNNING,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for other in running:
            if not self._finalize_if_time_up(other):
                raise ConflictError(
                    "Another exam is already running in this class",
                    code=ErrorCode.EXAM_ALREADY_RUNNING,
                    details={"session_id": str(other.id)},
                )
        await self.session.flush()

        now = clock.utc_now()
        exam.status = ExamSessionStatus.RUNNING
        exam.started_at = now
        exam.ends_at = now + timedelta(minutes=exam.total_minutes)
        exam.started_by = actor.id
        for stage in (await self._stages([exam.id]))[exam.id]:
            stage.target_at = now + timedelta(minutes=stage.offset_minutes)

        students = await self.classes.active_student_ids(exam.class_id)
        if students:
            # 시작 = 스케치 시작
            await self.session.execute(
                insert(ExamParticipant)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "academy_id": actor.academy_id,
                            "session_id": exam.id,
                            "student_membership_id": sid,
                            "current_stage": ExamWorkStage.SKETCH,
                            "stage_updated_at": now,
                            "sketch_at": now,
                        }
                        for sid in sorted(students)
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ExamParticipant.session_id,
                        ExamParticipant.student_membership_id,
                    ]
                )
            )
        try:
            await self.session.commit()
        except IntegrityError:
            # 동시에 다른 시험이 시작됨: 부분 유니크 uq_exam_sessions_running_class
            await self.session.rollback()
            raise ConflictError(
                "Another exam is already running in this class",
                code=ErrorCode.EXAM_ALREADY_RUNNING,
            ) from None
        return await self.detail(actor, exam.id)

    async def end(self, actor: AcademyMembership, session_id: uuid.UUID) -> ExamSessionDetail:
        exam = await self._managed_session(actor, session_id, for_update=True)
        if exam.status in (ExamSessionStatus.SCHEDULED, ExamSessionStatus.CANCELLED):
            raise ConflictError(
                f"This exam is not running (now {exam.status})", code=ErrorCode.EXAM_INVALID_STATE
            )
        if exam.status == ExamSessionStatus.RUNNING and not self._finalize_if_time_up(exam):
            exam.status = ExamSessionStatus.ENDED
            exam.ended_at = clock.utc_now()
            exam.end_reason = ExamEndReason.MANUAL
            exam.ended_by = actor.id
        await self.session.commit()
        return await self.detail(actor, exam.id)

    async def cancel(self, actor: AcademyMembership, session_id: uuid.UUID) -> None:
        exam = await self._managed_session(actor, session_id, for_update=True)
        if exam.status != ExamSessionStatus.SCHEDULED:
            raise ConflictError(
                "Only a scheduled exam can be cancelled; end it instead",
                code=ErrorCode.EXAM_INVALID_STATE,
            )
        exam.status = ExamSessionStatus.CANCELLED
        await self.session.commit()

    async def list_sessions(
        self,
        actor: AcademyMembership,
        params: PaginationParams,
        *,
        class_id: uuid.UUID | None,
        status: ExamSessionStatus | None,
    ) -> tuple[list[ExamSessionSummary], int]:
        if class_id is not None:
            await self.access.require_class_manager(actor, class_id)
            scope = select(AcademyClass.id).where(AcademyClass.id == class_id)
        else:
            scope = scoped_class_ids(actor, mine=False)
        stmt = select(ExamSession).where(
            ExamSession.academy_id == actor.academy_id, ExamSession.class_id.in_(scope)
        )
        if status is not None:
            stmt = stmt.where(ExamSession.status == status)
        stmt = stmt.order_by(ExamSession.created_at.desc(), ExamSession.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return await self._summaries([row[0] for row in rows]), total

    async def detail(self, actor: AcademyMembership, session_id: uuid.UUID) -> ExamSessionDetail:
        """반 전체 진행 현황 (학생별 현재 단계, 단계별 인원, 뒤처진 학생 수)."""
        exam = await self._managed_session(actor, session_id)
        await self.session.refresh(exam)
        summary = (await self._summaries([exam]))[0]
        rows = (
            await self.session.execute(
                select(ExamParticipant, AcademyMembership, Profile)
                .join(
                    AcademyMembership, AcademyMembership.id == ExamParticipant.student_membership_id
                )
                .join(Profile, Profile.id == AcademyMembership.user_id)
                .where(ExamParticipant.session_id == exam.id)
                .order_by(Profile.display_name, ExamParticipant.id)
            )
        ).all()
        participants = [
            ParticipantRead(
                id=p.id,
                student=student_ref(m, profile),
                current_stage=p.current_stage,
                stage_updated_at=p.stage_updated_at,
                sketch_at=p.sketch_at,
                progress_at=p.progress_at,
                final_at=p.final_at,
                done_at=p.done_at,
                behind_schedule=is_behind(p.current_stage, summary.timer),
            )
            for p, m, profile in rows
        ]
        counts = Counter(p.current_stage for p in participants)
        return ExamSessionDetail(
            **summary.model_dump(),
            participant_count=len(participants),
            stage_counts=[
                StageCount(stage=stage, count=counts.get(stage, 0))
                for stage in EXAM_WORK_STAGE_ORDER
            ],
            behind_count=sum(p.behind_schedule for p in participants),
            participants=participants,
        )

    # ------------------------------------------------------------------ student

    @staticmethod
    def _me(participant: ExamParticipant, summary: ExamSessionSummary) -> MyParticipation:
        return MyParticipation(
            current_stage=participant.current_stage,
            stage_updated_at=participant.stage_updated_at,
            sketch_at=participant.sketch_at,
            progress_at=participant.progress_at,
            final_at=participant.final_at,
            done_at=participant.done_at,
            behind_schedule=is_behind(participant.current_stage, summary.timer),
        )

    async def my_exams(
        self, student: AcademyMembership, params: PaginationParams, *, active_only: bool
    ) -> tuple[list[MyExam], int]:
        stmt = (
            select(ExamSession, ExamParticipant)
            .join(ExamParticipant, ExamParticipant.session_id == ExamSession.id)
            .where(
                ExamSession.academy_id == student.academy_id,
                ExamParticipant.student_membership_id == student.id,
            )
        )
        if active_only:
            stmt = stmt.where(
                ExamSession.status == ExamSessionStatus.RUNNING,
                ExamSession.ends_at > clock.utc_now(),
            )
        stmt = stmt.order_by(ExamSession.started_at.desc(), ExamSession.id)
        rows, total = await fetch_page(self.session, stmt, params)
        summaries = await self._summaries([row[0] for row in rows])
        return [
            MyExam(**summary.model_dump(), me=self._me(row[1], summary))
            for summary, row in zip(summaries, rows, strict=True)
        ], total

    async def _participation(
        self, student: AcademyMembership, session_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[ExamSession, ExamParticipant]:
        exam = await self._session(student, session_id, for_update=for_update)
        stmt = select(ExamParticipant).where(
            ExamParticipant.session_id == exam.id,
            ExamParticipant.student_membership_id == student.id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        participant = (await self.session.execute(stmt)).scalar_one_or_none()
        if participant is None:
            # 참가하지 않은 시험은 존재를 노출하지 않는다
            raise NotFoundError("Exam session not found")
        return exam, participant

    async def my_exam(self, student: AcademyMembership, session_id: uuid.UUID) -> MyExam:
        exam, participant = await self._participation(student, session_id)
        summary = (await self._summaries([exam]))[0]
        return MyExam(**summary.model_dump(), me=self._me(participant, summary))

    async def change_stage(
        self, student: AcademyMembership, session_id: uuid.UUID, stage: ExamWorkStage
    ) -> MyExam:
        exam, participant = await self._participation(student, session_id, for_update=True)
        if self._finalize_if_time_up(exam):
            await self.session.commit()
            raise ConflictError("The exam has ended", code=ErrorCode.EXAM_NOT_RUNNING)
        if exam.status != ExamSessionStatus.RUNNING:
            raise ConflictError(
                f"The exam is not running (now {exam.status})", code=ErrorCode.EXAM_NOT_RUNNING
            )
        now = clock.utc_now()
        if participant.current_stage != stage:
            participant.current_stage = stage
            participant.stage_updated_at = now
            column = _STAGE_COLUMNS[stage]
            if getattr(participant, column) is None:
                setattr(participant, column, now)
        await self.session.commit()
        return await self.my_exam(student, session_id)
