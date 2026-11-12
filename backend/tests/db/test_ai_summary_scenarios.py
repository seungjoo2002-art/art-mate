"""v0.9.5 AI 첨삭 요약 시나리오 (가짜 Gemini — 실제 API 호출 없음).

녹음 길이별 대본 → 자동 요약 → 결과 저장·복원, 기존 대본 요약, 대본 수정 후 최신 기준 재분석,
요약 실패 후 재시도(대본은 유지), 다른 학생 차단, 동의 없으면 외부 전송 차단.
"""

import httpx
import pytest

from app.integrations.ai.gemini import LlmError
from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import _ai_consent, _base
from tests.db.test_recordings_api import _consent, _record
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt

API = "/api/v1"

# 강사 첨삭 문장 (가짜 LLM 응답 ai_json()의 근거 [0]~[3]과 표현이 겹치도록)
CRITIQUE = [
    "전체적으로 구도는 안정적으로 잘 잡았어.",
    "근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보여.",
    "어두운 면을 한 톤 더 눌러주고 반사광은 조금만 남겨.",
    "다음 작품에서는 처음부터 큰 덩어리 명암을 먼저 잡자.",
]


def _segments(duration_ms: int) -> list[dict]:
    """녹음 길이만큼 4초 간격 구간. 앞 4개는 첨삭, 나머지는 이어지는 설명."""
    count = max(4, duration_ms // 4000)
    out = []
    for i in range(count):
        start = i * 4000
        text = CRITIQUE[i] if i < len(CRITIQUE) else f"{i}번째 부분은 지금처럼 계속 진행하면 돼."
        out.append({"start_ms": start, "end_ms": min(start + 3500, duration_ms), "text": text})
    return out


async def _recording(client, app, student, duration_ms: int) -> str:  # type: ignore[no-untyped-def]
    artwork = await client.post(
        f"{API}/artworks", json={"title": "정물 수채화"}, headers=student.headers
    )
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(
        client, app.state.audio_storage, student, artwork.json()["id"], duration_ms=duration_ms
    )
    assert recorded.status_code == 200, recorded.text
    return _base(artwork.json()["id"], recorded.json()["id"])


def _runner(app, llm: FakeLlm) -> JobRunner:  # type: ignore[no-untyped-def]
    return JobRunner(
        app.state.database,
        app.state.settings,
        stt=FakeStt(),
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="test",
    )


def _browser(segments: list[dict], *, auto: bool) -> dict:
    return {
        "device": "wasm",
        "model_name": "onnx-community/whisper-base",
        "segments": segments,
        "processing_ms": 1000,
        "auto_summarize": auto,
    }


@pytest.mark.parametrize("duration_ms", [30_000, 60_000, 300_000])
async def test_transcript_to_summary_by_length_and_restore(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, duration_ms
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    base = await _recording(client, app, student, duration_ms)
    segments = _segments(duration_ms)

    saved = await client.post(
        f"{base}/transcript/browser", json=_browser(segments, auto=True), headers=student.headers
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["summary_status"] == "QUEUED"  # 대본 저장과 동시에 요약 작업 생성

    llm = FakeLlm()
    assert await _runner(app, llm).run_once() is True
    # 실제로 보낸 것은 구간 번호·시각·문장뿐 (전체 구간 포함)
    assert f"[{len(segments) - 1}]" in llm.prompts[0]

    # 새로고침 = 상태 API를 다시 읽음 → DB에 저장된 결과
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["feedback_id"] and summary["job"]["status"] == "SUCCEEDED"
    feedback = (
        await client.get(f"{API}/feedbacks/{summary['feedback_id']}", headers=student.headers)
    ).json()
    assert feedback["summary"]
    for key in ("strengths", "weaknesses", "fixes", "next_tips"):
        assert feedback[key], key
        # 모든 항목에 원문 근거(구간 문장)가 붙어 있음
        assert all(item["evidence"] and item["evidence"][0]["text"] for item in feedback[key])


async def test_existing_transcript_edit_reanalyze_and_retry(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    base = await _recording(client, app, student, 30_000)
    # 동의 전에 저장한 기존 대본 (요약 없이)
    saved = await client.post(
        f"{base}/transcript/browser",
        json=_browser(_segments(30_000), auto=True),
        headers=student.headers,
    )
    assert saved.json()["summary_status"] == "CONSENT_REQUIRED"
    assert saved.json()["summary_job"] is None
    # 동의 없으면 요약 요청도 거부 → 외부 전송 없음
    denied = await client.post(f"{base}/summary", headers=student.headers)
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "AI_CONSENT_REQUIRED"

    await _ai_consent(client, student)
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202

    # Gemini 실패 → 작업 FAILED(다시 시도 가능), 대본은 그대로
    llm = FakeLlm()
    llm.outcomes.append(LlmError("LLM_AUTH_FAILED", "401", retryable=False))
    assert await _runner(app, llm).run_once() is True
    failed = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert failed["job"]["status"] == "FAILED" and failed["job"]["retryable"] is True
    transcript = await client.get(f"{base}/transcript", headers=student.headers)
    assert transcript.status_code == 200  # AI 실패가 대본에 영향 없음

    retry = await client.post(f"{base}/summary/regenerate", headers=student.headers)
    assert retry.status_code == 202
    assert await _runner(app, FakeLlm()).run_once() is True
    first = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert first["feedback_id"]

    # 같은 대본으로 다시 요청 → 중복 호출하지 않고 409 (재생성은 명시적으로만)
    again = await client.post(f"{base}/summary", headers=student.headers)
    assert again.status_code == 409

    # 대본 수정 → 초안 대체, 최신 대본 기준으로 재분석
    current = transcript.json()
    edited = await client.put(
        f"{base}/transcript",
        json={
            "base_transcript_id": current["id"],
            "segments": [{"index": 1, "text": "오른쪽 사과의 명암이 약해서 형태가 떠 보여."}],
        },
        headers=student.headers,
    )
    assert edited.status_code == 200, edited.text
    new_id = edited.json()["id"]
    assert new_id != current["id"]
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202
    llm = FakeLlm()
    assert await _runner(app, llm).run_once() is True
    assert "오른쪽 사과의 명암이 약해서 형태가 떠 보여." in llm.prompts[0]
    latest = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert latest["feedback_id"] and latest["feedback_id"] != first["feedback_id"]


async def test_other_student_cannot_read_summary(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    owner = await actors.signup("STUDENT")
    other = await actors.signup("STUDENT")
    await _ai_consent(client, owner)
    base = await _recording(client, app, owner, 30_000)
    body = _browser(_segments(30_000), auto=True)
    await client.post(f"{base}/transcript/browser", json=body, headers=owner.headers)
    await _runner(app, FakeLlm()).run_once()
    feedback_id = (await client.get(f"{base}/summary", headers=owner.headers)).json()["feedback_id"]

    for path in (f"{base}/summary", f"{base}/transcript", f"{API}/feedbacks/{feedback_id}"):
        res = await client.get(path, headers=other.headers)
        assert res.status_code == 404, path
    regen = await client.post(f"{base}/summary/regenerate", headers=other.headers)
    assert regen.status_code == 404
