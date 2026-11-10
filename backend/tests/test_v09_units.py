"""v0.9 순수 로직 단위 테스트 (DB 없음): 문장 분할·근거 대조·타이머 계산·출처/시간 통계."""

import uuid
from datetime import UTC, date, datetime, timedelta

from app.models.enums import (
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    FeedbackSource,
    ReportStatus,
    TimerEventType,
    TimerState,
    WeaknessCategory,
)
from app.services.ai_summary import (
    MAX_NOTE_SEGMENTS,
    TEXT_SYSTEM_INSTRUCTION,
    build_text_prompt,
    is_grounded,
    parse_output,
    split_segments,
)
from app.services.artwork_timer import Replay
from app.services.growth_analytics import (
    ArtworkFact,
    Dataset,
    FeedbackFact,
    analyze,
    time_stats,
)
from tests.fake_ai import SEGMENTS, ai_json

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def test_split_segments_by_sentence_and_length() -> None:
    parts = split_segments("구도는 좋다. 명암이 약하다!\n\n다음엔 큰 덩어리부터?  끝")
    assert [p["text"] for p in parts] == [
        "구도는 좋다.",
        "명암이 약하다!",
        "다음엔 큰 덩어리부터?",
        "끝",
    ]
    assert [p["index"] for p in parts] == [0, 1, 2, 3]
    long = split_segments("가" * 900)
    assert [len(p["text"]) for p in long] == [400, 400, 100]
    many = split_segments("\n".join(f"문장{i}" for i in range(300)))
    assert len(many) == MAX_NOTE_SEGMENTS


def test_grounding_check() -> None:
    assert is_grounded("오른쪽 사과의 명암이 약하다", [SEGMENTS[1]])
    assert not is_grounded("채도 대비가 훌륭하다", [SEGMENTS[1]])
    assert not is_grounded("", [SEGMENTS[0]])
    # 원문 대조 없이(segment_texts 없음)는 기존 동작 그대로
    _, dropped = parse_output(ai_json(), 4)
    assert dropped == 0
    invented = ai_json(
        strengths=[{"text": "채색이 아주 훌륭하다", "category": "COLOR", "evidence": [0]}]
    )
    output, dropped = parse_output(invented, 4, SEGMENTS)
    assert dropped == 1 and output.strengths == []


def test_text_prompt_has_only_sentences() -> None:
    prompt = build_text_prompt([{"index": 0, "text": "명암을 더 눌러"}])
    assert prompt.endswith("[0] 명암을 더 눌러")
    assert "문장 번호" in TEXT_SYSTEM_INSTRUCTION and "TIME_MANAGEMENT" in TEXT_SYSTEM_INSTRUCTION


def test_timer_replay() -> None:
    r = Replay()
    r.apply(TimerEventType.START, T0)
    assert r.elapsed_at(T0 + timedelta(minutes=10)) == 600
    r.apply(TimerEventType.PAUSE, T0 + timedelta(minutes=10))
    assert r.elapsed_at(T0 + timedelta(hours=5)) == 600  # 일시정지 중에는 늘지 않음
    r.apply(TimerEventType.RESUME, T0 + timedelta(minutes=20))
    r.apply(TimerEventType.STOP, T0 + timedelta(minutes=50))
    assert (r.state, r.elapsed_at(T0 + timedelta(hours=9))) == (TimerState.STOPPED, 2400)
    r.apply(TimerEventType.START, T0 + timedelta(hours=1))  # 새 세션
    assert r.elapsed_at(T0 + timedelta(hours=1, minutes=1)) == 60
    r.apply(TimerEventType.RESET, T0 + timedelta(hours=2))
    assert (r.state, r.elapsed_at(T0 + timedelta(hours=3))) == (TimerState.IDLE, 0)


def _artwork(day: int, minutes: int | None = None, limit: int | None = None, mock: bool = False):  # type: ignore[no-untyped-def]
    return ArtworkFact(
        id=uuid.uuid4(),
        title=f"a{day}",
        work_date=date(2026, 10, day),
        created_at=T0,
        updated_at=T0,
        work_status=ArtworkWorkStatus.COMPLETED,
        completed_at=T0,
        practical_type=None,
        work_category=ArtworkWorkCategory.MOCK_EXAM if mock else None,
        actual_minutes=minutes,
        time_limit_minutes=limit,
    )


def test_time_stats_skip_unrecorded() -> None:
    stats = time_stats(
        [
            _artwork(1, 200, 240, True),
            _artwork(2, 300, 240, True),
            _artwork(3, mock=True),
            _artwork(4, 60),
        ]
    )
    assert stats["recorded_artwork_count"] == 3 and stats["unrecorded_artwork_count"] == 1
    assert stats["total_minutes"] == 560 and stats["average_minutes"] == round(560 / 3, 1)
    assert stats["mock_exam"]["over_limit_count"] == 1
    assert stats["mock_exam"]["timed_count"] == 2 and stats["mock_exam"]["artwork_count"] == 3


def test_unverified_sources_not_in_weakness_stats() -> None:
    artworks = [_artwork(d) for d in (1, 2, 3)]
    feedbacks, categories = [], {}
    for a in artworks:
        for source, category in (
            (FeedbackSource.INSTRUCTOR, WeaknessCategory.VALUE),
            (FeedbackSource.SELF_NOTE, WeaknessCategory.COLOR),
            (FeedbackSource.PEER, WeaknessCategory.COLOR),
        ):
            fid = uuid.uuid4()
            feedbacks.append(FeedbackFact(fid, a.id, T0, 1, source))
            categories[fid] = {category}
    metrics = analyze(Dataset(artworks, feedbacks, categories, []), min_artworks=3, recent_window=5)
    assert metrics["status"] == ReportStatus.READY.value
    assert [w["category"] for w in metrics["weaknesses"]] == ["VALUE"]
    assert metrics["totals"]["approved_feedback_count"] == 3
    assert metrics["source_breakdown"] == {"INSTRUCTOR": 3, "SELF_NOTE": 3, "PEER": 3}
    color = metrics["unverified_mentions"][0]
    assert color["category"] == "COLOR" and color["by_source"] == {"SELF_NOTE": 3, "PEER": 3}
    # 자기 메모만 있는 학생: 분석 대상 0, 안내 문구
    only_self = [f for f in feedbacks if f.source == FeedbackSource.SELF_NOTE]
    metrics = analyze(Dataset(artworks, only_self, categories, []), min_artworks=3, recent_window=5)
    assert metrics["status"] == ReportStatus.INSUFFICIENT_DATA.value
    assert any("참고로만" in g for g in metrics["guidance"])
    assert any("작업 시간" in g for g in metrics["guidance"])
