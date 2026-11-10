"""v0.9 기능명세서 V2: 과제 수행·후속 분석(F-8), 커뮤니티 피드백 채택(F-6), 앱 내부 알림(F-9)."""

from __future__ import annotations

import httpx
from sqlalchemy import text

from app.worker.runner import JobRunner
from tests.db.conftest import Actor
from tests.db.test_community_api import _final_artwork, _post, _share
from tests.db.test_growth_api import _artwork, _seed_example, _seed_feedback
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt

API = "/api/v1"


async def _sql(app, sql: str, **params):  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return result.all() if result.returns_rows else []


async def _personal_recs(client: httpx.AsyncClient, student: Actor) -> list[dict]:
    created = await client.post(
        f"{API}/growth/me/recommendations", json={"scope": "PERSONAL"}, headers=student.headers
    )
    assert created.status_code == 201, created.text
    return created.json()["recommendations"]


async def _notifications(client: httpx.AsyncClient, user: Actor, **params) -> dict:  # type: ignore[no-untyped-def]
    response = await client.get(f"{API}/notifications", params=params, headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================================ F-8 과제 수행


async def test_personal_task_start_link_and_follow_up(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")  # 학원 없음
    seeds = await _seed_example(client, app, student)  # 4작품 모두 '비례' 지적
    recs = await _personal_recs(client, student)
    rec = recs[0]
    assert rec["weakness_category"] == "PROPORTION" and "비례" in rec["learning_goal"]
    assert rec["started_at"] is None and rec["linked_artwork_ids"] == []
    base = f"{API}/growth/me/recommendations/{rec['id']}"

    # 채택 전에는 시작·연결 불가
    early = await client.post(f"{base}/start", json={"version": 1}, headers=student.headers)
    assert early.json()["error"]["code"] == "RECOMMENDATION_INVALID_STATE"
    early_link = await client.post(
        f"{base}/artworks", json={"artwork_id": seeds[0].artwork_id}, headers=student.headers
    )
    assert early_link.json()["error"]["code"] == "RECOMMENDATION_INVALID_STATE"

    adopted = await client.post(f"{base}/adopt", json={"version": 1}, headers=student.headers)
    assert adopted.json()["status"] == "ADOPTED"
    started = await client.post(f"{base}/start", json={"version": 2}, headers=student.headers)
    assert started.status_code == 200 and started.json()["started_at"]
    assert started.json()["version"] == 3
    again = await client.post(f"{base}/start", json={"version": 3}, headers=student.headers)
    assert again.json()["version"] == 3  # 이미 시작 (멱등)

    follow = (await client.get(f"{base}/follow-up", headers=student.headers)).json()
    assert follow["status"] == "NO_LINKED_ARTWORK" and follow["completed"] is False

    # 새 작품을 과제 수행 작품으로 등록
    created = await client.post(
        f"{API}/artworks",
        json={"title": "비례 연습 1", "work_date": "2026-10-20", "recommendation_id": rec["id"]},
        headers=student.headers,
    )
    assert created.status_code == 201, created.text
    new_artwork = created.json()["id"]
    follow = (await client.get(f"{base}/follow-up", headers=student.headers)).json()
    assert follow["status"] == "NO_FOLLOW_UP_FEEDBACK"
    assert follow["linked_artworks"][0]["weakness_mentioned"] is None

    # 후속 강사 첨삭에서 '비례'가 언급되지 않음 → 향상으로 단정하지 않음
    await _seed_feedback(app, student, new_artwork, ["VALUE"])
    follow = (await client.get(f"{base}/follow-up", headers=student.headers)).json()
    assert follow["status"] == "NOT_MENTIONED" and follow["reappeared_count"] == 0
    assert any("단정" in n for n in follow["notes"])

    # 기존 작품 연결 (멱등) → 약점 재등장
    for _ in range(2):
        linked = await client.post(
            f"{base}/artworks", json={"artwork_id": seeds[3].artwork_id}, headers=student.headers
        )
        assert linked.status_code == 201, linked.text
    assert len(linked.json()) == 2
    follow = (await client.get(f"{base}/follow-up", headers=student.headers)).json()
    assert follow["status"] == "REAPPEARED" and follow["reappeared_count"] == 1
    assert follow["evidence"][0]["category"] == "PROPORTION"
    assert follow["evidence"][0]["artwork_id"] == seeds[3].artwork_id

    # 다른 사람 작품·남의 과제는 404
    other = await actors.signup("STUDENT")
    foreign = await _artwork(client, other, 5)
    blocked = await client.post(
        f"{base}/artworks", json={"artwork_id": foreign}, headers=student.headers
    )
    assert blocked.status_code == 404
    assert (await client.get(f"{base}/follow-up", headers=other.headers)).status_code == 404
    stolen = await client.post(
        f"{API}/artworks",
        json={"title": "남의 과제", "recommendation_id": rec["id"]},
        headers=other.headers,
    )
    assert stolen.status_code == 404
    assert (await client.get(f"{API}/artworks?limit=100", headers=other.headers)).json()[
        "total"
    ] == 1  # 실패한 작품 생성은 저장되지 않음

    # 완료하면서 수행 작품 연결 (완료 ≠ 향상)
    third = await _artwork(client, student, 25)
    done = await client.put(
        f"{base}/completion",
        json={"version": 3, "completed": True, "artwork_id": third},
        headers=student.headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "COMPLETED"
    assert set(done.json()["linked_artwork_ids"]) == {new_artwork, seeds[3].artwork_id, third}
    follow = (await client.get(f"{base}/follow-up", headers=student.headers)).json()
    assert follow["completed"] is True and follow["status"] == "REAPPEARED"

    # 연결 해제
    assert (
        await client.delete(f"{base}/artworks/{seeds[3].artwork_id}", headers=student.headers)
    ).status_code == 204
    assert (
        await client.delete(f"{base}/artworks/{seeds[3].artwork_id}", headers=student.headers)
    ).status_code == 404
    history = (await client.get(f"{base}/history", headers=student.headers)).json()
    actions = [h["action"] for h in history]
    assert actions[:3] == ["CREATED", "ADOPTED", "STARTED"]
    assert actions.count("ARTWORK_LINKED") == 3 and actions[-1] == "ARTWORK_UNLINKED"

    # 아카이브: 작품에서 연결된 과제 확인
    timeline = (
        await client.get(f"{API}/growth/me/timeline?limit=50", headers=student.headers)
    ).json()
    linked_item = next(i for i in timeline["items"] if i["artwork_id"] == new_artwork)
    assert linked_item["recommendations"][0]["id"] == rec["id"]

    # 작품을 지우면 연결도 사라진다
    deleted = await client.delete(f"{API}/artworks/{third}", headers=student.headers)
    assert deleted.status_code == 204
    remaining = (await client.get(f"{base}/artworks", headers=student.headers)).json()
    assert [a["artwork_id"] for a in remaining] == [new_artwork]


# ============================================================================ F-6 커뮤니티 피드백


async def test_community_question_feedback_comment_and_adoption(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    author = await actors.signup("STUDENT", name="작성자")
    reader = await actors.signup("STUDENT", name="댓글러")
    third = await actors.signup("STUDENT", name="구경꾼")
    artwork_id = await _final_artwork(client, app.state.storage, author)
    assert (await _share(client, author, artwork_id)).status_code in (200, 201)
    post = await _post(client, author, artwork_id, question="명암이 충분한지 봐 주세요")
    assert post["question"] == "명암이 충분한지 봐 주세요"
    comments = f"{API}/community/posts/{post['id']}/comments"

    bad = await client.post(
        comments, json={"body": "좋아요", "categories": ["VALUE"]}, headers=reader.headers
    )
    assert bad.status_code == 422  # 일반 의견에는 항목 지정 불가
    feedback = await client.post(
        comments,
        json={
            "body": "오른쪽 컵의 명암 대비가 약해 보여요. 어두운 면을 더 눌러 보세요.",
            "comment_type": "FEEDBACK",
            "categories": ["VALUE", "COMPOSITION"],
        },
        headers=reader.headers,
    )
    assert feedback.status_code == 201, feedback.text
    assert feedback.json()["categories"] == ["VALUE", "COMPOSITION"]
    general = await client.post(comments, json={"body": "멋져요"}, headers=reader.headers)
    assert general.json()["comment_type"] == "GENERAL"
    own = await client.post(
        comments,
        json={"body": "제 생각엔 구도가 아쉬워요", "comment_type": "FEEDBACK"},
        headers=author.headers,
    )
    fid, gid, oid = feedback.json()["id"], general.json()["id"], own.json()["id"]

    # 채택 전: 성장 분석에 반영되지 않음 (피드백 기록도 없음)
    notes = f"{API}/artworks/{artwork_id}/feedback-notes"
    assert (await client.get(notes, headers=author.headers)).json() == []
    listed = (await client.get(comments, headers=author.headers)).json()["items"]
    flags = {c["id"]: c["adopted"] for c in listed}
    assert flags[fid] is False and flags[gid] is None

    adopt = f"{API}/community/comments/{{}}/adopt"
    assert (await client.post(adopt.format(fid), headers=reader.headers)).status_code == 403
    assert (await client.post(adopt.format(fid), headers=third.headers)).status_code == 403
    not_feedback = await client.post(adopt.format(gid), headers=author.headers)
    assert not_feedback.json()["error"]["code"] == "COMMENT_NOT_FEEDBACK"
    assert (await client.post(adopt.format(oid), headers=author.headers)).status_code == 422
    adopted = await client.post(adopt.format(fid), headers=author.headers)
    assert adopted.status_code == 201, adopted.text
    note = adopted.json()
    assert (note["source"], note["community_comment_id"]) == ("PEER", fid)
    assert note["body"].startswith("오른쪽 컵의 명암") and note["review_mode"] == "SELF"
    twice = await client.post(adopt.format(fid), headers=author.headers)
    assert twice.json()["error"]["code"] == "COMMENT_ALREADY_ADOPTED"
    assert {
        c["adopted"]
        for c in (await client.get(comments, headers=reader.headers)).json()["items"]
        if c["id"] == fid
    } == {True}
    assert {
        c["adopted"] for c in (await client.get(comments, headers=third.headers)).json()["items"]
    } == {None}

    # 댓글·게시물이 지워져도 학생이 채택한 기록(사본)은 남는다
    assert (
        await client.delete(f"{API}/community/comments/{fid}", headers=reader.headers)
    ).status_code == 204
    assert (
        await client.delete(f"{API}/community/posts/{post['id']}", headers=author.headers)
    ).status_code == 204
    kept = await client.get(f"{API}/feedback-notes/{note['id']}", headers=author.headers)
    assert kept.status_code == 200 and kept.json()["source"] == "PEER"
    # 실기 유형별 피드는 그대로 (기존 필터)
    feed = await client.get(
        f"{API}/community/posts?practical_type=BASIC_DESIGN", headers=third.headers
    )
    assert feed.status_code == 200


# ============================================================================ F-9 알림


async def test_notifications_created_deduped_and_private(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _seed_example(client, app, student)
    recs = await _personal_recs(client, student)
    report_body = {"period": "ALL", "scope": "ALL"}
    report = await client.post(
        f"{API}/growth/me/reports", json=report_body, headers=student.headers
    )
    assert report.status_code == 201
    same = await client.post(f"{API}/growth/me/reports", json=report_body, headers=student.headers)
    assert same.status_code == 200  # 같은 데이터 → 기존 리포트, 알림 중복 없음

    page = await _notifications(client, student)
    types = sorted(n["type"] for n in page["items"])
    assert types == ["REPORT_READY", "TASK_RECOMMENDED"]
    assert page["unread_count"] == 2
    by_type = {n["type"]: n for n in page["items"]}
    assert by_type["REPORT_READY"]["report_id"] == report.json()["id"]
    assert by_type["TASK_RECOMMENDED"]["recommendation_id"] == recs[0]["id"]

    # 미완료 과제 안내: 채택 후 기준 일수가 지나면 주 1회 (중복 없음)
    base = f"{API}/growth/me/recommendations/{recs[0]['id']}"
    await client.post(f"{base}/adopt", json={"version": 1}, headers=student.headers)
    assert all(
        n["type"] != "TASK_REMINDER" for n in (await _notifications(client, student))["items"]
    )
    await _sql(
        app,
        "UPDATE practice_recommendations SET approved_at = now() - interval '5 days' WHERE id = :r",
        r=recs[0]["id"],
    )
    for _ in range(2):
        page = await _notifications(client, student)
    reminders = [n for n in page["items"] if n["type"] == "TASK_REMINDER"]
    assert len(reminders) == 1 and reminders[0]["recommendation_id"] == recs[0]["id"]

    # 학습 목표 확인 안내: 가입 후 7일이 지나고 목표가 없으면 월 1회
    await _sql(
        app,
        "UPDATE profiles SET created_at = now() - interval '10 days' WHERE id = :u",
        u=str(student.user_id),
    )
    for _ in range(2):
        page = await _notifications(client, student)
    assert [n["type"] for n in page["items"]].count("GOAL_CHECK") == 1
    await client.patch(
        f"{API}/users/me", json={"learning_goal": "비례 정확도 높이기"}, headers=student.headers
    )

    # 읽음·전체 읽음·숨김
    first = page["items"][0]
    read = await client.post(f"{API}/notifications/{first['id']}/read", headers=student.headers)
    assert read.json()["is_read"] is True
    assert (await _notifications(client, student))["unread_count"] == len(page["items"]) - 1
    unread_only = await _notifications(client, student, unread_only="true")
    assert first["id"] not in {n["id"] for n in unread_only["items"]}
    assert (await client.post(f"{API}/notifications/read-all", headers=student.headers)).json()[
        "updated"
    ] == len(page["items"]) - 1
    assert (
        await client.delete(f"{API}/notifications/{first['id']}", headers=student.headers)
    ).status_code == 204
    after = await _notifications(client, student)
    assert first["id"] not in {n["id"] for n in after["items"]} and after["unread_count"] == 0
    # 숨긴 알림의 이벤트는 다시 만들어지지 않는다
    assert len(after["items"]) == len(page["items"]) - 1

    # 다른 사용자는 남의 알림에 접근 불가
    other = await actors.signup("STUDENT")
    assert (await _notifications(client, other))["total"] == 0
    target = after["items"][0]["id"]
    assert (
        await client.post(f"{API}/notifications/{target}/read", headers=other.headers)
    ).status_code == 404
    assert (
        await client.delete(f"{API}/notifications/{target}", headers=other.headers)
    ).status_code == 404

    # 설정: 끈 유형은 만들지 않음
    prefs = await client.patch(
        f"{API}/notifications/preferences", json={"report_ready": False}, headers=student.headers
    )
    assert prefs.json()["report_ready"] is False and prefs.json()["reminder_after_days"] == 3
    assert (
        await client.patch(
            f"{API}/notifications/preferences",
            json={"reminder_after_days": 0},
            headers=student.headers,
        )
    ).status_code == 422
    extra = await _artwork(client, student, 28, practical_type="DRAWING")
    await _seed_feedback(app, student, extra, ["PROPORTION"])
    new_report = await client.post(
        f"{API}/growth/me/reports", json=report_body, headers=student.headers
    )
    assert new_report.status_code == 201
    final = await _notifications(client, student)
    assert [n["type"] for n in final["items"]].count("REPORT_READY") == 1


async def test_worker_maintenance_sweeps(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    """Worker 정기 작업: 보관 기간 지난 음성 표시 + 미완료 과제 알림 (사용자 요청 없이)."""
    student = await actors.signup("STUDENT")
    seeds = await _seed_example(client, app, student)
    recs = await _personal_recs(client, student)
    await client.post(
        f"{API}/growth/me/recommendations/{recs[0]['id']}/adopt",
        json={"version": 1},
        headers=student.headers,
    )
    await _sql(
        app,
        "UPDATE practice_recommendations SET approved_at = now() - interval '4 days' WHERE id = :r",
        r=recs[0]["id"],
    )
    await _sql(
        app,
        "UPDATE feedback_recordings SET uploaded_at = now() - interval '200 days' WHERE id = :r",
        r=seeds[0].recording_id,
    )
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=FakeStt(),
        llm=FakeLlm(),
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="w-maint",
    )
    first = await runner.maintenance()
    assert first["expired_audio"] == 1 and first["notifications"] >= 1
    second = await runner.maintenance()
    assert second == {"expired_audio": 0, "notifications": 0}
    rows = await _sql(
        app,
        "SELECT audio_deleted_at IS NOT NULL, storage_cleanup_pending FROM feedback_recordings"
        " WHERE id = :r",
        r=seeds[0].recording_id,
    )
    assert rows[0] == (True, True)
    # 첨삭은 그대로 성장 분석에 남는다
    weak = (await client.get(f"{API}/growth/me/weaknesses", headers=student.headers)).json()
    assert weak["totals"]["analyzed_artwork_count"] == 4
