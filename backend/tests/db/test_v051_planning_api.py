"""v0.5.1 기획 변경 API: 프로필 실기 유형, 작품 분류·필터, 작품 완료/재개, recording_count."""

import httpx
import pytest
from sqlalchemy import event

from tests.db.conftest import Actor, World
from tests.db.test_artworks_api import _artwork, _upload
from tests.db.test_recordings_api import _consent, _record, _ticket_body
from tests.fake_storage import FakeStorage, audio_bytes, image_bytes

API = "/api/v1/artworks"
ME = "/api/v1/users/me"


@pytest.fixture
def storage(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.storage


@pytest.fixture
def audio(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.audio_storage


# ----------------------------------------------------------------------------- profile


async def test_profile_practical_type_create_and_update(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    actor = actors.anonymous_token()
    created = await client.post(
        ME,
        json={"display_name": "김학생", "user_type": "STUDENT", "practical_type": "BASIC_DESIGN"},
        headers=actor.headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["practical_type"] == "BASIC_DESIGN"
    assert (await client.get(ME, headers=actor.headers)).json()["practical_type"] == "BASIC_DESIGN"

    # 멱등 재호출은 값을 바꾸지 않는다 (변경은 PATCH)
    again = await client.post(
        ME,
        json={"display_name": "김학생", "user_type": "STUDENT", "practical_type": "DRAWING"},
        headers=actor.headers,
    )
    assert again.status_code == 200 and again.json()["practical_type"] == "BASIC_DESIGN"

    changed = await client.patch(ME, json={"practical_type": "WATERCOLOR"}, headers=actor.headers)
    assert changed.status_code == 200 and changed.json()["practical_type"] == "WATERCOLOR"
    # 다른 필드만 수정하면 실기 유형은 유지
    renamed = await client.patch(ME, json={"display_name": "새이름"}, headers=actor.headers)
    assert renamed.json()["practical_type"] == "WATERCOLOR"
    cleared = await client.patch(ME, json={"practical_type": None}, headers=actor.headers)
    assert cleared.status_code == 200 and cleared.json()["practical_type"] is None


@pytest.mark.parametrize("value", ["basic_design", "기초디자인", "PAINTING", 1, ""])
async def test_profile_practical_type_rejects_unknown_values(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, value
) -> None:
    student = await actors.signup("STUDENT")
    response = await client.patch(ME, json={"practical_type": value}, headers=student.headers)
    assert response.status_code == 422
    signup = await client.post(
        ME,
        json={"display_name": "x", "user_type": "STUDENT", "practical_type": value},
        headers=actors.anonymous_token().headers,
    )
    assert signup.status_code == 422


async def test_existing_profile_without_practical_type(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors
) -> None:
    """기존 방식(practical_type 없이) 가입한 회원은 null로 조회되고 이후 설정할 수 있다."""
    for user_type in ("STUDENT", "INSTRUCTOR"):
        actor = await actors.signup(user_type)
        me = await client.get(ME, headers=actor.headers)
        assert me.status_code == 200 and me.json()["practical_type"] is None
        updated = await client.patch(ME, json={"practical_type": "OTHER"}, headers=actor.headers)
        assert updated.json()["practical_type"] == "OTHER"


# ----------------------------------------------------------------------------- classification


async def test_artwork_classification_saved_updated_and_filtered(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors
) -> None:
    student = await actors.signup("STUDENT")
    mock_basic = await _artwork(
        client, student, title="모의 기디", practical_type="BASIC_DESIGN", work_category="MOCK_EXAM"
    )
    assert (mock_basic["practical_type"], mock_basic["work_category"]) == (
        "BASIC_DESIGN",
        "MOCK_EXAM",
    )
    assert mock_basic["work_status"] == "IN_PROGRESS" and mock_basic["completed_at"] is None
    await _artwork(
        client,
        student,
        title="연습 기디",
        practical_type="BASIC_DESIGN",
        work_category="PERSONAL_PRACTICE",
    )
    practice_drawing = await _artwork(
        client,
        student,
        title="연습 소묘",
        practical_type="DRAWING",
        work_category="PERSONAL_PRACTICE",
    )
    unclassified = await _artwork(client, student, title="미분류")
    assert unclassified["practical_type"] is None and unclassified["work_category"] is None

    async def titles(query: str) -> set[str]:
        response = await client.get(f"{API}?{query}", headers=student.headers)
        assert response.status_code == 200, response.text
        return {a["title"] for a in response.json()["items"]}

    assert await titles("practical_type=BASIC_DESIGN") == {"모의 기디", "연습 기디"}
    assert await titles("work_category=MOCK_EXAM") == {"모의 기디"}
    assert await titles("work_category=PERSONAL_PRACTICE") == {"연습 기디", "연습 소묘"}
    # 서로 다른 필드는 AND
    assert await titles("practical_type=BASIC_DESIGN&work_category=PERSONAL_PRACTICE") == {
        "연습 기디"
    }
    # 같은 필드 여러 값은 OR
    assert await titles("practical_type=BASIC_DESIGN&practical_type=DRAWING") == {
        "모의 기디",
        "연습 기디",
        "연습 소묘",
    }
    assert len(await titles("")) == 4
    bad = await client.get(f"{API}?work_category=EXAM", headers=student.headers)
    assert bad.status_code == 422

    # 수정: 분류 변경·해제, 다른 필드 수정 시 분류 유지
    detail = await client.patch(
        f"{API}/{practice_drawing['id']}",
        json={"practical_type": "WATERCOLOR", "work_category": None},
        headers=student.headers,
    )
    assert detail.status_code == 200
    assert (detail.json()["practical_type"], detail.json()["work_category"]) == ("WATERCOLOR", None)
    retitled = await client.patch(
        f"{API}/{mock_basic['id']}", json={"title": "모의 기디 2"}, headers=student.headers
    )
    assert retitled.json()["work_category"] == "MOCK_EXAM"
    got = await client.get(f"{API}/{mock_basic['id']}", headers=student.headers)
    assert got.json()["practical_type"] == "BASIC_DESIGN"
    assert got.json()["recording_count"] == 0
    invalid = await client.patch(
        f"{API}/{mock_basic['id']}", json={"practical_type": "X"}, headers=student.headers
    )
    assert invalid.status_code == 422


async def test_filters_respect_pagination_and_order(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors
) -> None:
    student = await actors.signup("STUDENT")
    for day in range(1, 6):
        await _artwork(
            client,
            student,
            title=f"모의 {day}",
            work_date=f"2026-11-0{day}",
            work_category="MOCK_EXAM",
        )
    await _artwork(client, student, title="연습", work_category="PERSONAL_PRACTICE")
    page = await client.get(
        f"{API}?work_category=MOCK_EXAM&limit=2&offset=1", headers=student.headers
    )
    body = page.json()
    assert body["total"] == 5 and body["limit"] == 2 and body["offset"] == 1
    assert [a["title"] for a in body["items"]] == ["모의 4", "모의 3"]


# ----------------------------------------------------------------------------- completion


async def test_complete_requires_final_photo_and_locks_photos(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, storage: FakeStorage, audio: FakeStorage
) -> None:
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    base = f"{API}/{artwork['id']}"

    no_final = await client.post(f"{base}/complete", headers=student.headers)
    assert (no_final.status_code, no_final.json()["error"]["code"]) == (409, "FINAL_PHOTO_REQUIRED")
    sketch = (await _upload(client, storage, student, artwork["id"], stage="SKETCH")).json()
    still_no_final = await client.post(f"{base}/complete", headers=student.headers)
    assert still_no_final.status_code == 409

    final = (
        await _upload(
            client, storage, student, artwork["id"], "FINAL", image_bytes("PNG", color="red")
        )
    ).json()
    # 완료 직전에 시작한 업로드 (완료 처리 시 취소되어야 함)
    pending = await client.post(
        f"{base}/photos",
        json={"stage": "PROGRESS", "content_type": "image/png", "file_size": 100},
        headers=student.headers,
    )
    assert pending.status_code == 201

    done = await client.post(f"{base}/complete", headers=student.headers)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["work_status"] == "COMPLETED" and body["completed_at"] is not None
    assert body["progress"] == "FINAL"
    # 멱등: 완료 시각 유지
    again = await client.post(f"{base}/complete", headers=student.headers)
    assert again.status_code == 200 and again.json()["completed_at"] == body["completed_at"]

    progress = (await client.get(f"{base}/progress", headers=student.headers)).json()
    assert progress["work_status"] == "COMPLETED" and progress["has_final_photo"] is True
    assert progress["completed"] is True  # 호환 필드 (= has_final_photo)
    listing = (await client.get(f"{API}?work_status=COMPLETED", headers=student.headers)).json()
    assert [a["id"] for a in listing["items"]] == [artwork["id"]]
    assert listing["items"][0]["completed_at"] == body["completed_at"]

    # 사진 변경은 모두 409 ARTWORK_COMPLETED
    blocked = [
        await client.post(
            f"{base}/photos",
            json={"stage": "FINAL", "content_type": "image/png", "file_size": 100},
            headers=student.headers,
        ),
        await client.post(
            f"{base}/photos/{pending.json()['photo']['id']}/complete", headers=student.headers
        ),
        await client.delete(f"{base}/photos/{final['id']}", headers=student.headers),
        await client.patch(
            f"{base}/photos/{sketch['id']}",
            json={"is_representative": True},
            headers=student.headers,
        ),
    ]
    assert [r.status_code for r in blocked] == [409, 404, 409, 409]
    assert blocked[0].json()["error"]["code"] == "ARTWORK_COMPLETED"
    # 사진 조회·Signed URL, 메타데이터 수정, 피드백 녹음은 가능
    assert (
        await client.get(f"{base}/photos/{final['id']}/url", headers=student.headers)
    ).status_code == 200
    edited = await client.patch(
        base, json={"title": "완성작", "work_category": "MOCK_EXAM"}, headers=student.headers
    )
    assert edited.status_code == 200 and edited.json()["work_status"] == "COMPLETED"
    assert (await _consent(client, student)).status_code == 201
    assert (await _record(client, audio, student, artwork["id"])).status_code == 200

    # 작업 재개 → 다시 사진 변경 가능, 완료 시각 제거
    reopened = await client.post(f"{base}/reopen", headers=student.headers)
    assert reopened.status_code == 200
    assert reopened.json()["work_status"] == "IN_PROGRESS"
    assert reopened.json()["completed_at"] is None
    assert (await client.post(f"{base}/reopen", headers=student.headers)).status_code == 200
    assert (
        await client.delete(f"{base}/photos/{final['id']}", headers=student.headers)
    ).status_code == 204
    # FINAL 사진을 지웠으니 다시 완료하려면 FINAL 사진이 필요
    assert (await client.post(f"{base}/complete", headers=student.headers)).status_code == 409


async def test_completion_access_control(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, storage: FakeStorage
) -> None:
    s1, s2 = world.students[0], world.students[1]
    artwork = await _artwork(client, s1, academy_id=world.academy_id)
    await _upload(client, storage, s1, artwork["id"], "FINAL")
    base = f"{API}/{artwork['id']}"
    # 다른 학생: 404 (존재 비노출), 강사·원장: 학생 전용 API라 403
    for actor, expected in ((s2, 404), (world.teacher, 403), (world.owner, 403)):
        for action in ("complete", "reopen"):
            response = await client.post(f"{base}/{action}", headers=actor.headers)
            assert response.status_code == expected, (actor, action, response.text)
    assert (await client.post(f"{base}/complete", headers=s1.headers)).status_code == 200
    # 강사는 완료 상태를 조회만 한다
    staff = await client.get(
        f"{world.base}/artworks/{artwork['id']}", headers=world.teacher.headers
    )
    assert staff.json()["work_status"] == "COMPLETED"


# ----------------------------------------------------------------------------- recording_count


async def test_recording_count_in_lists(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, audio: FakeStorage
) -> None:
    s1, s2 = world.students[0], world.students[1]
    for student in (s1, s2):
        assert (await _consent(client, student)).status_code == 201
    first = await _artwork(client, s1, academy_id=world.academy_id, title="세 개")
    second = await _artwork(client, s1, academy_id=world.academy_id, title="없음")
    other = await _artwork(client, s2, academy_id=world.academy_id, title="다른 학생")

    kept = []
    for kind in ("webm", "ogg", "mp4"):
        response = await _record(client, audio, s1, first["id"], audio_bytes(kind), f"audio/{kind}")
        assert response.status_code == 200, response.text
        kept.append(response.json()["id"])
    # 삭제된 녹음, 업로드 미완료(PENDING) 녹음은 제외
    deleted = await _record(client, audio, s1, first["id"], audio_bytes("wav"), "audio/wav")
    assert (
        await client.delete(
            f"{API}/{first['id']}/recordings/{deleted.json()['id']}", headers=s1.headers
        )
    ).status_code == 204
    pending = await client.post(
        f"{API}/{first['id']}/recordings",
        json=_ticket_body(audio_bytes("webm")),
        headers=s1.headers,
    )
    assert pending.status_code == 201
    other_recording = await _record(client, audio, s2, other["id"])
    assert other_recording.status_code == 200

    mine = (await client.get(API, headers=s1.headers)).json()["items"]
    assert {a["title"]: a["recording_count"] for a in mine} == {"세 개": 3, "없음": 0}
    detail = await client.get(f"{API}/{first['id']}", headers=s1.headers)
    assert detail.json()["recording_count"] == 3
    assert (await client.get(f"{API}/{second['id']}", headers=s1.headers)).json()[
        "recording_count"
    ] == 0

    # 담당 강사 목록: 담당 학생 작품의 녹음만 집계
    staff = await client.get(f"{world.base}/artworks", headers=world.teacher.headers)
    counts = {a["title"]: a["recording_count"] for a in staff.json()["items"]}
    assert counts == {"세 개": 3, "없음": 0, "다른 학생": 1}
    filtered = await client.get(
        f"{world.base}/artworks?student_membership_id={s1.membership_id}",
        headers=world.teacher.headers,
    )
    assert {a["title"] for a in filtered.json()["items"]} == {"세 개", "없음"}
    # 비담당 강사는 학원 작품 목록이 비어 있다 (다른 학생 녹음 수 노출 없음)
    hidden = await client.get(f"{world.base}/artworks", headers=world.other_teacher.headers)
    assert hidden.json()["items"] == []


async def test_artwork_list_query_count_does_not_grow(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, storage: FakeStorage, audio: FakeStorage
) -> None:
    """N+1 방지: 작품 수와 무관하게 목록 조회 SQL 수가 같다."""
    student = await actors.signup("STUDENT")
    assert (await _consent(client, student)).status_code == 201

    async def add_artwork(i: int) -> None:
        artwork = await _artwork(client, student, title=f"작품 {i}")
        await _upload(
            client, storage, student, artwork["id"], data=image_bytes("PNG", color=(i, 0, 0))
        )
        await _record(client, audio, student, artwork["id"], audio_bytes("webm"))

    statements: list[str] = []

    def count(conn, cursor, statement, *args) -> None:  # type: ignore[no-untyped-def]
        statements.append(statement)

    async def list_queries() -> int:
        statements.clear()
        engine = app.state.database.engine.sync_engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            response = await client.get(f"{API}?limit=50", headers=student.headers)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert response.status_code == 200
        return len(statements)

    await add_artwork(1)
    one = await list_queries()
    for i in range(2, 7):
        await add_artwork(i)
    six = await list_queries()
    assert six == one, (one, six)


async def test_other_students_artworks_stay_hidden(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors
) -> None:
    owner: Actor = await actors.signup("STUDENT")
    intruder: Actor = await actors.signup("STUDENT")
    artwork = await _artwork(client, owner, practical_type="DRAWING", work_category="MOCK_EXAM")
    listing = await client.get(
        f"{API}?practical_type=DRAWING&work_category=MOCK_EXAM", headers=intruder.headers
    )
    assert listing.json()["total"] == 0
    for method, path, body in (
        ("GET", f"{API}/{artwork['id']}", None),
        ("PATCH", f"{API}/{artwork['id']}", {"practical_type": "OTHER"}),
        ("GET", f"{API}/{artwork['id']}/progress", None),
    ):
        response = await client.request(method, path, json=body, headers=intruder.headers)
        assert response.status_code == 404, (method, path)
