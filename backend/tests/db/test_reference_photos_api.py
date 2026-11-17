"""v1.1 원본 제시물 사진·시험 조건·표현 의도 API (FakeStorage + 테스트 DB, AI 호출 없음)."""

from __future__ import annotations

import httpx
from sqlalchemy import text

from tests.db.test_artworks_api import _upload
from tests.fake_storage import FakeStorage, image_bytes

API = "/api/v1/artworks"


async def _artwork(client: httpx.AsyncClient, owner, **body) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(API, json={"title": "기초디자인"} | body, headers=owner.headers)
    assert created.status_code == 201, created.text
    return created.json()


async def _ref(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient,
    storage: FakeStorage,
    owner,
    artwork_id: str,
    data: bytes | None = None,
    content_type: str = "image/png",
    **extra,
) -> httpx.Response:
    payload = data if data is not None else image_bytes("PNG", color="green")
    ticket = await client.post(
        f"{API}/{artwork_id}/reference-photos",
        json={"content_type": content_type, "file_size": len(payload)} | extra,
        headers=owner.headers,
    )
    if ticket.status_code != 201:
        return ticket
    storage.put(ticket.json()["upload"]["path"], payload)
    return await client.post(
        f"{API}/{artwork_id}/reference-photos/{ticket.json()['photo']['id']}/complete",
        headers=owner.headers,
    )


async def test_reference_upload_list_limit_replace_delete(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    aid = artwork["id"]

    first = await _ref(client, storage, student, aid)
    assert first.status_code == 200, first.text
    ref = first.json()
    assert (ref["status"], ref["position"], ref["width"]) == ("ACTIVE", 0, 32)
    # 경로는 서버가 만든다: 본인 폴더 + ref- 접두사 (기존 작품 사진 경로와 구분)
    path = next(p for p in storage.objects if ref["id"] in p)
    assert path.startswith(f"{student.user_id}/{aid}/ref-")

    colors = ["red", "blue", "yellow", "white"]
    for color in colors:
        assert (
            await _ref(client, storage, student, aid, image_bytes("PNG", color=color))
        ).status_code == 200
    listed = (
        await client.get(f"{API}/{aid}/reference-photos?include_urls=true", headers=student.headers)
    ).json()
    assert listed["max_count"] == 5
    assert [p["position"] for p in listed["items"]] == [0, 1, 2, 3, 4]
    assert all(p["url"] for p in listed["items"])

    # 최대 5장
    over = await _ref(client, storage, student, aid, image_bytes("PNG", color="black"))
    assert over.status_code == 409 and over.json()["error"]["code"] == "PHOTO_LIMIT_REACHED"

    # 교체는 제한과 무관, 같은 자리
    second = listed["items"][1]
    replaced = await _ref(
        client,
        storage,
        student,
        aid,
        image_bytes("JPEG", color="purple"),
        "image/jpeg",
        replaces_photo_id=second["id"],
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["position"] == 1
    after = (await client.get(f"{API}/{aid}/reference-photos", headers=student.headers)).json()
    assert second["id"] not in [p["id"] for p in after["items"]] and len(after["items"]) == 5

    # 삭제 → 목록에서 빠지고 파일 정리
    gone = await client.delete(f"{API}/{aid}/reference-photos/{ref['id']}", headers=student.headers)
    assert gone.status_code == 204
    assert path not in storage.objects
    remaining = (await client.get(f"{API}/{aid}/reference-photos", headers=student.headers)).json()
    assert len(remaining["items"]) == 4
    # 작품 사진 수·진행률에는 섞이지 않는다
    detail = (await client.get(f"{API}/{aid}", headers=student.headers)).json()
    assert detail["photo_count"] == 0 and detail["progress"] == "NOT_STARTED"


async def test_reference_validation(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    aid = (await _artwork(client, student))["id"]

    gif = await _ref(client, storage, student, aid, b"GIF89a....", "image/gif")
    assert gif.status_code == 422
    huge = await client.post(
        f"{API}/{aid}/reference-photos",
        json={"content_type": "image/png", "file_size": 50 * 1024 * 1024},
        headers=student.headers,
    )
    assert huge.status_code == 422
    # 선언은 PNG인데 실제 이미지가 아님 → 완료 단계에서 거부·정리
    fake = await _ref(client, storage, student, aid, b"not an image at all" * 10)
    assert fake.status_code == 422
    assert not [p for p in storage.objects if "/ref-" in p]
    # 같은 파일 중복
    same = image_bytes("PNG", color="orange")
    assert (await _ref(client, storage, student, aid, same)).status_code == 200
    dup = await _ref(client, storage, student, aid, same)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_PHOTO"
    # 아직 안 올린 파일로 완료 → 409 (재시도 가능)
    ticket = await client.post(
        f"{API}/{aid}/reference-photos",
        json={"content_type": "image/png", "file_size": 100},
        headers=student.headers,
    )
    early = await client.post(
        f"{API}/{aid}/reference-photos/{ticket.json()['photo']['id']}/complete",
        headers=student.headers,
    )
    assert early.status_code == 409 and early.json()["error"]["code"] == "UPLOAD_NOT_FOUND"


async def test_other_student_cannot_touch_reference_photos(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    other = await actors.signup("STUDENT")
    aid = (await _artwork(client, student))["id"]
    ref = (await _ref(client, storage, student, aid)).json()

    for method, url, body in (
        ("GET", f"{API}/{aid}/reference-photos", None),
        ("POST", f"{API}/{aid}/reference-photos", {"content_type": "image/png", "file_size": 10}),
        ("POST", f"{API}/{aid}/reference-photos/{ref['id']}/complete", None),
        ("DELETE", f"{API}/{aid}/reference-photos/{ref['id']}", None),
        ("GET", f"{API}/{aid}/comparison-input", None),
    ):
        res = await client.request(method, url, json=body, headers=other.headers)
        assert res.status_code == 404, (method, url, res.text)
    still = (await client.get(f"{API}/{aid}/reference-photos", headers=student.headers)).json()
    assert [p["id"] for p in still["items"]] == [ref["id"]]


async def test_storage_access_function_allows_only_owner(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    """Supabase Storage 정책이 부르는 함수: 원본 사진은 소유자만 읽기·쓰기 (삭제 후 읽기 불가)."""
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    other = await actors.signup("STUDENT")
    aid = (await _artwork(client, student))["id"]
    ref = (await _ref(client, storage, student, aid)).json()
    path = next(p for p in storage.objects if ref["id"] in p)

    async def allowed(user_id, mode: str) -> bool:  # type: ignore[no-untyped-def]
        async with app.state.database.engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT artmate_private.can_access_artwork_object(:u, :p, :m)"),
                    {"u": user_id, "p": path, "m": mode},
                )
            ).scalar_one()

    assert await allowed(student.user_id, "read") and await allowed(student.user_id, "write")
    assert not await allowed(other.user_id, "read") and not await allowed(other.user_id, "write")
    await client.delete(f"{API}/{aid}/reference-photos/{ref['id']}", headers=student.headers)
    assert not await allowed(student.user_id, "read")
    assert await allowed(student.user_id, "write")  # 정리(삭제)는 소유자가 할 수 있어야 한다


async def test_completed_artwork_accepts_references_and_delete_cleans_up(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    aid = (await _artwork(client, student))["id"]
    assert (await _upload(client, storage, student, aid, "FINAL")).status_code == 200
    done = await client.post(f"{API}/{aid}/complete", headers=student.headers)
    assert done.status_code == 200 and done.json()["work_status"] == "COMPLETED"
    # 완료한 기존 작품에도 원본 사진을 나중에 추가할 수 있다 (작품 사진은 잠김 유지)
    assert (await _ref(client, storage, student, aid)).status_code == 200
    locked = await client.post(
        f"{API}/{aid}/photos",
        json={"stage": "SKETCH", "content_type": "image/png", "file_size": 100},
        headers=student.headers,
    )
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "ARTWORK_COMPLETED"

    ref_paths = [p for p in storage.objects if "/ref-" in p]
    assert ref_paths
    deleted = await client.delete(f"{API}/{aid}", headers=student.headers)
    assert deleted.status_code == 204
    assert not [p for p in storage.objects if "/ref-" in p]
    assert (
        await client.get(f"{API}/{aid}/reference-photos", headers=student.headers)
    ).status_code == 404


async def test_exam_conditions_and_intent_save_update_and_compat(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    # 새 필드 없이 만든 작품(기존 방식) → 기본값으로 정상 응답
    plain = await _artwork(client, student)
    assert (plain["paper_size"], plain["expression_methods"], plain["expression_intent"]) == (
        None,
        [],
        None,
    )
    listed = (await client.get(API, headers=student.headers)).json()
    assert listed["items"][0]["expression_methods"] == []

    full = await _artwork(
        client,
        student,
        practical_type="BASIC_DESIGN",
        topic="유리컵과 사과",
        exam_materials="유리컵, 사과 2개",
        time_limit_minutes=240,
        paper_size="4절",
        exam_conditions="제시물 2개 이상 사용",
        description="자유 메모",
        expression_methods=["REARRANGE", "SCALE", "SCALE"],
        expression_intent="유리컵을 기울여 역동적인 구도를 만들었다.",
    )
    assert full["expression_methods"] == ["SCALE", "REARRANGE"]  # 중복 제거·정의 순서
    aid = full["id"]

    patched = await client.patch(
        f"{API}/{aid}",
        json={"expression_methods": ["ROTATE"], "paper_size": None, "expression_intent": "수정"},
        headers=student.headers,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert (body["expression_methods"], body["paper_size"], body["expression_intent"]) == (
        ["ROTATE"],
        None,
        "수정",
    )
    assert body["exam_conditions"] == "제시물 2개 이상 사용"  # 보내지 않은 필드는 유지
    bad = await client.patch(
        f"{API}/{aid}", json={"expression_methods": None}, headers=student.headers
    )
    assert bad.status_code == 422
    invalid = await client.patch(
        f"{API}/{aid}", json={"expression_methods": ["MAGIC"]}, headers=student.headers
    )
    assert invalid.status_code == 422
    cleared = await client.patch(
        f"{API}/{aid}",
        json={"expression_methods": [], "expression_intent": None},
        headers=student.headers,
    )
    assert cleared.json()["expression_methods"] == []

    # v1.2 입력: 의도 없음 → NOT_PROVIDED, 사진이 생기면 ready
    pre = (await client.get(f"{API}/{aid}/comparison-input", headers=student.headers)).json()
    assert pre["intent"]["status"] == "NOT_PROVIDED"
    assert pre["readiness"] == {"ready": False, "missing": ["REFERENCE_PHOTO", "ARTWORK_PHOTO"]}
    await _ref(client, storage, student, aid)
    await _upload(client, storage, student, aid, "SKETCH")
    ready = (await client.get(f"{API}/{aid}/comparison-input", headers=student.headers)).json()
    assert ready["readiness"]["ready"] is True
    assert ready["exam"]["topic"] == "유리컵과 사과" and ready["exam"]["exam_conditions"]
    assert len(ready["references"]) == 1 and ready["stages"][0]["photos"][0]["role"] == "ARTWORK"
    assert "storage_path" not in str(ready) and "/ref-" not in str(ready)
