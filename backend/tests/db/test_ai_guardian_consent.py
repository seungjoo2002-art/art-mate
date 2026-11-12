"""v0.9.6 연령 확인·보호자 동의·외부 전송 차단 (가짜 LLM — 실제 API 호출 없음)."""

import httpx

from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import AI_VERSION, _base, _sql
from tests.db.test_recordings_api import _consent, _record
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt
from tests.fake_storage import FakeStorage

API = "/api/v1"
CONSENTS = f"{API}/ai-processing-consents"
SEGMENTS = [
    {"start_ms": 0, "end_ms": 3500, "text": "전체적으로 구도는 안정적으로 잘 잡았어."},
    {
        "start_ms": 4000,
        "end_ms": 7500,
        "text": "근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보여.",
    },
    {
        "start_ms": 8000,
        "end_ms": 11500,
        "text": "어두운 면을 한 톤 더 눌러주고 반사광은 조금만 남겨.",
    },
    {
        "start_ms": 12000,
        "end_ms": 15500,
        "text": "다음 작품에서는 처음부터 큰 덩어리 명암을 먼저 잡자.",
    },
]


def _grant(birth: str) -> dict:
    return {"policy_version": AI_VERSION, "agreed": True, "birth_year_month": birth}


def _runner(app, llm: FakeLlm) -> JobRunner:  # type: ignore[no-untyped-def]
    return JobRunner(
        app.state.database,
        app.state.settings,
        stt=FakeStt(),
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="test",
    )


async def _transcribed(client, audio: FakeStorage, student) -> str:  # type: ignore[no-untyped-def]
    artwork = await client.post(f"{API}/artworks", json={"title": "소묘"}, headers=student.headers)
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(client, audio, student, artwork.json()["id"])
    base = _base(artwork.json()["id"], recorded.json()["id"])
    body = {"device": "wasm", "model_name": "onnx-community/whisper-base", "segments": SEGMENTS}
    saved = await client.post(f"{base}/transcript/browser", json=body, headers=student.headers)
    assert saved.status_code == 201, saved.text
    return base


async def test_minor_needs_guardian_link_then_summary_works(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    base = await _transcribed(client, app.state.audio_storage, student)

    granted = await client.post(CONSENTS, json=_grant("2010-03"), headers=student.headers)
    assert granted.status_code == 201, granted.text
    status = granted.json()
    assert (status["is_valid"], status["reason"]) == (False, "GUARDIAN_PENDING")
    assert status["provider"] == "OPENAI"
    assert status["consent"]["age_band"] == "MINOR"
    assert status["consent"]["granted_by"] == "GUARDIAN"
    token = status["guardian_token"]
    assert token and status["guardian_token_expires_at"]
    # 생년월은 저장하지 않는다 (연령 구간만)
    stored = await _sql(
        app, "SELECT * FROM ai_processing_consents WHERE user_id = :u", u=student.user_id
    )
    assert "2010" not in str(stored) and token not in str(stored)
    # 학생 상태 조회에는 토큰이 다시 나오지 않음
    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert me["guardian_token"] is None and me["reason"] == "GUARDIAN_PENDING"

    # 보호자 확인 전: 외부 전송 차단 (요약 요청 409, 작업 없음)
    blocked = await client.post(f"{base}/summary", headers=student.headers)
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (409, "AI_CONSENT_REQUIRED")

    # 보호자: 로그인 없이 링크로 확인 (학생 정보·전사 내용은 보이지 않음)
    view = await client.get(f"{API}/guardian-consents/{token}")
    assert view.status_code == 200
    assert view.json()["status"] == "PENDING" and view.json()["age_band"] == "MINOR"
    assert "구도" not in view.text and str(student.user_id) not in view.text
    bad = await client.post(
        f"{API}/guardian-consents/{token}",
        json={"guardian_name": "보호자", "relationship": "PARENT", "agreed": False},
    )
    assert bad.status_code == 422
    confirmed = await client.post(
        f"{API}/guardian-consents/{token}",
        json={"guardian_name": "김보호", "relationship": "PARENT", "agreed": True},
    )
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "CONFIRMED"
    # 링크는 한 번만
    assert (await client.get(f"{API}/guardian-consents/{token}")).status_code == 404

    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert me["is_valid"] is True and me["consent"]["guardian_relationship"] == "PARENT"
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202
    llm = FakeLlm()
    assert await _runner(app, llm).run_once() is True
    assert llm.prompts  # 확인 후에는 전송
    assert (await client.get(f"{base}/summary", headers=student.headers)).json()["feedback_id"]


async def test_under_13_blocked_until_operator_zdr(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    base = await _transcribed(client, app.state.audio_storage, student)
    token = (await client.post(CONSENTS, json=_grant("2015-05"), headers=student.headers)).json()[
        "guardian_token"
    ]
    await client.post(
        f"{API}/guardian-consents/{token}",
        json={"guardian_name": "이보호", "relationship": "LEGAL_GUARDIAN", "agreed": True},
    )
    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert (me["is_valid"], me["reason"]) == (False, "UNDER_13_BLOCKED")
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 409

    app.state.settings = app.state.settings.model_copy(update={"ai_zdr_approved": True})
    assert (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()["is_valid"]
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202

    # 작업이 큐에 있는 동안 승인이 꺼지면 Worker가 보내기 직전에 취소 (외부 전송 없음)
    app.state.settings = app.state.settings.model_copy(update={"ai_zdr_approved": False})
    llm = FakeLlm()
    await _runner(app, llm).run_once()
    assert llm.prompts == []
    job = (await client.get(f"{base}/summary", headers=student.headers)).json()["job"]
    assert (job["status"], job["error_code"]) == ("CANCELLED", "AI_CONSENT_REVOKED")


async def test_adult_self_consent_provider_switch_and_links(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    adult = await client.post(CONSENTS, json=_grant("2001-07"), headers=student.headers)
    assert adult.json()["is_valid"] and adult.json()["guardian_token"] is None
    # 성인은 보호자 링크 재발급 대상 아님
    renew = await client.post(f"{CONSENTS}/me/guardian-link", headers=student.headers)
    assert renew.status_code == 409

    # 제공자를 바꾸면 이전 제공자 동의로는 보낼 수 없다 (다시 동의)
    app.state.settings = app.state.settings.model_copy(update={"ai_provider": "gemini"})
    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert (me["provider"], me["is_valid"], me["consent"]) == ("GOOGLE_GEMINI", False, None)
    app.state.settings = app.state.settings.model_copy(update={"ai_provider": "openai"})

    # 미성년자 링크 재발급: 이전 링크는 무효
    other = await actors.signup("STUDENT")
    first = (await client.post(CONSENTS, json=_grant("2009-01"), headers=other.headers)).json()
    second = (await client.post(f"{CONSENTS}/me/guardian-link", headers=other.headers)).json()
    assert second["guardian_token"] and second["guardian_token"] != first["guardian_token"]
    assert (
        await client.get(f"{API}/guardian-consents/{first['guardian_token']}")
    ).status_code == 404
    assert (
        await client.get(f"{API}/guardian-consents/{second['guardian_token']}")
    ).status_code == 200

    # 만료된 링크
    await _sql(
        app,
        "UPDATE ai_processing_consents SET guardian_token_expires_at = now() - interval '1 minute'"
        " WHERE user_id = :u AND revoked_at IS NULL",
        u=other.user_id,
    )
    expired = await client.get(f"{API}/guardian-consents/{second['guardian_token']}")
    assert (expired.status_code, expired.json()["error"]["code"]) == (404, "GUARDIAN_LINK_INVALID")
    # 형식이 틀린 토큰
    assert (await client.get(f"{API}/guardian-consents/short")).status_code == 422
