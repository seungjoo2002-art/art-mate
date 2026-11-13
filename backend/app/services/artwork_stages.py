"""작품 단계 (v0.9.7): 학생이 단계 개수·이름·순서를 정한다.

- 새 작품 기본: 스케치 / 채색 / 완성 (요청에 stages가 있으면 그대로)
- 기존 작품: 0014 마이그레이션이 이전 고정 3단계(스케치·중간 작업·완성)를 옮겨 둠
- 단계 목록 교체(replace): 이름 변경·순서 변경·추가·빼기를 한 번에.
  뺀 단계에 사진·녹음·글 첨삭이 하나라도 연결돼 있으면 지우지 않고 숨긴다(archived_at)
  → 데이터 보존.
  숨긴 단계를 다시 목록에 넣으면(id 포함) 복원된다.
- legacy_stage(SKETCH·PROGRESS·FINAL)는 위치로 계산해 단계와 사진에 함께 저장한다:
  첫 단계 SKETCH, 마지막 단계 FINAL, 나머지 PROGRESS (단계가 1개면 FINAL) → 진행도, "완성 사진이
  있어야 작품 완료" 같은 기존 규칙이 사용자 정의 단계에서도 그대로 동작한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import UnprocessableError
from app.models.ai_feedback import FeedbackNote
from app.models.artwork import MAX_ARTWORK_STAGES, Artwork, ArtworkPhoto, ArtworkStageDef
from app.models.enums import ArtworkStage, PhotoKind
from app.models.recording import FeedbackRecording

DEFAULT_STAGE_NAMES = ("스케치", "채색", "완성")


@dataclass(frozen=True, slots=True)
class StageSpec:
    name: str
    target_minutes: int | None = None
    id: uuid.UUID | None = None


def legacy_for(position: int, count: int) -> ArtworkStage:
    if position == count - 1:
        return ArtworkStage.FINAL
    if position == 0:
        return ArtworkStage.SKETCH
    return ArtworkStage.PROGRESS


async def active_stages(session: AsyncSession, artwork_id: uuid.UUID) -> list[ArtworkStageDef]:
    return list(
        (
            await session.execute(
                select(ArtworkStageDef)
                .where(
                    ArtworkStageDef.artwork_id == artwork_id,
                    ArtworkStageDef.archived_at.is_(None),
                )
                .order_by(ArtworkStageDef.position)
            )
        )
        .scalars()
        .all()
    )


async def all_stages(session: AsyncSession, artwork_id: uuid.UUID) -> list[ArtworkStageDef]:
    """활성 단계(순서대로) 뒤에 숨긴 단계(숨긴 순서대로)."""
    rows = (
        (
            await session.execute(
                select(ArtworkStageDef).where(ArtworkStageDef.artwork_id == artwork_id)
            )
        )
        .scalars()
        .all()
    )
    active = sorted((s for s in rows if s.archived_at is None), key=lambda s: s.position)
    archived = sorted(
        (s for s in rows if s.archived_at is not None), key=lambda s: (s.archived_at, s.position)
    )
    return active + archived


def _validate(specs: list[StageSpec]) -> list[StageSpec]:
    if not 1 <= len(specs) <= MAX_ARTWORK_STAGES:
        raise UnprocessableError(
            f"An artwork needs 1 to {MAX_ARTWORK_STAGES} stages",
            details={"max_stages": MAX_ARTWORK_STAGES},
        )
    ids = [s.id for s in specs if s.id is not None]
    if len(ids) != len(set(ids)):
        raise UnprocessableError("A stage is listed twice")
    return specs


def create_stages(artwork: Artwork, specs: list[StageSpec] | None) -> list[ArtworkStageDef]:
    """새 작품의 단계 (세션에 추가하지 않음 — 호출 쪽에서 add)."""
    specs = _validate(specs or [StageSpec(name) for name in DEFAULT_STAGE_NAMES])
    count = len(specs)
    return [
        ArtworkStageDef(
            id=uuid.uuid4(),
            artwork_id=artwork.id,
            owner_id=artwork.owner_id,
            position=i,
            name=spec.name,
            legacy_stage=legacy_for(i, count),
            target_minutes=spec.target_minutes,
        )
        for i, spec in enumerate(specs)
    ]


async def ensure_stages(session: AsyncSession, artwork: Artwork) -> list[ArtworkStageDef]:
    """단계가 없는 작품(마이그레이션 이후 다른 경로로 만든 작품 등)에 기본 단계를 만든다."""
    stages = await active_stages(session, artwork.id)
    if stages:
        return stages
    created = create_stages(artwork, None)
    session.add_all(created)
    await session.flush()
    return created


async def _has_data(session: AsyncSession, stage_id: uuid.UUID) -> bool:
    """사진(상태 무관)·녹음(삭제 포함)·글 첨삭이 하나라도 연결돼 있음 → 지우지 않고 숨긴다."""
    for model in (ArtworkPhoto, FeedbackRecording, FeedbackNote):
        found = (
            await session.execute(select(func.count()).where(model.stage_id == stage_id))
        ).scalar_one()
        if found:
            return True
    return False


@dataclass(frozen=True, slots=True)
class ReplaceResult:
    archived: list[uuid.UUID]  # 데이터가 있어 숨긴 단계
    deleted: list[uuid.UUID]  # 데이터가 없어 지운 단계


async def replace_stages(
    session: AsyncSession, artwork: Artwork, specs: list[StageSpec]
) -> ReplaceResult:
    """단계 목록을 specs(순서대로)로 바꾼다. 호출 쪽에서 작품 행을 잠그고 커밋한다."""
    specs = _validate(specs)
    existing = {
        s.id: s
        for s in (
            await session.execute(
                select(ArtworkStageDef).where(ArtworkStageDef.artwork_id == artwork.id)
            )
        )
        .scalars()
        .all()
    }
    unknown = [s.id for s in specs if s.id is not None and s.id not in existing]
    if unknown:
        raise UnprocessableError(
            "Unknown stage for this artwork", details={"stage_id": str(unknown[0])}
        )

    # 활성 위치 유니크와 겹치지 않게 먼저 임시 위치로 옮긴다
    for stage in existing.values():
        if stage.archived_at is None:
            stage.position += 1000
    await session.flush()

    keep = {s.id for s in specs if s.id is not None}
    archived: list[uuid.UUID] = []
    deleted: list[uuid.UUID] = []
    now = clock.utc_now()
    for stage_id, stage in existing.items():
        if stage_id in keep or stage.archived_at is not None:
            continue
        if await _has_data(session, stage_id):
            stage.archived_at = now
            archived.append(stage_id)
        else:
            await session.delete(stage)
            deleted.append(stage_id)
    await session.flush()

    count = len(specs)
    final: list[ArtworkStageDef] = []
    for i, spec in enumerate(specs):
        legacy = legacy_for(i, count)
        if spec.id is not None:
            stage = existing[spec.id]
            stage.name = spec.name
            stage.position = i
            stage.target_minutes = spec.target_minutes
            stage.archived_at = None  # 숨긴 단계를 다시 넣으면 복원
            stage.legacy_stage = legacy
        else:
            stage = ArtworkStageDef(
                id=uuid.uuid4(),
                artwork_id=artwork.id,
                owner_id=artwork.owner_id,
                position=i,
                name=spec.name,
                legacy_stage=legacy,
                target_minutes=spec.target_minutes,
            )
            session.add(stage)
        final.append(stage)
    await session.flush()
    # 사진의 호환용 단계 값도 새 위치에 맞춘다 (진행도·완료 조건)
    for stage in final:
        await session.execute(
            update(ArtworkPhoto)
            .where(ArtworkPhoto.stage_id == stage.id, ArtworkPhoto.stage != stage.legacy_stage)
            .values(stage=stage.legacy_stage)
        )
    return ReplaceResult(archived=archived, deleted=deleted)


async def resolve_stage(
    session: AsyncSession,
    artwork: Artwork,
    stage_id: uuid.UUID | None,
    legacy: ArtworkStage | None = None,
) -> ArtworkStageDef:
    """업로드 등에서 쓰는 단계 (활성 단계만). stage_id 우선, 없으면 이전 고정 단계 값으로 찾는다."""
    stages = await ensure_stages(session, artwork)
    if stage_id is not None:
        found = next((s for s in stages if s.id == stage_id), None)
        if found is None:
            raise UnprocessableError(
                "The stage does not belong to this artwork or is hidden",
                details={"stage_id": str(stage_id)},
            )
        return found
    if legacy is not None:
        found = next((s for s in stages if s.legacy_stage == legacy), None)
        if found is None:
            raise UnprocessableError(
                "This artwork has no stage for the given legacy stage",
                details={"stage": legacy.value},
            )
        return found
    raise UnprocessableError("stage_id is required")


async def check_feedback_stage(
    session: AsyncSession, artwork: Artwork, stage_id: uuid.UUID | None
) -> uuid.UUID | None:
    """피드백(녹음·글 첨삭)에 붙일 단계 확인. None = 작품 전체."""
    if stage_id is None:
        return None
    return (await resolve_stage(session, artwork, stage_id)).id


async def check_revisions_follow(
    session: AsyncSession, stage_id: uuid.UUID, linked: ColumnElement[bool]
) -> None:
    """피드백을 단계에 붙일 때, 이미 연결된 수정 사진이 다른 단계에 있으면 거부한다.

    (수정 사진은 피드백과 같은 단계에 둔다. 작품 전체 피드백으로 바꾸는 것은 항상 허용)
    """
    other = (
        await session.execute(
            select(func.count()).where(
                linked,
                ArtworkPhoto.kind == PhotoKind.REVISION,
                ArtworkPhoto.stage_id != stage_id,
            )
        )
    ).scalar_one()
    if other:
        raise UnprocessableError(
            "Revision photos of this feedback are in another stage",
            details={"revision_photos_elsewhere": other},
        )


def in_active_stage() -> ColumnElement[bool]:
    """사진이 숨기지 않은 단계에 있음 (숨긴 단계의 사진은 보존하지만 진행도·공유 등에서 뺀다)."""
    return exists().where(
        ArtworkStageDef.id == ArtworkPhoto.stage_id, ArtworkStageDef.archived_at.is_(None)
    )


def visible_stage_photo() -> ColumnElement[bool]:
    """숨기지 않은 단계의 사진 (v0.9.8부터 피드백 뒤 사진도 일반 사진과 같음)."""
    return in_active_stage()
