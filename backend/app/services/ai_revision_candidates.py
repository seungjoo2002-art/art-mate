"""AI 수정본에 반영할 개선사항 후보 (v1.3). 새 AI 분석 없이 기존 AI 첨삭 정리 결과만 쓴다.

대상 피드백 (단계별 피드백 화면의 '이 사진 피드백'과 같은 기준)
- 같은 단계(stage_id)의 녹음(ACTIVE)·글 첨삭이면서, 기준 사진(feedback_image_refs)이 **지금 이 사진
  행**
  인 피드백만. 교체 전 사진을 기준으로 한 피드백, 단계 공통·작품 전체·다른 단계 피드백은 넣지
  않는다.

개선사항
- 각 피드백의 현재 첨삭(DRAFT·IN_REVIEW·APPROVED) 항목 중 부족한 점(WEAKNESS)·수정 방법(FIX).
- 시간 관리(TIME_MANAGEMENT)처럼 그림으로 보여 줄 수 없는 카테고리는 뺀다.
- 같은 카테고리·종류에서 글자가 거의 같은 항목(정규화 후 유사도 ≥ 0.85)은 하나로 합친다 (규칙 기반,
  LLM 호출 없음 → 피드백에 없는 내용이 생기지 않는다).
- key: 카테고리·종류·정규화 문장의 해시 → 같은 내용이면 같은 key (요청 때 서버가 다시 계산해 대조).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feedback import FeedbackItem, FeedbackNote, FeedbackSummary
from app.models.dataset import FeedbackImageRef
from app.models.enums import (
    CURRENT_FEEDBACK_STATUSES,
    WEAKNESS_CATEGORY_LABELS,
    FeedbackItemKind,
    RecordingStatus,
    WeaknessCategory,
)
from app.models.recording import FeedbackRecording

# 이미지로 반영할 수 없는 카테고리
EXCLUDED_CATEGORIES: frozenset[WeaknessCategory] = frozenset({WeaknessCategory.TIME_MANAGEMENT})
IMPROVEMENT_KINDS: tuple[FeedbackItemKind, ...] = (FeedbackItemKind.WEAKNESS, FeedbackItemKind.FIX)
KIND_LABELS = {FeedbackItemKind.WEAKNESS: "부족한 점", FeedbackItemKind.FIX: "수정 방법"}
SIMILARITY = 0.85
# 화면·프롬프트 표시 순서 (형태·비례·구도 → 명암·색채 → 재질·묘사 → 기타)
CATEGORY_ORDER: tuple[WeaknessCategory, ...] = (
    WeaknessCategory.FORM,
    WeaknessCategory.PROPORTION,
    WeaknessCategory.COMPOSITION,
    WeaknessCategory.PERSPECTIVE,
    WeaknessCategory.VALUE,
    WeaknessCategory.COLOR,
    WeaknessCategory.TEXTURE,
    WeaknessCategory.RENDERING,
    WeaknessCategory.FINISH,
    WeaknessCategory.OTHER,
)
MAX_CANDIDATES = 20

_NON_WORD = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    return _NON_WORD.sub("", text).lower()


def candidate_key(category: WeaknessCategory, kind: FeedbackItemKind, text: str) -> str:
    raw = f"{category.value}|{kind.value}|{normalize(text)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class Candidate:
    key: str
    category: WeaknessCategory
    kind: FeedbackItemKind
    text: str
    sources: list[dict[str, str]] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        return {
            "key": self.key,
            "category": self.category.value,
            "category_label": WEAKNESS_CATEGORY_LABELS[self.category],
            "kind": self.kind.value,
            "kind_label": KIND_LABELS[self.kind],
            "text": self.text,
            "sources": self.sources,
        }


@dataclass
class CandidateSet:
    candidates: list[Candidate]
    # 이 사진에 연결된 피드백 수 / 그중 AI 첨삭 정리가 없는 수
    feedback_count: int
    unsummarized_count: int
    # 생성 당시 참조한 피드백 (스냅샷용)
    source_feedback: list[dict[str, object]]

    def by_key(self) -> dict[str, Candidate]:
        return {c.key: c for c in self.candidates}


async def _linked_feedback(
    session: AsyncSession, stage_id: uuid.UUID, photo_id: uuid.UUID
) -> tuple[list[FeedbackRecording], list[FeedbackNote]]:
    refs = (
        await session.execute(
            select(FeedbackImageRef.feedback_recording_id, FeedbackImageRef.feedback_note_id).where(
                FeedbackImageRef.photo_id == photo_id
            )
        )
    ).all()
    recording_ids = [r for r, _ in refs if r is not None]
    note_ids = [n for _, n in refs if n is not None]
    recordings: list[FeedbackRecording] = []
    notes: list[FeedbackNote] = []
    if recording_ids:
        recordings = list(
            (
                await session.execute(
                    select(FeedbackRecording)
                    .where(
                        FeedbackRecording.id.in_(recording_ids),
                        FeedbackRecording.stage_id == stage_id,
                        FeedbackRecording.status == RecordingStatus.ACTIVE,
                    )
                    .order_by(FeedbackRecording.created_at, FeedbackRecording.id)
                )
            ).scalars()
        )
    if note_ids:
        notes = list(
            (
                await session.execute(
                    select(FeedbackNote)
                    .where(FeedbackNote.id.in_(note_ids), FeedbackNote.stage_id == stage_id)
                    .order_by(FeedbackNote.created_at, FeedbackNote.id)
                )
            ).scalars()
        )
    return recordings, notes


async def collect(session: AsyncSession, stage_id: uuid.UUID, photo_id: uuid.UUID) -> CandidateSet:
    recordings, notes = await _linked_feedback(session, stage_id, photo_id)
    feedback: list[tuple[str, uuid.UUID]] = [("RECORDING", r.id) for r in recordings] + [
        ("NOTE", n.id) for n in notes
    ]
    summaries: dict[uuid.UUID, FeedbackSummary] = {}
    if feedback:
        rows = (
            await session.execute(
                select(FeedbackSummary).where(
                    FeedbackSummary.status.in_(CURRENT_FEEDBACK_STATUSES),
                    (FeedbackSummary.recording_id.in_([r.id for r in recordings]))
                    | (FeedbackSummary.note_id.in_([n.id for n in notes])),
                )
            )
        ).scalars()
        for s in rows:
            key = s.recording_id or s.note_id
            if key is not None:
                summaries[key] = s

    items_by_summary: dict[uuid.UUID, list[FeedbackItem]] = {}
    if summaries:
        items = (
            await session.execute(
                select(FeedbackItem)
                .where(
                    FeedbackItem.summary_id.in_([s.id for s in summaries.values()]),
                    FeedbackItem.kind.in_(IMPROVEMENT_KINDS),
                )
                .order_by(FeedbackItem.kind, FeedbackItem.position, FeedbackItem.id)
            )
        ).scalars()
        for item in items:
            items_by_summary.setdefault(item.summary_id, []).append(item)

    merged: list[Candidate] = []
    source_feedback: list[dict[str, object]] = []
    for type_, feedback_id in feedback:
        summary = summaries.get(feedback_id)
        if summary is None:
            continue
        source_feedback.append(
            {
                "type": type_,
                "id": str(feedback_id),
                "summary_id": str(summary.id),
                "summary_version": summary.version,
            }
        )
        for item in items_by_summary.get(summary.id, []):
            category = item.category or WeaknessCategory.OTHER
            if category in EXCLUDED_CATEGORIES or not item.content.strip():
                continue
            source = {
                "feedback_type": type_,
                "feedback_id": str(feedback_id),
                "item_id": str(item.id),
            }
            norm = normalize(item.content)
            same = next(
                (
                    c
                    for c in merged
                    if c.category == category
                    and c.kind == item.kind
                    and SequenceMatcher(None, normalize(c.text), norm).ratio() >= SIMILARITY
                ),
                None,
            )
            if same is not None:
                same.sources.append(source)
                continue
            text = item.content.strip()
            merged.append(
                Candidate(
                    key=candidate_key(category, item.kind, text),
                    category=category,
                    kind=item.kind,
                    text=text,
                    sources=[source],
                )
            )

    rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    kind_rank = {FeedbackItemKind.WEAKNESS: 0, FeedbackItemKind.FIX: 1}
    merged.sort(key=lambda c: (rank.get(c.category, len(rank)), kind_rank[c.kind]))
    return CandidateSet(
        candidates=merged[:MAX_CANDIDATES],
        feedback_count=len(feedback),
        unsummarized_count=sum(1 for _, fid in feedback if fid not in summaries),
        source_feedback=source_feedback,
    )
