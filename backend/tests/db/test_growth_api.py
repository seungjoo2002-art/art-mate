"""v0.7 성장 코치: 통합 이력, 반복 약점, 리포트, 맞춤 과제(규칙·AI), 강사 검토·배포, 권한, 동의.

첨삭 데이터는 v0.6 파이프라인 대신 SQL로 직접 넣는다 (승인·초안 상태를 정확히 만들기 위해).
Gemini는 FakeLlm, Worker는 테스트에서 직접 실행한다.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import text

from app.integrations.ai.gemini import LlmError
from app.worker.runner import JobRunner
from tests.db.conftest import Actor, World
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt

API = "/api/v1"
GROWTH_VERSION = "2026-12-growth-v2"


@dataclass
class Seed:
    artwork_id: str
    recording_id: str
    feedback_id: str
    item_ids: dict[str, str]


async def _exec(app, sql: str, **params):  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return result.all() if result.returns_rows else []


async def _artwork(client: httpx.AsyncClient, owner: Actor, day: int, **body) -> str:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks",
        json={"title": f"작품 {day}", "work_date": f"2026-10-{day:02d}"} | body,
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _seed_feedback(  # type: ignore[no-untyped-def]
    app,
    owner: Actor,
    artwork_id: str,
    categories: list[str],
    *,
    status: str = "APPROVED",
    strengths: tuple[str, ...] = ("COMPOSITION",),
) -> Seed:
    uid = str(owner.user_id)
    consent = await _exec(
        app,
        "SELECT id FROM recording_consents WHERE user_id = :u AND revoked_at IS NULL",
        u=uid,
    )
    if consent:
        consent_id = str(consent[0][0])
    else:
        consent_id = str(uuid.uuid4())
        await _exec(
            app,
            "INSERT INTO recording_consents (id, user_id, consent_type, policy_version, granted_by,"
            " granted_at) VALUES (:id, :u, 'VOICE_RECORDING', '2026-11-v1', 'SELF', now())",
            id=consent_id,
            u=uid,
        )
    rec, transcript, summary = (str(uuid.uuid4()) for _ in range(3))
    await _exec(
        app,
        "INSERT INTO feedback_recordings (id, artwork_id, owner_id, consent_id,"
        " speaker_notice_confirmed, status, storage_path, content_type, size_bytes, duration_ms,"
        " sha256, upload_expires_at, uploaded_at, transcription_status) VALUES (:id, :a, :u, :c,"
        " true, 'ACTIVE', :p, 'audio/webm', 100, 1000, :sha, now(), now(), 'COMPLETED')",
        id=rec,
        a=artwork_id,
        u=uid,
        c=consent_id,
        p=f"{uid}/{artwork_id}/{rec}.webm",
        sha=rec.replace("-", "")[:64].ljust(64, "0"),
    )
    segments = [
        {"index": 0, "start_ms": 0, "end_ms": 900, "text": "첨삭"},
        {"index": 1, "start_ms": 1500, "end_ms": 3000, "text": "첨삭2"},
    ]
    await _exec(
        app,
        "INSERT INTO feedback_transcripts (id, recording_id, artwork_id, owner_id, language, text,"
        " segments, segment_count, engine, model_name) VALUES (:id, :r, :a, :u, 'ko', '첨삭',"
        " CAST(:s AS jsonb), 2, 'fake', 'small')",
        id=transcript,
        r=rec,
        a=artwork_id,
        u=uid,
        s=json.dumps(segments, ensure_ascii=False),
    )
    await _exec(
        app,
        "INSERT INTO feedback_summaries (id, recording_id, artwork_id, owner_id, transcript_id,"
        " status, review_mode, summary, ai_output, model_name, prompt_version, approved_at)"
        " VALUES (:id, :r, :a, :u, :t, CAST(:st AS varchar), 'SELF', :sm, '{}'::jsonb, 'm', 'p',"
        " CASE WHEN CAST(:st AS varchar) = 'APPROVED' THEN now() END)",
        id=summary,
        r=rec,
        a=artwork_id,
        u=uid,
        t=transcript,
        st=status,
        sm=f"요약: {', '.join(categories)}",
    )
    item_ids: dict[str, str] = {}
    position = 0
    for kind, cats in (("WEAKNESS", categories), ("FIX", categories[:1]), ("STRENGTH", strengths)):
        for category in cats:
            item_id = str(uuid.uuid4())
            item_ids[f"{kind}:{category}"] = item_id
            await _exec(
                app,
                "INSERT INTO feedback_items (id, summary_id, kind, position, content, category,"
                " evidence_segment_ids, origin) VALUES (:id, :s, :k, :p, :c, :cat, '{1}', 'AI')",
                id=item_id,
                s=summary,
                k=kind,
                p=position,
                c=f"{kind} {category} 문장",
                cat=category,
            )
            position += 1
    for category in categories:
        await _exec(
            app,
            "INSERT INTO feedback_categories (id, summary_id, category, origin)"
            " VALUES (:id, :s, :c, 'AI')",
            id=str(uuid.uuid4()),
            s=summary,
            c=category,
        )
    return Seed(artwork_id, rec, summary, item_ids)


SPEC_EXAMPLE = [
    ["PROPORTION", "VALUE"],
    ["PROPORTION", "COMPOSITION"],
    ["PROPORTION", "VALUE"],
    ["COLOR", "PROPORTION"],
]


async def _seed_example(client, app, owner: Actor, **artwork) -> list[Seed]:  # type: ignore[no-untyped-def]
    seeds = []
    for day, cats in enumerate(SPEC_EXAMPLE, start=1):
        artwork_id = await _artwork(
            client, owner, day, practical_type="DRAWING", work_category="MOCK_EXAM", **artwork
        )
        seeds.append(await _seed_feedback(app, owner, artwork_id, cats))
    return seeds


async def _growth_consent(client: httpx.AsyncClient, student: Actor) -> None:
    granted = await client.post(
        f"{API}/ai-processing-consents",
        json={
            "purpose": "GROWTH_COACHING",
            "policy_version": GROWTH_VERSION,
            "agreed": True,
            "birth_year_month": "2000-01",
        },
        headers=student.headers,
    )
    assert granted.status_code == 201, granted.text


@pytest.fixture
def worker(app, client):  # type: ignore[no-untyped-def]
    llm = FakeLlm()
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=FakeStt(),
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="growth-worker",
    )
    return runner, llm


async def _drain(runner: JobRunner) -> int:
    count = 0
    while count < 10 and await runner.run_once():
        count += 1
    return count


def _narrative_json(**overrides) -> str:  # type: ignore[no-untyped-def]
    return json.dumps(
        {
            "overview": "최근 첨삭에서 비례가 반복적으로 언급되었다.",
            "strengths_comment": "구도는 강사가 긍정적으로 언급했다.",
            "improvement_comment": "기준선을 먼저 잡으라는 지적이 이어졌다.",
            "next_goals": [{"goal": "스케치 단계에서 기준선 먼저 긋기", "evidence": [1]}],
        }
        | overrides,
        ensure_ascii=False,
    )


def _recs_json() -> str:
    return json.dumps(
        {
            "recommendations": [
                {
                    "category": "PROPORTION",
                    "title": "정물 2개 비율 비교 스케치",
                    "description": "기준 길이를 정하고 두 정물의 비율을 비교한다.",
                    "steps": ["기준선을 긋는다", "가로·세로 비율을 비교한다", "형태를 구성한다"],
                    "estimated_minutes": 40,
                    "difficulty": "EASY",
                    "reason": "비례 지적이 여러 작품에서 반복되었다.",
                    "evidence": [1],
                }
            ]
        },
        ensure_ascii=False,
    )


# ============================================================================ 통합 이력·반복 약점


async def test_weakness_analysis_dedupes_and_excludes_unapproved(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    seeds = await _seed_example(client, app, student)
    # 같은 작품에 '비례' 첨삭이 하나 더 (작품 수는 그대로, 첨삭 횟수만 증가)
    await _seed_feedback(app, student, seeds[0].artwork_id, ["PROPORTION"])
    # 미승인 첨삭(형태)은 제외
    await _seed_feedback(app, student, seeds[1].artwork_id, ["FORM"], status="IN_REVIEW")
    # 삭제된 작품의 승인 첨삭(형태·형태)은 제외
    deleted = await _artwork(client, student, 20)
    await _seed_feedback(app, student, deleted, ["FORM"])
    other = await _artwork(client, student, 21)
    await _seed_feedback(app, student, other, ["FORM"])
    assert (
        await client.delete(f"{API}/artworks/{deleted}", headers=student.headers)
    ).status_code == 204

    body = (
        await client.get(f"{API}/growth/me/weaknesses?recent_window=2", headers=student.headers)
    ).json()
    assert body["status"] == "READY" and body["confidence"] == "MEDIUM"
    assert body["top_weaknesses"] == ["PROPORTION", "VALUE"]
    stats = {w["category"]: w for w in body["weaknesses"]}
    assert (stats["PROPORTION"]["artwork_count"], stats["PROPORTION"]["mention_count"]) == (4, 5)
    assert stats["FORM"]["artwork_count"] == 1  # 삭제 작품·초안 첨삭 제외
    assert stats["PROPORTION"]["recent"]["analyzed_artwork_count"] == 2
    evidence = stats["PROPORTION"]["evidence"][0]
    assert evidence["content"].startswith("WEAKNESS PROPORTION") and evidence["start_ms"] == 1500
    assert body["totals"]["analyzed_artwork_count"] == 5
    assert "AI가 실기 능력을 채점한 결과가 아닙니다" in " ".join(body["notes"])
    assert body["next_goals"][0]["based_on"]["kind"] == "FIX"

    # 필터: 실기 유형·기간·작업 목적
    filtered = (
        await client.get(
            f"{API}/growth/me/weaknesses?practical_type=DRAWING&from=2026-10-02&to=2026-10-04",
            headers=student.headers,
        )
    ).json()
    assert filtered["totals"]["analyzed_artwork_count"] == 3
    assert filtered["period_start"] == "2026-10-02"
    none = (
        await client.get(
            f"{API}/growth/me/weaknesses?work_category=PERSONAL_PRACTICE", headers=student.headers
        )
    ).json()
    assert none["status"] == "INSUFFICIENT_DATA" and none["message"]
    bad = await client.get(
        f"{API}/growth/me/weaknesses?from=2026-10-05&to=2026-10-01", headers=student.headers
    )
    assert bad.status_code == 422

    # 통합 이력: 승인된 첨삭만, 최근 작업일순, 페이지네이션
    timeline = (
        await client.get(f"{API}/growth/me/timeline?limit=2", headers=student.headers)
    ).json()
    assert timeline["total"] == 5 and len(timeline["items"]) == 2
    first_page = [i["title"] for i in timeline["items"]]
    assert first_page == ["작품 21", "작품 4"]
    page = (await client.get(f"{API}/growth/me/timeline?limit=10", headers=student.headers)).json()
    second = next(i for i in page["items"] if i["artwork_id"] == seeds[1].artwork_id)
    assert [f["categories"] for f in second["feedbacks"]] == [["COMPOSITION", "PROPORTION"]]
    assert second["stages"][0]["stage"] == "SKETCH" and second["work_category"] == "MOCK_EXAM"

    summary = (await client.get(f"{API}/growth/me/summary", headers=student.headers)).json()
    assert [w["category"] for w in summary["top_weaknesses"]] == ["PROPORTION", "VALUE"]
    assert len(summary["recent_feedbacks"]) == 5 and summary["latest_report"] is None


async def test_insufficient_data(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    for day in (1, 2):
        await _seed_feedback(app, student, await _artwork(client, student, day), ["VALUE"])
    report = await client.post(
        f"{API}/growth/me/reports", json={"period": "ALL"}, headers=student.headers
    )
    assert report.status_code == 201
    assert report.json()["status"] == "INSUFFICIENT_DATA"
    assert report.json()["message"] == "분석에 필요한 기록이 부족합니다."
    recs = await client.post(f"{API}/growth/me/recommendations", json={}, headers=student.headers)
    assert (recs.status_code, recs.json()["error"]["code"]) == (409, "INSUFFICIENT_DATA")
    assert recs.json()["error"]["details"]["reason"] == "NOT_ENOUGH_ARTWORKS"
    # 3개지만 반복 약점이 없음
    await _seed_feedback(app, student, await _artwork(client, student, 3), ["COLOR"])
    await _exec(
        app,
        "DELETE FROM feedback_categories WHERE category = 'VALUE' AND summary_id IN"
        " (SELECT id FROM feedback_summaries ORDER BY created_at LIMIT 1)",
    )
    recs = await client.post(f"{API}/growth/me/recommendations", json={}, headers=student.headers)
    assert recs.json()["error"]["details"]["reason"] == "NO_REPEATED_WEAKNESS"


# ============================================================================ 성장 리포트


async def test_report_dedupe_stale_regenerate_and_ai_narrative(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, worker
) -> None:
    runner, llm = worker
    student = await actors.signup("STUDENT")
    seeds = await _seed_example(client, app, student)
    body = {"period": "CUSTOM", "from": "2026-10-01", "to": "2026-10-31"}
    first = await client.post(f"{API}/growth/me/reports", json=body, headers=student.headers)
    assert first.status_code == 201, first.text
    report = first.json()
    assert report["status"] == "READY" and report["is_stale"] is False
    assert report["statistics"]["top_weaknesses"] == ["PROPORTION", "VALUE"]
    assert report["ai_narrative"]["status"] == "NOT_REQUESTED"
    assert report["source_feedback_count"] == 4
    again = await client.post(f"{API}/growth/me/reports", json=body, headers=student.headers)
    assert again.status_code == 200 and again.json()["id"] == report["id"]

    # AI 설명문: 첨삭 요약 동의(FEEDBACK_SUMMARY)로는 안 된다 → SKIPPED
    await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": "2026-12-ai-v2", "agreed": True, "birth_year_month": "2000-01"},
        headers=student.headers,
    )
    skipped = await client.post(
        f"{API}/growth/me/reports",
        json=body | {"include_ai_narrative": True},
        headers=student.headers,
    )
    narrative = skipped.json()["ai_narrative"]
    assert (narrative["status"], narrative["error_code"]) == ("SKIPPED", "AI_CONSENT_REQUIRED")

    await _growth_consent(client, student)
    pending = await client.post(
        f"{API}/growth/me/reports/{report['id']}/regenerate",
        json={"include_ai_narrative": True},
        headers=student.headers,
    )
    assert pending.status_code == 200 and pending.json()["id"] == report["id"]
    assert pending.json()["ai_narrative"]["status"] == "PENDING"
    llm.outcomes.append(_narrative_json())
    assert await _drain(runner) == 1
    ready = (
        await client.get(f"{API}/growth/me/reports/{report['id']}", headers=student.headers)
    ).json()
    assert ready["ai_narrative"]["status"] == "READY"
    assert ready["ai_narrative"]["model_name"] == "gemini-3.1-flash-lite"
    assert ready["ai_narrative"]["prompt_version"] == "growth-narrative-v1"
    goal = ready["ai_narrative"]["content"]["next_goals"][0]
    assert goal["evidence"][0]["kind"] in ("WEAKNESS", "FIX")
    # 외부 전송 최소화: 작품 제목·사용자 ID 미포함
    assert "작품 1" not in llm.prompts[-1] and student.user_id.hex not in llm.prompts[-1]

    # 데이터 변경 → stale → 재생성하면 새 리포트
    extra = await _artwork(client, student, 10)
    await _seed_feedback(app, student, extra, ["PROPORTION"])
    stale = (
        await client.get(f"{API}/growth/me/reports/{report['id']}", headers=student.headers)
    ).json()
    assert stale["is_stale"] is True
    regenerated = await client.post(
        f"{API}/growth/me/reports/{report['id']}/regenerate", json={}, headers=student.headers
    )
    assert regenerated.status_code == 201 and regenerated.json()["id"] != report["id"]
    listing = (await client.get(f"{API}/growth/me/reports", headers=student.headers)).json()
    assert listing["total"] == 2 and listing["items"][0]["id"] == regenerated.json()["id"]

    # 근거 첨삭(녹음) 삭제 → 설명문 무효화, 근거 문장도 빠짐
    deleted = await client.delete(
        f"{API}/artworks/{seeds[0].artwork_id}/recordings/{seeds[0].recording_id}",
        headers=student.headers,
    )
    assert deleted.status_code == 204
    invalid = (
        await client.get(f"{API}/growth/me/reports/{report['id']}", headers=student.headers)
    ).json()
    assert invalid["ai_narrative"]["status"] == "INVALIDATED"
    assert invalid["ai_narrative"]["content"] is None
    ids = {e["feedback_id"] for w in invalid["statistics"]["weaknesses"] for e in w["evidence"]}
    assert seeds[0].feedback_id not in ids


async def test_ai_narrative_with_forbidden_claims_fails(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, worker
) -> None:
    runner, llm = worker
    student = await actors.signup("STUDENT")
    await _seed_example(client, app, student)
    await _growth_consent(client, student)
    report = (
        await client.post(
            f"{API}/growth/me/reports",
            json={"period": "ALL", "include_ai_narrative": True},
            headers=student.headers,
        )
    ).json()
    llm.outcomes.extend(
        [
            _narrative_json(overview="실력이 30% 향상되었다."),
            LlmError("LLM_RATE_LIMITED", "429", retryable=True),
            _narrative_json(improvement_comment="이대로면 합격 가능성이 높다."),
        ]
    )
    for _ in range(3):
        await _exec(app, "UPDATE ai_processing_jobs SET run_after = now()")
        await runner.run_once()
    body = (
        await client.get(f"{API}/growth/me/reports/{report['id']}", headers=student.headers)
    ).json()
    assert body["ai_narrative"]["status"] == "FAILED"
    assert body["ai_narrative"]["error_code"] == "LLM_INVALID_OUTPUT"
    usage = await _exec(app, "SELECT attempts, api_call_count FROM ai_processing_jobs")
    assert tuple(usage[0]) == (3, 3)
    # 통계는 그대로 볼 수 있다
    assert body["statistics"]["top_weaknesses"] == ["PROPORTION", "VALUE"]


# ============================================================================ 개인 추천 (본인 채택)


async def test_personal_recommendation_flow(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, app
) -> None:
    student = world.students[0]
    await _seed_example(client, app, student)  # 개인 작품 (학원 미연결)
    created = await client.post(
        f"{API}/growth/me/recommendations", json={"scope": "PERSONAL"}, headers=student.headers
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["status"] == "CREATED" and result["job"] is None
    recs = result["recommendations"]
    assert [r["weakness_category"] for r in recs] == ["PROPORTION", "VALUE"]
    rec = recs[0]
    assert (rec["source"], rec["status"], rec["review_mode"]) == ("RULE", "DRAFT", "SELF")
    assert rec["title"] == "기준선 비율 비교 스케치" and rec["method_steps"]
    assert rec["evidence"] and rec["evidence"][0]["category"] == "PROPORTION"
    assert rec["analysis"]["artwork_count"] == 4 and rec["practical_type"] == "DRAWING"
    assert rec["origin"]["template_version"] == "practice-template-v1"
    again = await client.post(
        f"{API}/growth/me/recommendations", json={"scope": "PERSONAL"}, headers=student.headers
    )
    assert again.status_code == 200 and again.json()["status"] == "EXISTING"

    # 강사에게 보이지 않음
    staff_list = (
        await client.get(f"{world.base}/growth/recommendations", headers=world.teacher.headers)
    ).json()
    assert staff_list["total"] == 0
    assert (
        await client.get(
            f"{world.base}/growth/recommendations/{rec['id']}", headers=world.teacher.headers
        )
    ).status_code == 404

    base = f"{API}/growth/me/recommendations/{rec['id']}"
    edited = await client.patch(
        base,
        json={
            "version": 1,
            "title": "비율 관찰 스케치",
            "estimated_minutes": 30,
            "difficulty": "NORMAL",
        },
        headers=student.headers,
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["status"], edited.json()["version"]) == ("IN_REVIEW", 2)
    assert edited.json()["origin"]["title"] == "기준선 비율 비교 스케치"  # 원본 보존
    conflict = await client.patch(base, json={"version": 1, "title": "x"}, headers=student.headers)
    assert conflict.json()["error"]["code"] == "RECOMMENDATION_VERSION_CONFLICT"
    early = await client.put(
        f"{base}/completion", json={"version": 2, "completed": True}, headers=student.headers
    )
    assert early.json()["error"]["code"] == "RECOMMENDATION_INVALID_STATE"
    adopted = await client.post(f"{base}/adopt", json={"version": 2}, headers=student.headers)
    assert adopted.json()["status"] == "ADOPTED"
    done = await client.put(
        f"{base}/completion", json={"version": 3, "completed": True}, headers=student.headers
    )
    assert done.json()["status"] == "COMPLETED" and done.json()["completed_at"]
    undone = await client.put(
        f"{base}/completion", json={"version": 4, "completed": False}, headers=student.headers
    )
    assert undone.json()["status"] == "ADOPTED" and undone.json()["completed_at"] is None
    history = (await client.get(f"{base}/history", headers=student.headers)).json()
    assert [h["action"] for h in history] == [
        "CREATED",
        "EDITED",
        "ADOPTED",
        "COMPLETED",
        "COMPLETED",
    ]
    assert history[1]["changes"]["before"]["title"] == "기준선 비율 비교 스케치"

    rejected = await client.post(
        f"{API}/growth/me/recommendations/{recs[1]['id']}/reject",
        json={"version": 1, "reason": "지금은 다른 연습 중"},
        headers=student.headers,
    )
    assert rejected.json()["status"] == "REJECTED"
    # 학원 범위 승인·배포 API는 학생이 쓸 수 없다 (경로 자체가 강사 전용)
    assert (
        await client.post(
            f"{world.base}/growth/recommendations/{rec['id']}/approve",
            json={"version": 1},
            headers=student.headers,
        )
    ).status_code == 403
    # 다른 학생은 볼 수 없다
    assert (await client.get(base, headers=world.students[1].headers)).status_code == 404


# ======================================================================= 학원 추천 (강사 검토·배포)


async def test_academy_recommendation_review_and_distribution(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, app, build_world
) -> None:
    student = world.students[0]
    await _seed_example(client, app, student, academy_id=world.academy_id)
    # 개인 작품(색채)은 강사 분석에 포함되지 않아야 한다
    for day in (11, 12):
        await _seed_feedback(app, student, await _artwork(client, student, day), ["COLOR"])
    staff = f"{world.base}/growth"
    weak = (
        await client.get(
            f"{staff}/students/{student.membership_id}/weaknesses", headers=world.teacher.headers
        )
    ).json()
    assert weak["totals"]["analyzed_artwork_count"] == 4
    assert weak["scope"]["scope"] == "ACADEMY"
    assert {w["category"] for w in weak["weaknesses"]} == {
        "PROPORTION",
        "VALUE",
        "COMPOSITION",
        "COLOR",
    }
    assert next(w for w in weak["weaknesses"] if w["category"] == "COLOR")["artwork_count"] == 1
    # 학생 본인 전체 범위에서는 색채가 3개 작품
    mine = (await client.get(f"{API}/growth/me/weaknesses", headers=student.headers)).json()
    assert next(w for w in mine["weaknesses"] if w["category"] == "COLOR")["artwork_count"] == 3

    students = (await client.get(f"{staff}/students", headers=world.teacher.headers)).json()
    row = next(
        r for r in students["items"] if r["student"]["membership_id"] == student.membership_id
    )
    assert row["top_weaknesses"] == ["PROPORTION", "VALUE"] and row["analyzed_artwork_count"] == 4

    generated = await client.post(
        f"{staff}/students/{student.membership_id}/recommendations",
        json={},
        headers=world.teacher.headers,
    )
    assert generated.status_code == 201, generated.text
    rec = generated.json()["recommendations"][0]
    assert (rec["review_mode"], rec["status"]) == ("INSTRUCTOR", "DRAFT")
    assert rec["student"]["membership_id"] == student.membership_id

    # 학생: 배포 전 학원 추천은 보이지 않음
    assert (await client.get(f"{API}/growth/me/recommendations", headers=student.headers)).json()[
        "total"
    ] == 0
    assert (
        await client.get(f"{API}/growth/me/recommendations/{rec['id']}", headers=student.headers)
    ).status_code == 404

    queue = (await client.get(f"{staff}/recommendations", headers=world.teacher.headers)).json()
    assert queue["total"] == 2
    # 비담당 강사 403, 다른 학원 404
    assert (
        await client.get(
            f"{staff}/recommendations/{rec['id']}", headers=world.other_teacher.headers
        )
    ).status_code == 403
    assert (
        await client.get(f"{staff}/recommendations", headers=world.other_teacher.headers)
    ).json()["total"] == 0
    other = await build_world("다른 학원", admin=world.admin)
    assert (
        await client.get(
            f"{other.base}/growth/recommendations/{rec['id']}", headers=other.owner.headers
        )
    ).status_code == 404
    assert (
        await client.get(
            f"{other.base}/growth/students/{student.membership_id}/summary",
            headers=other.owner.headers,
        )
    ).status_code == 404

    base = f"{staff}/recommendations/{rec['id']}"
    edited = await client.patch(
        base,
        json={
            "version": 1,
            "method_steps": ["기준선 긋기", "비율 비교", "형태 구성"],
            "difficulty": "HARD",
        },
        headers=world.teacher.headers,
    )
    assert edited.json()["status"] == "IN_REVIEW"
    early = await client.post(
        f"{base}/distribute", json={"version": 2}, headers=world.teacher.headers
    )
    assert early.json()["error"]["code"] == "RECOMMENDATION_INVALID_STATE"
    approved = await client.post(
        f"{base}/approve", json={"version": 2}, headers=world.teacher.headers
    )
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_by_name"].endswith("담당강사")
    distributed = await client.post(
        f"{base}/distribute",
        json={"version": 3, "due_at": "2099-01-01T23:59:00+09:00"},
        headers=world.teacher.headers,
    )
    assert distributed.status_code == 200, distributed.text
    body = distributed.json()
    assert body["status"] == "DISTRIBUTED" and body["task"]["completed"] is False
    task_id = body["task"]["task_id"]

    # 기존 v0.3 과제 시스템으로 배포됨: 학생 '받은 과제'에 보이고 완료 체크 가능
    my_tasks = (await client.get(f"{world.base}/tasks/me", headers=student.headers)).json()
    task = next(t for t in my_tasks["items"] if t["task_id"] == task_id)
    assert task["title"] == rec["title"] and "연습 방법" in task["description"]
    assert (await client.get(f"{world.base}/tasks/me", headers=world.students[1].headers)).json()[
        "total"
    ] == 0
    completed = await client.put(
        f"{world.base}/tasks/{task_id}/completion",
        json={"completed": True},
        headers=student.headers,
    )
    assert completed.status_code == 200
    visible = (await client.get(f"{API}/growth/me/recommendations", headers=student.headers)).json()
    assert [r["status"] for r in visible["items"]] == ["DISTRIBUTED"]
    assert visible["items"][0]["task"]["completed"] is True
    assert "origin" not in visible["items"][0]  # 학원 추천: 학생은 원본·모델 정보를 보지 않음

    history = (await client.get(f"{base}/history", headers=world.teacher.headers)).json()
    assert [h["action"] for h in history] == ["CREATED", "EDITED", "APPROVED", "DISTRIBUTED"]
    assert (
        await client.get(
            f"{API}/growth/me/recommendations/{rec['id']}/history", headers=student.headers
        )
    ).status_code == 403

    # 반려
    second = generated.json()["recommendations"][1]
    rejected = await client.post(
        f"{staff}/recommendations/{second['id']}/reject",
        json={"version": 1, "reason": "이번 주는 명암 과제가 이미 있음"},
        headers=world.teacher.headers,
    )
    assert rejected.json()["status"] == "REJECTED"

    # 강사 리포트 (학원 범위)
    report = await client.post(
        f"{staff}/students/{student.membership_id}/reports",
        json={"period": "ALL"},
        headers=world.teacher.headers,
    )
    assert report.status_code == 201 and report.json()["scope"]["scope"] == "ACADEMY"
    assert report.json()["statistics"]["totals"]["analyzed_artwork_count"] == 4
    report_id = report.json()["id"]
    assert (
        await client.get(f"{staff}/reports/{report_id}", headers=world.teacher.headers)
    ).status_code == 200
    assert (
        await client.get(f"{staff}/reports/{report_id}", headers=world.other_teacher.headers)
    ).status_code == 403
    # 학생도 자기 학원 리포트를 볼 수 있다
    assert (
        await client.get(f"{API}/growth/me/reports/{report_id}", headers=student.headers)
    ).status_code == 200
    # 학생 개인(ALL) 리포트는 강사가 볼 수 없다
    personal = (
        await client.post(
            f"{API}/growth/me/reports", json={"period": "ALL"}, headers=student.headers
        )
    ).json()
    assert (
        await client.get(f"{staff}/reports/{personal['id']}", headers=world.teacher.headers)
    ).status_code == 404


async def test_distribution_class_selection(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, app
) -> None:
    student = world.students[0]
    await _seed_example(client, app, student, academy_id=world.academy_id)
    staff = f"{world.base}/growth"
    rec = (
        await client.post(
            f"{staff}/students/{student.membership_id}/recommendations",
            json={},
            headers=world.owner.headers,
        )
    ).json()["recommendations"][0]
    base = f"{staff}/recommendations/{rec['id']}"
    await client.post(f"{base}/approve", json={"version": 1}, headers=world.owner.headers)
    # 학생을 두 번째 반에도 배정 → 반을 지정해야 함
    created = await client.post(
        f"{world.base}/classes", json={"name": "B반"}, headers=world.owner.headers
    )
    class_b = created.json()["id"]
    await client.post(
        f"{world.base}/classes/{class_b}/members",
        json={"membership_id": student.membership_id},
        headers=world.owner.headers,
    )
    ambiguous = await client.post(
        f"{base}/distribute", json={"version": 2}, headers=world.owner.headers
    )
    assert (ambiguous.status_code, ambiguous.json()["error"]["code"]) == (422, "CLASS_REQUIRED")
    assert set(ambiguous.json()["error"]["details"]["class_ids"]) == {world.class_id, class_b}
    ok = await client.post(
        f"{base}/distribute", json={"version": 2, "class_id": class_b}, headers=world.owner.headers
    )
    assert ok.status_code == 200 and ok.json()["status"] == "DISTRIBUTED"


# ============================================================================ AI 추천 (Worker)


async def test_ai_recommendations_via_worker(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, worker
) -> None:
    runner, llm = worker
    student = await actors.signup("STUDENT")
    await _seed_example(client, app, student)
    body = {"scope": "PERSONAL", "use_ai": True}
    blocked = await client.post(
        f"{API}/growth/me/recommendations", json=body, headers=student.headers
    )
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (409, "AI_CONSENT_REQUIRED")
    assert blocked.json()["error"]["details"]["purpose"] == "GROWTH_COACHING"
    await _growth_consent(client, student)
    queued = await client.post(
        f"{API}/growth/me/recommendations", json=body, headers=student.headers
    )
    assert queued.status_code == 202 and queued.json()["status"] == "QUEUED"
    job = queued.json()["job"]
    dup = await client.post(f"{API}/growth/me/recommendations", json=body, headers=student.headers)
    assert dup.json()["job"]["id"] == job["id"]  # 중복 작업 방지

    llm.outcomes.extend([LlmError("LLM_UNAVAILABLE", "503", retryable=True), _recs_json()])
    await runner.run_once()
    status = (await client.get(f"{API}/growth/me/jobs/{job['id']}", headers=student.headers)).json()
    assert (status["status"], status["error_code"]) == ("QUEUED", "LLM_UNAVAILABLE")
    await _exec(app, "UPDATE ai_processing_jobs SET run_after = now()")
    await runner.run_once()
    status = (await client.get(f"{API}/growth/me/jobs/{job['id']}", headers=student.headers)).json()
    assert status["status"] == "SUCCEEDED"
    recs = (await client.get(f"{API}/growth/me/recommendations", headers=student.headers)).json()[
        "items"
    ]
    assert len(recs) == 1
    rec = recs[0]
    assert (rec["source"], rec["weakness_category"], rec["status"]) == ("AI", "PROPORTION", "DRAFT")
    assert rec["model_name"] == "gemini-3.1-flash-lite"
    assert rec["prompt_version"] == "practice-recommend-v1"
    assert rec["evidence"][0]["category"] == "PROPORTION"
    assert "작품 1" not in llm.prompts[-1]  # 작품 제목 미전송
    usage = await _exec(app, "SELECT api_call_count, input_tokens FROM ai_processing_jobs")
    assert tuple(usage[0]) == (2, 120)
    # 다시 요청하면 같은 데이터의 기존 AI 추천
    existing = await client.post(
        f"{API}/growth/me/recommendations", json=body, headers=student.headers
    )
    assert existing.json()["status"] == "EXISTING"


async def test_growth_consent_revocation_cancels_jobs(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, worker
) -> None:
    runner, llm = worker
    student = await actors.signup("STUDENT")
    await _seed_example(client, app, student)
    await _growth_consent(client, student)
    status = (
        await client.get(
            f"{API}/ai-processing-consents/me?purpose=GROWTH_COACHING", headers=student.headers
        )
    ).json()
    assert status["is_valid"] and status["purpose"] == "GROWTH_COACHING"
    # 첨삭 요약 동의 상태와는 별개
    assert not (
        await client.get(f"{API}/ai-processing-consents/me", headers=student.headers)
    ).json()["is_valid"]
    job = (
        await client.post(
            f"{API}/growth/me/recommendations",
            json={"scope": "PERSONAL", "use_ai": True},
            headers=student.headers,
        )
    ).json()["job"]
    report = (
        await client.post(
            f"{API}/growth/me/reports",
            json={"period": "ALL", "include_ai_narrative": True},
            headers=student.headers,
        )
    ).json()
    assert report["ai_narrative"]["status"] == "PENDING"
    revoked = await client.delete(
        f"{API}/ai-processing-consents/me?purpose=GROWTH_COACHING", headers=student.headers
    )
    assert revoked.status_code == 204
    cancelled = (
        await client.get(f"{API}/growth/me/jobs/{job['id']}", headers=student.headers)
    ).json()
    assert (cancelled["status"], cancelled["error_code"]) == ("CANCELLED", "AI_CONSENT_REVOKED")
    after = (
        await client.get(f"{API}/growth/me/reports/{report['id']}", headers=student.headers)
    ).json()
    assert after["ai_narrative"]["status"] == "SKIPPED"
    assert await _drain(runner) == 0 and llm.prompts == []
    # 규칙 기반 추천은 동의 없이 계속 가능 (외부 전송 없음)
    rule = await client.post(
        f"{API}/growth/me/recommendations", json={"scope": "PERSONAL"}, headers=student.headers
    )
    assert rule.status_code == 201


async def test_growth_ai_disabled(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await _seed_example(client, app, student)
    await _growth_consent(client, student)
    app.state.settings.growth_ai_enabled = False
    try:
        ai = await client.post(
            f"{API}/growth/me/recommendations",
            json={"scope": "PERSONAL", "use_ai": True},
            headers=student.headers,
        )
        report = await client.post(
            f"{API}/growth/me/reports",
            json={"period": "ALL", "include_ai_narrative": True},
            headers=student.headers,
        )
    finally:
        app.state.settings.growth_ai_enabled = True
    assert (ai.status_code, ai.json()["error"]["code"]) == (503, "GROWTH_AI_NOT_CONFIGURED")
    assert report.json()["ai_narrative"]["error_code"] == "GROWTH_AI_NOT_CONFIGURED"


async def test_concurrent_rule_generation_creates_one_batch(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _seed_example(client, app, student)
    responses = await asyncio.gather(
        *[
            client.post(
                f"{API}/growth/me/recommendations",
                json={"scope": "PERSONAL"},
                headers=student.headers,
            )
            for _ in range(4)
        ]
    )
    assert all(r.status_code in (200, 201) for r in responses), [r.text for r in responses]
    rows = await _exec(app, "SELECT count(*) FROM practice_recommendations")
    assert rows[0][0] == 2


async def test_new_data_supersedes_open_recommendations(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _seed_example(client, app, student)
    first = (
        await client.post(
            f"{API}/growth/me/recommendations", json={"scope": "PERSONAL"}, headers=student.headers
        )
    ).json()["recommendations"]
    await _seed_feedback(app, student, await _artwork(client, student, 15), ["VALUE"])
    second = await client.post(
        f"{API}/growth/me/recommendations", json={"scope": "PERSONAL"}, headers=student.headers
    )
    assert second.status_code == 201
    statuses = await _exec(
        app,
        "SELECT status FROM practice_recommendations WHERE id = ANY(CAST(:ids AS uuid[]))",
        ids=[r["id"] for r in first],
    )
    assert {s[0] for s in statuses} == {"SUPERSEDED"}
    visible = (await client.get(f"{API}/growth/me/recommendations", headers=student.headers)).json()
    assert visible["total"] == 2  # 대체된 추천은 목록에서 빠짐
