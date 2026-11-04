"""질문 대기열 변경 알림 (실시간 확장 지점).

v0.5는 REST 폴링이다. 대기열 상태가 바뀔 때마다 서비스는 커밋 후 `publish()`를 호출하지만,
기본 구현(`NullHelpQueuePublisher`)은 아무 것도 하지 않는다.

SSE/WebSocket을 도입할 때는 이 프로토콜을 구현한 브로드캐스터(예: Redis pub/sub, PostgreSQL
LISTEN/NOTIFY)를 `app.state.help_publisher`에 넣고, 구독 엔드포인트에서 `class_id`별로 이벤트를
흘려보내면 된다. 서비스 로직은 바뀌지 않는다. 재접속 시 놓친 이벤트는 help_queue_events 테이블로
복구할 수 있다.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models.enums import HelpQueueEventType, HelpRequestStatus


@dataclass(frozen=True, slots=True)
class HelpQueueChange:
    academy_id: uuid.UUID
    class_id: uuid.UUID
    help_request_id: uuid.UUID
    event_type: HelpQueueEventType
    status: HelpRequestStatus
    occurred_at: datetime


class HelpQueuePublisher(Protocol):
    async def publish(self, change: HelpQueueChange) -> None: ...


class NullHelpQueuePublisher:
    async def publish(self, change: HelpQueueChange) -> None:
        return None


class RecordingHelpQueuePublisher:
    """테스트·디버깅용: 발행된 변경을 메모리에 쌓는다."""

    def __init__(self) -> None:
        self.changes: list[HelpQueueChange] = []

    async def publish(self, change: HelpQueueChange) -> None:
        self.changes.append(change)
