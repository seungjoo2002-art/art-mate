"""외부 AI 전송 전 개인정보 최소화 (v0.9.6)."""

from app.services.ai_redaction import redact_segments, redact_text


def test_masks_contact_formats() -> None:
    text = (
        "연락은 010-1234-5678이나 010 9876 5432, 01055556666, 02-123-4567로 하고 "
        "메일은 kim.minsu@example.com, 주민번호 050101-3123456, 카드 1234-5678-9012-3456, "
        "자료는 https://example.com/a 에 있어."
    )
    masked, count = redact_text(text)
    for leaked in (
        "1234-5678",
        "9876",
        "01055556666",
        "123-4567",
        "example.com",
        "3123456",
        "9012",
    ):
        assert leaked not in masked
    assert masked.count("[전화번호]") == 4
    assert "[이메일]" in masked and "[주민번호]" in masked and "[카드번호]" in masked
    assert "[링크]" in masked
    assert count == 8


def test_masks_student_names_but_keeps_art_terms() -> None:
    masked, count = redact_text(
        "민수야 명암이 약해. 김민수 학생은 소실점을 다시 잡자.", ["김민수", "민수", None, "김"]
    )
    assert masked == "[학생]야 명암이 약해. [학생] 학생은 소실점을 다시 잡자."
    assert count == 2
    # 한 글자 이름은 오탐이 많아 가리지 않음, 숫자로 된 미술 표현은 그대로
    masked, count = redact_text("3점 투시, 2시간 안에 끝내. 4B 연필로 120도 각도", ["김"])
    assert (masked, count) == ("3점 투시, 2시간 안에 끝내. 4B 연필로 120도 각도", 0)


def test_segments_keep_index_and_times() -> None:
    segments = [
        {"index": 0, "start_ms": 0, "end_ms": 3000, "text": "지은아 구도는 좋아."},
        {"index": 1, "start_ms": 3000, "end_ms": 6000, "text": "명암을 더 눌러."},
    ]
    result = redact_segments(segments, ["지은"])
    assert [s["text"] for s in result.segments] == ["[학생]아 구도는 좋아.", "명암을 더 눌러."]
    assert [(s["index"], s["start_ms"], s["end_ms"]) for s in result.segments] == [
        (0, 0, 3000),
        (1, 3000, 6000),
    ]
    assert segments[0]["text"] == "지은아 구도는 좋아."  # 원본은 그대로
    assert result.replaced == 1
