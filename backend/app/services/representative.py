"""단계 대표 사진 = 그 단계에서 가장 먼저 등록한 사진 (등록 시각, 같으면 id 순).

학생이 직접 대표를 고르던 시절의 is_representative 값은 DB에 남아 있지만 화면·목록·비교·공유
어디서도 읽지 않고 이 규칙으로 계산한다 (데이터를 고치지 않고 목록·상세가 같은 사진).
교체한 사진은 교체 전 사진의 등록 시각을 이어받으므로 그 자리가 그대로 대표다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from app.models.artwork import ArtworkPhoto
from app.models.enums import PhotoStatus


def registration_key(photo: ArtworkPhoto) -> tuple:  # type: ignore[type-arg]
    """등록 순서 정렬 키 (서버가 삭제 후 다음 대표를 고르는 순서와 같음)."""
    return (photo.uploaded_at or photo.created_at, str(photo.id))


def representative_ids(photos: Iterable[ArtworkPhoto]) -> set[uuid.UUID]:
    """단계(stage_id)마다 가장 먼저 등록한 ACTIVE 사진의 id."""
    first: dict[uuid.UUID, ArtworkPhoto] = {}
    for photo in photos:
        if photo.status != PhotoStatus.ACTIVE:
            continue
        current = first.get(photo.stage_id)
        if current is None or registration_key(photo) < registration_key(current):
            first[photo.stage_id] = photo
    return {p.id for p in first.values()}
