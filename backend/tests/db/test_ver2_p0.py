"""VER.2 P0: 사진 없는 글·카테고리, 작품 사진 선택 공유, 실기시험 단계별 시간."""

from __future__ import annotations

from datetime import timedelta

import asyncpg
import httpx
from sqlalchemy import text

from app.core import timezone as clock
from tests.db.test_artworks_api import _upload
from tests.db.test_community_api import _final_artwork, _share
from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic
from tests.fake_storage import image_bytes

API = "/api/v1"


async def _sql(app, sql: str, **params):  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return result.all() if result.returns_rows else []


async def _can_read(app, user, path: str) -> bool:  # type: ignore[no-untyped-def]
    rows = await _sql(
        app,
        "SELECT artmate_private.can_access_shared_image(:u, :n, 'read')",
        u=str(user.user_id),
        n=path,
    )
    return rows[0][0]


async def _post(client, author, **body) -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.post(
        f"{API}/community/posts", json={"title": "질문 있어요"} | body, headers=author.headers
    )


# ============================================================================ 사진 없는 글·카테고리


async def test_text_posts_categories_and_filter(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    author = await actors.signup("STUDENT", name="질문러")
    reader = await actors.signup("STUDENT", name="읽는이")

    # 정책 검증: 사진 없는 글은 본문 필수, 작품 공유 분류 불가, 사진 선택 불가
    for bad in (
        {"body": None},
        {"body": "   "},
        {"body": "내용", "category": "ARTWORK_SHARE"},
        {"body": "내용", "photo_id": "00000000-0000-0000-0000-000000000000"},
    ):
        assert (await _post(client, author, **bad)).status_code == 422, bad

    question = await _post(
        client,
        author,
        body="소묘 명암 단계는 몇 개로 나누나요?",
        category="PRACTICE_QUESTION",
        practical_type="DRAWING",
    )
    assert question.status_code == 201, question.text
    q = question.json()
    assert (q["category"], q["has_artwork"], q["image"], q["artwork_id"]) == (
        "PRACTICE_QUESTION",
        False,
        None,
        None,
    )
    free = await _post(
        client, author, title="잡담", body="오늘 실기 힘들었다", author_display="ANONYMOUS"
    )
    assert free.json()["category"] == "FREE"  # 기본값
    assert free.json()["author"]["is_me"] is True

    # 다른 학생에게 보임, 익명 글은 이름 숨김
    feed = (await client.get(f"{API}/community/posts", headers=reader.headers)).json()
    by_id = {p["id"]: p for p in feed["items"]}
    assert set(by_id) == {q["id"], free.json()["id"]}
    assert by_id[q["id"]]["author"]["display_name"] == "질문러"
    assert by_id[free.json()["id"]]["author"] == {
        "display_name": "익명 학생",
        "is_anonymous": True,
        "is_me": False,
    }
    only_q = (
        await client.get(
            f"{API}/community/posts?category=PRACTICE_QUESTION", headers=reader.headers
        )
    ).json()
    assert [p["id"] for p in only_q["items"]] == [q["id"]]
    two = (
        await client.get(
            f"{API}/community/posts?category=FREE&category=PRACTICE_QUESTION",
            headers=reader.headers,
        )
    ).json()
    assert two["total"] == 2
    bad_filter = await client.get(f"{API}/community/posts?category=NOPE", headers=reader.headers)
    assert bad_filter.status_code == 422

    # 기존 기능: 좋아요·댓글·신고·수정·삭제
    post_url = f"{API}/community/posts/{q['id']}"
    assert (await client.put(f"{post_url}/like", headers=reader.headers)).json()["like_count"] == 1
    comment = await client.post(
        f"{post_url}/comments", json={"body": "보통 5단계요"}, headers=reader.headers
    )
    assert comment.status_code == 201
    report = await client.post(
        f"{post_url}/reports", json={"reason": "SPAM"}, headers=reader.headers
    )
    assert report.status_code == 201
    edited = await client.patch(
        post_url, json={"category": "FEEDBACK_REQUEST"}, headers=author.headers
    )
    assert edited.json()["category"] == "FEEDBACK_REQUEST"
    for bad in ({"category": "ARTWORK_SHARE"}, {"body": None}, {"photo_id": None}):
        assert (await client.patch(post_url, json=bad, headers=author.headers)).status_code == 422
    assert (
        await client.patch(post_url, json={"title": "x"}, headers=reader.headers)
    ).status_code == 403
    assert (await client.delete(post_url, headers=author.headers)).status_code == 204
    assert (await client.get(post_url, headers=reader.headers)).status_code == 404


async def test_artwork_posts_keep_legacy_behaviour(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    author = await actors.signup("STUDENT")
    photos = app.state.storage
    plain = await _final_artwork(client, photos, author, "완성작")
    asking = await _final_artwork(client, photos, author, "질문작")
    for artwork in (plain, asking):
        assert (await _share(client, author, artwork)).status_code == 200
    # 기존 요청 그대로 (category 없음): question 유무로 분류
    share = await _post(client, author, artwork_id=plain)
    feedback = await _post(client, author, artwork_id=asking, question="명암이 괜찮나요?")
    assert share.json()["category"] == "ARTWORK_SHARE" and share.json()["image"]
    assert feedback.json()["category"] == "FEEDBACK_REQUEST"
    again = await _post(client, author, artwork_id=plain)
    assert again.json()["error"]["code"] == "POST_ALREADY_EXISTS"
    no_consent = await _final_artwork(client, photos, author, "비공개작")
    denied = await _post(client, author, artwork_id=no_consent)
    assert denied.json()["error"]["code"] == "SHARING_CONSENT_REQUIRED"
    # 작품 게시물의 작성자 표시는 공유 동의를 따른다
    wrong = await _post(client, author, artwork_id=no_consent, author_display="ANONYMOUS")
    assert wrong.status_code == 422


# ============================================================================ 사진 선택 공유


async def test_share_selected_photo(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    author = await actors.signup("STUDENT")
    reader = await actors.signup("STUDENT")
    photos = app.state.storage
    created = await client.post(
        f"{API}/artworks",
        json={"title": "과정 공유", "practical_type": "DRAWING"},
        headers=author.headers,
    )
    artwork = created.json()["id"]
    sketch = (await _upload(client, photos, author, artwork, "SKETCH")).json()
    # 완성 사진이 없어도 커뮤니티 동의 가능 (VER.2), 참고작 동의는 완성 사진 필요
    assert (await _share(client, author, artwork)).status_code == 200
    reference = await _share(client, author, artwork, purpose="REFERENCE")
    assert reference.json()["error"]["code"] == "FINAL_PHOTO_REQUIRED"
    # 완성 사진이 없으면 사진을 골라야 한다
    missing = await _post(client, author, artwork_id=artwork)
    assert missing.json()["error"]["code"] == "PHOTO_SELECTION_REQUIRED"
    # 다른 작품·다른 사람의 사진은 고를 수 없다
    other_art = await _final_artwork(client, photos, reader, "남의 작품")
    other_photo = (await client.get(f"{API}/artworks/{other_art}", headers=reader.headers)).json()[
        "photos"
    ][0]["id"]
    stolen = await _post(client, author, artwork_id=artwork, photo_id=other_photo)
    assert stolen.status_code == 404

    posted = await _post(client, author, artwork_id=artwork, photo_id=sketch["id"])
    assert posted.status_code == 201, posted.text
    post = posted.json()
    assert post["photo_id"] == sketch["id"] and post["image"]["url"]
    image = await _sql(
        app,
        "SELECT kind, storage_path, source_photo_id FROM shared_artwork_images"
        " WHERE artwork_id = :a AND status = 'ACTIVE'",
        a=artwork,
    )
    assert [(r[0], str(r[2])) for r in image] == [("POST", sketch["id"])]
    path = image[0][1]
    assert str(author.user_id) not in path and artwork not in path  # 경로로 작성자 식별 불가
    assert await _can_read(app, reader, path)
    other_view = (
        await client.get(f"{API}/community/posts/{post['id']}", headers=reader.headers)
    ).json()
    assert other_view["photo_id"] is None and other_view["artwork_id"] is None  # 본인만

    # 완성 사진 추가 → 사진 변경: 대표 이미지를 쓰고 이전 게시물 이미지는 내림
    final = (
        await _upload(client, photos, author, artwork, "FINAL", data=image_bytes(color="green"))
    ).json()
    changed = await client.patch(
        f"{API}/community/posts/{post['id']}",
        json={"photo_id": final["id"]},
        headers=author.headers,
    )
    assert changed.status_code == 200, changed.text
    assert not await _can_read(app, reader, path)
    back = await client.patch(
        f"{API}/community/posts/{post['id']}",
        json={"photo_id": sketch["id"]},
        headers=author.headers,
    )
    assert back.json()["photo_id"] == sketch["id"]
    new_path = (
        await _sql(
            app,
            "SELECT storage_path FROM shared_artwork_images WHERE kind = 'POST'"
            " AND status = 'ACTIVE' AND artwork_id = :a",
            a=artwork,
        )
    )[0][0]
    assert await _can_read(app, reader, new_path)

    # 원본 사진 삭제 → 게시물은 남고 사진만 빠짐, 이미지 접근 불가
    assert (
        await client.delete(
            f"{API}/artworks/{artwork}/photos/{sketch['id']}", headers=author.headers
        )
    ).status_code == 204
    after = (await client.get(f"{API}/community/posts/{post['id']}", headers=reader.headers)).json()
    assert after["image"] is None and after["has_artwork"] is True
    assert not await _can_read(app, reader, new_path)

    # 게시물 삭제 시 게시물 이미지 정리 / 커뮤니티 철회 시 게시물·이미지 정리
    art2 = await _final_artwork(client, photos, author, "두 번째")
    s2 = (
        await _upload(client, photos, author, art2, "SKETCH", data=image_bytes(color="red"))
    ).json()
    await _share(client, author, art2)
    p2 = (await _post(client, author, artwork_id=art2, photo_id=s2["id"])).json()
    path2 = (
        await _sql(
            app,
            "SELECT storage_path FROM shared_artwork_images"
            " WHERE kind = 'POST' AND artwork_id = :a",
            a=art2,
        )
    )[0][0]
    revoked = await client.delete(
        f"{API}/artworks/{art2}/sharing/COMMUNITY", headers=author.headers
    )
    assert revoked.status_code == 200
    assert (
        await client.get(f"{API}/community/posts/{p2['id']}", headers=reader.headers)
    ).status_code == 404
    assert not await _can_read(app, reader, path2)
    assert path2 not in app.state.shared_storage.objects  # 파일도 삭제
    # 원본 사진은 그대로
    assert (
        await client.get(f"{API}/artworks/{art2}/photos/{s2['id']}/url", headers=author.headers)
    ).status_code == 200


async def test_migration_maps_existing_post_categories(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        _alembic("downgrade", "0009")
        user = await conn.fetchval(
            "INSERT INTO profiles (id, display_name, user_type) VALUES (gen_random_uuid(),"
            " 'legacy', 'STUDENT') RETURNING id"
        )
        ids = []
        for title, question in (("공유", None), ("질문", "명암 어때요?"), ("빈 질문", "  ")):
            art = await conn.fetchval(
                "INSERT INTO artworks (id, owner_id, title, work_date, work_status)"
                " VALUES (gen_random_uuid(), $1, $2, current_date, 'IN_PROGRESS') RETURNING id",
                user,
                title,
            )
            ids.append(
                await conn.fetchval(
                    "INSERT INTO community_posts"
                    " (id, artwork_id, author_id, title, question, status)"
                    " VALUES (gen_random_uuid(), $1, $2, $3, $4, 'ACTIVE') RETURNING id",
                    art,
                    user,
                    title,
                    question,
                )
            )
        _alembic("upgrade", "head")
        rows = dict(await conn.fetch("SELECT id, category FROM community_posts"))
        assert [rows[i] for i in ids] == ["ARTWORK_SHARE", "FEEDBACK_REQUEST", "ARTWORK_SHARE"]
        kinds = await conn.fetch("SELECT DISTINCT kind FROM shared_artwork_images")
        assert all(k["kind"] == "PRIMARY" for k in kinds)
    finally:
        _alembic("upgrade", "head")
        await conn.execute("DELETE FROM profiles WHERE display_name = 'legacy'")
        await conn.close()


# ============================================================================ 실기시험 단계


async def test_exam_stage_progress(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    created = await client.post(
        f"{API}/artworks",
        json={"title": "모의 실기", "work_category": "MOCK_EXAM"},
        headers=student.headers,
    )
    art = created.json()["id"]
    exam = f"{API}/artworks/{art}/exam"
    timer = f"{API}/artworks/{art}/timer/events"
    empty = (await client.get(exam, headers=student.headers)).json()
    assert empty["stages"] == [] and empty["current_stage"] is None
    no_plan = await client.post(
        f"{exam}/next", json={"current_stage": "IDEA"}, headers=student.headers
    )
    assert no_plan.json()["error"]["code"] == "EXAM_PLAN_REQUIRED"

    plan = {
        "stages": [
            {"stage": "IDEA", "target_minutes": 30},
            {"stage": "SKETCH", "target_minutes": 60},
            {"stage": "COLOR", "target_minutes": 120},
            {"stage": "FINISH", "target_minutes": 30},
        ]
    }
    saved = await client.put(f"{exam}/plan", json=plan, headers=student.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["total_target_minutes"] == 240
    detail = (await client.get(f"{API}/artworks/{art}", headers=student.headers)).json()
    assert detail["time_limit_minutes"] == 240
    dup = {"stages": [{"stage": "IDEA", "target_minutes": 1}] * 2}
    assert (await client.put(f"{exam}/plan", json=dup, headers=student.headers)).status_code == 422
    not_running = await client.post(
        f"{exam}/next", json={"current_stage": "IDEA"}, headers=student.headers
    )
    assert not_running.json()["error"]["code"] == "EXAM_NOT_RUNNING"

    now = clock.utc_now()

    async def event(name: str, minutes_ago: float | None = None) -> httpx.Response:
        body = {"event": name}
        if minutes_ago is not None:
            body["occurred_at"] = (now - timedelta(minutes=minutes_ago)).isoformat()
        return await client.post(timer, json=body, headers=student.headers)

    # 40분 전 시작, 30~20분 전 일시정지 → 아이디어 단계 작업 시간 30분
    assert (await event("START", 40)).status_code == 200
    assert (await event("PAUSE", 30)).status_code == 200
    assert (await event("RESUME", 20)).status_code == 200
    state = (await client.get(exam, headers=student.headers)).json()
    assert state["current_stage"] == "IDEA"
    idea = state["stages"][0]
    assert idea["status"] == "ACTIVE" and 1790 <= idea["elapsed_seconds"] <= 1820
    assert idea["over_target"] is False  # 목표 30분 이내 (일시정지 10분 제외)
    # 다른 단계를 보낸 요청(중복 클릭·다른 기기)은 거절
    wrong = await client.post(
        f"{exam}/next", json={"current_stage": "SKETCH"}, headers=student.headers
    )
    assert wrong.json()["error"]["code"] == "EXAM_STAGE_CONFLICT"
    assert wrong.json()["error"]["details"]["current_stage"] == "IDEA"
    moved = await client.post(
        f"{exam}/next", json={"current_stage": "IDEA"}, headers=student.headers
    )
    assert moved.json()["current_stage"] == "SKETCH"
    twice = await client.post(
        f"{exam}/next", json={"current_stage": "IDEA"}, headers=student.headers
    )
    assert twice.json()["error"]["code"] == "EXAM_STAGE_CONFLICT"
    stages = moved.json()["stages"]
    assert stages[0]["status"] == "DONE" and stages[1]["status"] == "ACTIVE"
    assert stages[1]["elapsed_seconds"] <= 5
    # 단계 전환 뒤에 그보다 이른 시각의 타이머 이벤트는 거절 (시간 역전 방지)
    late = await event("PAUSE", 5)
    assert late.status_code == 422 and late.json()["error"]["code"] == "TIMER_INVALID_TIME"

    # 시작 후 구성 변경 불가, 목표 시간 변경은 가능
    reorder = {"stages": list(reversed(plan["stages"]))}
    assert (await client.put(f"{exam}/plan", json=reorder, headers=student.headers)).json()[
        "error"
    ]["code"] == "EXAM_ALREADY_STARTED"
    retarget = {"stages": [dict(s, target_minutes=45) for s in plan["stages"]]}
    assert (await client.put(f"{exam}/plan", json=retarget, headers=student.headers)).json()[
        "total_target_minutes"
    ] == 180

    for current in ("SKETCH", "COLOR"):
        await client.post(f"{exam}/next", json={"current_stage": current}, headers=student.headers)
    last = await client.post(
        f"{exam}/next", json={"current_stage": "FINISH"}, headers=student.headers
    )
    assert last.json()["error"]["code"] == "EXAM_LAST_STAGE"
    # 다른 기기에서 같은 상태
    other_device = (await client.get(exam, headers=student.headers)).json()
    assert other_device["current_stage"] == "FINISH"
    assert (await event("STOP")).status_code == 200
    done = (await client.get(exam, headers=student.headers)).json()
    assert done["current_stage"] is None and all(s["status"] == "DONE" for s in done["stages"])
    total = sum(s["elapsed_seconds"] for s in done["stages"])
    assert abs(total - done["timer"]["elapsed_seconds"]) <= 2

    # RESET → 진행 초기화, 다른 학생 접근 불가
    await client.post(timer, json={"event": "RESET"}, headers=student.headers)
    reset = (await client.get(exam, headers=student.headers)).json()
    assert all(s["status"] == "PENDING" for s in reset["stages"])
    other = await actors.signup("STUDENT")
    assert (await client.get(exam, headers=other.headers)).status_code == 404
    assert (
        await client.post(f"{exam}/next", json={"current_stage": "IDEA"}, headers=other.headers)
    ).status_code == 404
