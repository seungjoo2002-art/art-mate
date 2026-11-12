"""v0.9.6 연령별 AI 전송 동의(만 14세 기준)·보호자 확인·전송 차단 (가짜 LLM, 실제 API 호출 없음)."""

import httpx

from app.api.v1.endpoints import ai_feedback as endpoints
from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import AI_VERSION, _base, _sql
from tests.db.test_recordings_api import _consent, _record
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt
from tests.fake_storage import FakeStorage

API = "/api/v1"
CONSENTS = f"{API}/ai-processing-consents"
GUARDIAN = f"{API}/guardian-consents"
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
TEEN = "2010-03"  # 만 16세
CHILD = "2015-05"  # 만 11세
ADULT = "2001-07"


def _grant(birth: str) -> dict:
    return {"policy_version": AI_VERSION, "agreed": True, "birth_year_month": birth}


def _settings(app, **changes) -> None:  # type: ignore[no-untyped-def]
    app.state.settings = app.state.settings.model_copy(update=changes)


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


async def _stored(app, student) -> str:  # type: ignore[no-untyped-def]
    rows = await _sql(
        app, "SELECT * FROM ai_processing_consents WHERE user_id = :u", u=student.user_id
    )
    return str(rows)


async def test_teen_self_consent_when_operator_enables(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    base = await _transcribed(client, app.state.audio_storage, student)

    # 배포 기본값: 만 14~17세 전송 차단, 보호자 링크도 발급하지 않음
    blocked = (await client.post(CONSENTS, json=_grant(TEEN), headers=student.headers)).json()
    assert (blocked["is_valid"], blocked["reason"]) == (False, "TEEN_NOT_ENABLED")
    assert blocked["consent"]["age_band"] == "TEEN" and blocked["guardian_token"] is None
    assert blocked["consent"]["granted_by"] == "SELF"
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 409

    # 운영자가 연령대를 열면 같은 동의로 바로 유효 (국내법상 만 14세 이상 본인 동의)
    _settings(app, ai_teens_enabled=True)
    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert (me["is_valid"], me["reason"]) == (True, None)
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202
    llm = FakeLlm()
    assert await _runner(app, llm).run_once() is True
    assert llm.prompts
    assert "2010" not in await _stored(app, student)  # 생년월은 저장하지 않는다


async def test_teen_guardian_flow_when_required(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    endpoints._guardian_hits.clear()
    _settings(app, ai_teens_enabled=True, ai_teen_guardian_required=True)
    student = await actors.signup("STUDENT")
    base = await _transcribed(client, app.state.audio_storage, student)
    status = (await client.post(CONSENTS, json=_grant(TEEN), headers=student.headers)).json()
    assert (status["is_valid"], status["reason"]) == (False, "GUARDIAN_PENDING")
    assert status["consent"]["granted_by"] == "GUARDIAN"
    token = status["guardian_token"]
    assert token and token not in await _stored(app, student)  # 해시만 저장
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 409

    # 보호자: 토큰은 URL이 아니라 요청 본문으로, 응답은 저장 금지
    view = await client.post(f"{GUARDIAN}/view", json={"token": token})
    assert view.status_code == 200
    assert view.headers["cache-control"] == "no-store"
    assert view.headers["referrer-policy"] == "no-referrer"
    assert view.json()["status"] == "PENDING" and view.json()["age_band"] == "TEEN"
    assert "구도" not in view.text and str(student.user_id) not in view.text
    confirm = {"token": token, "guardian_name": "김보호", "relationship": "PARENT"}
    bad = await client.post(f"{GUARDIAN}/confirm", json=confirm | {"agreed": False})
    assert bad.status_code == 422
    ok = await client.post(f"{GUARDIAN}/confirm", json=confirm | {"agreed": True})
    assert ok.status_code == 200 and ok.json()["status"] == "CONFIRMED"
    assert (await client.post(f"{GUARDIAN}/view", json={"token": token})).status_code == 404

    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert me["is_valid"] and me["consent"]["guardian_relationship"] == "PARENT"
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202


async def test_under_14_blocked_until_operator_zdr_then_guardian(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    endpoints._guardian_hits.clear()
    _settings(app, ai_teens_enabled=True)  # 청소년 허용은 만 14세 미만과 무관
    student = await actors.signup("STUDENT")
    base = await _transcribed(client, app.state.audio_storage, student)
    status = (await client.post(CONSENTS, json=_grant(CHILD), headers=student.headers)).json()
    assert (status["reason"], status["consent"]["age_band"]) == ("UNDER_14_BLOCKED", "UNDER_14")
    assert status["guardian_token"] is None  # 열리지 않은 연령대에는 링크도 안 줌
    renew = await client.post(f"{CONSENTS}/me/guardian-link", headers=student.headers)
    assert renew.status_code == 409

    _settings(app, ai_under14_enabled=True)  # ZDR 승인 없이는 여전히 차단
    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert me["reason"] == "UNDER_14_BLOCKED"

    _settings(app, ai_zdr_approved=True)
    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert me["reason"] == "GUARDIAN_PENDING"  # 법정대리인 확인 필요
    renewed = await client.post(f"{CONSENTS}/me/guardian-link", headers=student.headers)
    token = renewed.json()["guardian_token"]
    await client.post(
        f"{GUARDIAN}/confirm",
        json={
            "token": token,
            "guardian_name": "이보호",
            "relationship": "LEGAL_GUARDIAN",
            "agreed": True,
        },
    )
    assert (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()["is_valid"]
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202

    # 작업이 큐에 있는 동안 운영자가 다시 막으면 Worker가 보내기 직전에 취소 (외부 전송 없음)
    _settings(app, ai_zdr_approved=False)
    llm = FakeLlm()
    await _runner(app, llm).run_once()
    assert llm.prompts == []
    job = (await client.get(f"{base}/summary", headers=student.headers)).json()["job"]
    assert (job["status"], job["error_code"]) == ("CANCELLED", "AI_CONSENT_REVOKED")


async def test_revoked_consent_cancels_before_sending(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    base = await _transcribed(client, app.state.audio_storage, student)
    await client.post(CONSENTS, json=_grant(ADULT), headers=student.headers)
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202
    # 같은 요약 중복 요청 → 새 작업 없이 진행 중 작업 (200)
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 200
    assert (await client.delete(f"{CONSENTS}/me", headers=student.headers)).status_code == 204
    llm = FakeLlm()
    await _runner(app, llm).run_once()
    assert llm.prompts == []
    job = (await client.get(f"{base}/summary", headers=student.headers)).json()["job"]
    assert (job["status"], job["error_code"]) == ("CANCELLED", "AI_CONSENT_REVOKED")


async def test_guardian_links_renew_expire_and_rate_limit(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    endpoints._guardian_hits.clear()
    _settings(app, ai_teens_enabled=True, ai_teen_guardian_required=True)
    student = await actors.signup("STUDENT")
    first = (await client.post(CONSENTS, json=_grant(TEEN), headers=student.headers)).json()
    second = (await client.post(f"{CONSENTS}/me/guardian-link", headers=student.headers)).json()
    assert second["guardian_token"] != first["guardian_token"]

    async def view(token: str) -> httpx.Response:
        return await client.post(f"{GUARDIAN}/view", json={"token": token})

    assert (await view(first["guardian_token"])).status_code == 404
    assert (await view(second["guardian_token"])).status_code == 200

    await _sql(
        app,
        "UPDATE ai_processing_consents SET guardian_token_expires_at = now() - interval '1 minute'"
        " WHERE user_id = :u AND revoked_at IS NULL",
        u=student.user_id,
    )
    expired = await view(second["guardian_token"])
    assert (expired.status_code, expired.json()["error"]["code"]) == (404, "GUARDIAN_LINK_INVALID")
    assert (await view("short")).status_code == 422
    # 옛 방식(토큰이 URL 경로에 있는 GET)은 없음
    old = await client.get(f"{GUARDIAN}/{second['guardian_token']}")
    assert old.status_code in (404, 405)

    # 같은 클라이언트의 반복 요청 제한
    endpoints._guardian_hits.clear()
    codes = [
        (await view("x" * 40)).status_code for _ in range(endpoints._GUARDIAN_MAX_REQUESTS + 1)
    ]
    assert codes[:-1] == [404] * endpoints._GUARDIAN_MAX_REQUESTS and codes[-1] == 429
    endpoints._guardian_hits.clear()


async def test_adult_and_provider_switch(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    adult = (await client.post(CONSENTS, json=_grant(ADULT), headers=student.headers)).json()
    assert adult["is_valid"] and adult["guardian_token"] is None
    renew = await client.post(f"{CONSENTS}/me/guardian-link", headers=student.headers)
    assert renew.status_code == 409
    _settings(app, ai_provider="gemini")
    me = (await client.get(f"{CONSENTS}/me", headers=student.headers)).json()
    assert (me["provider"], me["is_valid"], me["consent"]) == ("GOOGLE_GEMINI", False, None)


async def test_transcript_is_minimized_before_sending_but_stored_as_is(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _sql(app, "UPDATE profiles SET real_name = '홍길순' WHERE id = :u", u=student.user_id)
    artwork = await client.post(f"{API}/artworks", json={"title": "정물"}, headers=student.headers)
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(client, app.state.audio_storage, student, artwork.json()["id"])
    base = _base(artwork.json()["id"], recorded.json()["id"])
    segments = [
        *SEGMENTS,
        {
            "start_ms": 16000,
            "end_ms": 19000,
            "text": "홍길순 학생 엄마 번호 010-1234-5678로 연락할게.",
        },
    ]
    body = {"device": "wasm", "model_name": "onnx-community/whisper-base", "segments": segments}
    await client.post(f"{base}/transcript/browser", json=body, headers=student.headers)
    await client.post(CONSENTS, json=_grant(ADULT), headers=student.headers)
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202

    llm = FakeLlm()
    assert await _runner(app, llm).run_once() is True
    sent = llm.prompts[0]
    assert "홍길순" not in sent and "010-1234-5678" not in sent
    assert "[학생]" in sent and "[전화번호]" in sent
    assert "[4]" in sent and "명암" in sent  # 구간 번호·첨삭 내용은 그대로
    # 원문 대본·요약 결과·근거 연결은 그대로
    transcript = (await client.get(f"{base}/transcript", headers=student.headers)).json()
    assert "홍길순" in transcript["segments"][4]["text"]
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["feedback_id"]
