"""AI 첨삭 학습 데이터셋 (v0.9.8): 학습 활용 동의와 학습 샘플 선별.

지금은 모델을 학습하거나 외부 API를 부르지 않는다. 데이터가 정확하게 쌓이도록
"어떤 피드백이 학습 샘플이 될 수 있는가"를 한 곳(eligibility)에서 판단한다.

학습 샘플 조건 (모두 만족):
1. 학생의 유효한 학습 활용 동의 (현재 버전, 철회 안 함). 만 14세 미만은 동의 자체를 받지 않는다.
2. 기준 이미지가 확인됨(CONFIRMED)이고, 참조한 사진 중 삭제되지 않은 사진이 1장 이상
   (제안 SUGGESTED·미지정 NONE은 자동 등록하지 않는다)
3. 강사 피드백: 글 첨삭은 출처 INSTRUCTOR, 녹음은 강사 동의를 학생이 기록(CONSENT_REPORTED)
4. 녹음은 STT 전사가 있어야 한다 (원문 근거)

원문(글 첨삭·전사)과 레이블(AI 요약 항목, 전문가 레이블)은 분리해서 담고, AI 추정과 전문가 확인을
origin·verification으로 구분한다. 학생 식별자는 HMAC 가명으로만 내보낸다.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    DatasetExportDisabledError,
    ErrorCode,
    UnprocessableError,
)
from app.models.ai_feedback import (
    FeedbackItem,
    FeedbackNote,
    FeedbackSummary,
    FeedbackTranscript,
)
from app.models.artwork import Artwork, ArtworkPhoto, ArtworkStageDef
from app.models.dataset import DatasetConsent, FeedbackImageRef, FeedbackLabel
from app.models.enums import (
    CURRENT_FEEDBACK_STATUSES,
    AiAgeBand,
    FeedbackSource,
    FeedbackStatus,
    ImageRefStatus,
    LabelOrigin,
    LabelVerification,
    PhotoStatus,
    RecordingStatus,
    ReviewMode,
    SpeakerConsentStatus,
)
from app.models.profile import Profile, TargetUniversity
from app.models.recording import FeedbackRecording
from app.schemas.dataset import (
    DatasetConsentCreate,
    DatasetConsentStatus,
    DatasetStats,
    SampleImage,
    SampleLabel,
    SampleTarget,
    TrainingSample,
)
from app.services.ai_consent_policy import age_band

# 제외 사유 (통계 키)
NO_CONSENT = "NO_DATASET_CONSENT"
REF_NOT_CONFIRMED = "IMAGE_REF_NOT_CONFIRMED"
NO_ACTIVE_PHOTO = "NO_ACTIVE_REFERENCE_PHOTO"
NOT_INSTRUCTOR = "NOT_INSTRUCTOR_FEEDBACK"
SPEAKER_NOT_REPORTED = "INSTRUCTOR_CONSENT_NOT_REPORTED"
NO_TRANSCRIPT = "NO_TRANSCRIPT"


# ------------------------------------------------------------------ 동의


class DatasetConsentService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _active(self, user_id: uuid.UUID) -> DatasetConsent | None:
        return (
            await self.session.execute(
                select(DatasetConsent).where(
                    DatasetConsent.user_id == user_id, DatasetConsent.revoked_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    def _status(self, consent: DatasetConsent | None) -> DatasetConsentStatus:
        required = self.settings.dataset_consent_version
        return DatasetConsentStatus(
            is_valid=consent is not None and consent.policy_version == required,
            required_version=required,
            policy_version=consent.policy_version if consent else None,
            age_band=consent.age_band if consent else None,
            granted_at=consent.granted_at if consent else None,
        )

    async def status(self, user: Profile) -> DatasetConsentStatus:
        return self._status(await self._active(user.id))

    async def grant(self, user: Profile, data: DatasetConsentCreate) -> DatasetConsentStatus:
        required = self.settings.dataset_consent_version
        if data.policy_version != required:
            raise ConflictError(
                "Please agree to the current policy version",
                code=ErrorCode.CONFLICT,
                details={"required_version": required},
            )
        try:
            band = age_band(data.birth_year_month, clock.local_today())
        except ValueError:
            raise UnprocessableError("birth_year_month is invalid") from None
        if band == AiAgeBand.UNDER_14:
            # 법정대리인 동의 절차가 준비되기 전까지 만 14세 미만은 학습 활용 동의를 받지 않는다
            raise ConflictError(
                "Training-use consent is not available under 14 yet",
                code=ErrorCode.DATASET_CONSENT_UNAVAILABLE,
            )
        current = await self._active(user.id)
        now = clock.utc_now()
        if current is not None:
            current.revoked_at = now
            await self.session.flush()
        consent = DatasetConsent(
            id=uuid.uuid4(),
            user_id=user.id,
            policy_version=required,
            age_band=band,
            granted_at=now,
        )
        self.session.add(consent)
        await self.session.commit()
        return self._status(consent)

    async def revoke(self, user: Profile) -> None:
        """철회하면 이후 내보내기에서 즉시 빠진다 (이미 내보낸 사본은 운영 절차로 삭제)."""
        current = await self._active(user.id)
        if current is not None:
            current.revoked_at = clock.utc_now()
            await self.session.commit()


# ------------------------------------------------------------------ 샘플 선별


@dataclass
class _Candidate:
    feedback: FeedbackRecording | FeedbackNote
    artwork: Artwork
    reasons: list[str] = field(default_factory=list)


def pseudonym(key: str, user_id: uuid.UUID) -> str:
    return hmac.new(key.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()[:24]


class DatasetService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _candidates(self) -> list[_Candidate]:
        out: list[_Candidate] = []
        live = Artwork.deleted_at.is_(None)
        for row in await self.session.execute(
            select(FeedbackRecording, Artwork)
            .join(Artwork, Artwork.id == FeedbackRecording.artwork_id)
            .where(FeedbackRecording.status == RecordingStatus.ACTIVE, live)
        ):
            out.append(_Candidate(row[0], row[1]))
        for row in await self.session.execute(
            select(FeedbackNote, Artwork)
            .join(Artwork, Artwork.id == FeedbackNote.artwork_id)
            .where(live)
        ):
            out.append(_Candidate(row[0], row[1]))
        return out

    async def _judge(
        self, candidates: list[_Candidate]
    ) -> tuple[dict[uuid.UUID, DatasetConsent], dict[uuid.UUID, list[uuid.UUID]]]:
        """제외 사유를 채운다. (유효 동의, 피드백별 살아 있는 기준 사진)을 함께 돌려준다."""
        owners = {c.artwork.owner_id for c in candidates}
        required = self.settings.dataset_consent_version
        consents = {
            c.user_id: c
            for c in (
                await self.session.execute(
                    select(DatasetConsent).where(
                        DatasetConsent.user_id.in_(owners) if owners else false(),
                        DatasetConsent.revoked_at.is_(None),
                        DatasetConsent.policy_version == required,
                    )
                )
            ).scalars()
        }
        live_refs: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for ref, status in await self.session.execute(
            select(FeedbackImageRef, ArtworkPhoto.status)
            .join(ArtworkPhoto, ArtworkPhoto.id == FeedbackImageRef.photo_id)
            .order_by(FeedbackImageRef.position)
        ):
            if status == PhotoStatus.ACTIVE:
                live_refs[ref.feedback_recording_id or ref.feedback_note_id].append(ref.photo_id)  # type: ignore[index]
        with_transcript = set(
            (await self.session.execute(select(FeedbackTranscript.recording_id))).scalars()
        )
        for c in candidates:
            f = c.feedback
            consent = consents.get(c.artwork.owner_id)
            if consent is None or consent.age_band == AiAgeBand.UNDER_14:
                c.reasons.append(NO_CONSENT)
            if f.image_ref_status != ImageRefStatus.CONFIRMED:
                c.reasons.append(REF_NOT_CONFIRMED)
            elif not live_refs.get(f.id):
                c.reasons.append(NO_ACTIVE_PHOTO)
            if isinstance(f, FeedbackNote):
                if f.source != FeedbackSource.INSTRUCTOR:
                    c.reasons.append(NOT_INSTRUCTOR)
            else:
                if f.speaker_consent_status != SpeakerConsentStatus.CONSENT_REPORTED:
                    c.reasons.append(SPEAKER_NOT_REPORTED)
                if f.id not in with_transcript:
                    c.reasons.append(NO_TRANSCRIPT)
        return consents, live_refs

    async def stats(self) -> DatasetStats:
        candidates = await self._candidates()
        await self._judge(candidates)
        excluded: Counter[str] = Counter(r for c in candidates for r in c.reasons)
        return DatasetStats(
            candidates=len(candidates),
            eligible=sum(1 for c in candidates if not c.reasons),
            excluded=dict(sorted(excluded.items())),
        )

    async def samples(self, limit: int = 100) -> list[TrainingSample]:
        key = self.settings.dataset_pseudonym_key
        if key is None or not key.get_secret_value():
            raise DatasetExportDisabledError()
        candidates = await self._candidates()
        consents, live_refs = await self._judge(candidates)
        eligible = sorted(
            (c for c in candidates if not c.reasons), key=lambda c: c.feedback.created_at
        )[:limit]
        return [
            await self._sample(
                c, consents[c.artwork.owner_id], live_refs[c.feedback.id], key.get_secret_value()
            )
            for c in eligible
        ]

    async def _sample(
        self, c: _Candidate, consent: DatasetConsent, photo_ids: list[uuid.UUID], key: str
    ) -> TrainingSample:
        f, artwork = c.feedback, c.artwork
        is_recording = isinstance(f, FeedbackRecording)
        stages = {
            s.id: s
            for s in (
                await self.session.execute(
                    select(ArtworkStageDef).where(ArtworkStageDef.artwork_id == artwork.id)
                )
            ).scalars()
        }
        photos = {
            p.id: p
            for p in (
                await self.session.execute(
                    select(ArtworkPhoto).where(ArtworkPhoto.id.in_(photo_ids))
                )
            ).scalars()
        }
        images = [
            SampleImage(
                photo_id=pid,
                stage_id=photos[pid].stage_id,
                stage_name=stages[photos[pid].stage_id].name
                if photos[pid].stage_id in stages
                else None,
                legacy_stage=photos[pid].stage,
                position=i,
                uploaded_at=photos[pid].uploaded_at,
            )
            for i, pid in enumerate(photo_ids)
        ]
        targets = [
            SampleTarget(
                priority=t.priority, university_name=t.university_name, department=t.department
            )
            for t in (
                await self.session.execute(
                    select(TargetUniversity)
                    .where(TargetUniversity.user_id == artwork.owner_id)
                    .order_by(TargetUniversity.priority)
                )
            ).scalars()
        ]
        transcript = None
        if is_recording:
            transcript = (
                await self.session.execute(
                    select(FeedbackTranscript)
                    .where(FeedbackTranscript.recording_id == f.id)
                    .order_by(FeedbackTranscript.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        summary_filter = (
            FeedbackSummary.recording_id == f.id
            if is_recording
            else FeedbackSummary.note_id == f.id
        )
        summary = (
            await self.session.execute(
                select(FeedbackSummary).where(
                    summary_filter, FeedbackSummary.status.in_(CURRENT_FEEDBACK_STATUSES)
                )
            )
        ).scalar_one_or_none()
        expert_verified = bool(
            summary
            and summary.status == FeedbackStatus.APPROVED
            and summary.review_mode == ReviewMode.INSTRUCTOR
        )
        labels: list[SampleLabel] = []
        if summary is not None:
            for item in (
                await self.session.execute(
                    select(FeedbackItem)
                    .where(FeedbackItem.summary_id == summary.id)
                    .order_by(FeedbackItem.kind, FeedbackItem.position)
                )
            ).scalars():
                labels.append(
                    SampleLabel(
                        origin=LabelOrigin.AI,
                        # 강사가 확정한 요약의 항목만 확인된 레이블. 학생 본인 확정은 미확인
                        verification=(
                            LabelVerification.CONFIRMED
                            if expert_verified
                            else LabelVerification.UNVERIFIED
                        ),
                        problem_type=item.category,
                        kind=item.kind.value,
                        description=item.content,
                        evidence_segment_ids=list(item.evidence_segment_ids or []),
                    )
                )
        label_filter = (
            FeedbackLabel.feedback_recording_id == f.id
            if is_recording
            else FeedbackLabel.feedback_note_id == f.id
        )
        for label in (
            await self.session.execute(select(FeedbackLabel).where(label_filter))
        ).scalars():
            labels.append(
                SampleLabel(
                    origin=label.origin,
                    verification=label.verification,
                    problem_type=label.problem_type,
                    kind=None,
                    target_object=label.target_object,
                    photo_id=label.photo_id,
                    region=label.region,
                    description=label.description,
                    recommendation=label.recommendation,
                    severity=label.severity,
                    evidence_segment_ids=list(label.evidence_segment_ids or []),
                )
            )
        stage = stages.get(f.stage_id) if f.stage_id else None
        return TrainingSample(
            sample_id=f.id,
            feedback_type="RECORDING" if is_recording else "NOTE",
            learner=pseudonym(key, artwork.owner_id),
            artwork_id=artwork.id,
            images=images,
            feedback_stage=stage.name if stage else None,
            practical_type=artwork.practical_type,
            work_category=artwork.work_category,
            topic=artwork.topic,
            exam_materials=artwork.exam_materials,
            target_universities=targets,
            source=FeedbackSource.INSTRUCTOR,
            raw_text=None if is_recording else f.body,  # type: ignore[union-attr]
            transcript=transcript.text if transcript else None,
            transcript_edited=(transcript.edited_from_id is not None) if transcript else None,
            ai_summary=summary.summary if summary else None,
            ai_summary_status=summary.status if summary else None,
            expert_verified=expert_verified,
            labels=labels,
            feedback_created_at=f.created_at,
            consent_version=consent.policy_version,
            consent_age_band=consent.age_band,
        )
