"""작품·단계별 사진 (F-06): 생성·수정·삭제, 업로드 2단계, 검증, 중복, Storage 실패, 권한."""

import asyncio
import datetime as dt

import httpx
import pytest

from app.core import timezone as clock
from tests.db.conftest import Actor, World
from tests.fake_storage import FakeStorage, image_bytes

API = "/api/v1/artworks"


@pytest.fixture
def storage(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.storage


async def _artwork(client: httpx.AsyncClient, owner: Actor, **body) -> dict:  # type: ignore[no-untyped-def]
    response = await client.post(API, json={"title": "석고 소묘"} | body, headers=owner.headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _upload(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient,
    storage: FakeStorage,
    owner: Actor,
    artwork_id: str,
    stage: str = "SKETCH",
    data: bytes | None = None,
    content_type: str = "image/png",
    **extra,
) -> httpx.Response:
    """업로드 요청 → (클라이언트가) Storage에 올림 → 완료 처리."""
    payload = data if data is not None else image_bytes("PNG", color="blue")
    ticket = await client.post(
        f"{API}/{artwork_id}/photos",
        json={"stage": stage, "content_type": content_type, "file_size": len(payload)} | extra,
        headers=owner.headers,
    )
    assert ticket.status_code == 201, ticket.text
    storage.put(ticket.json()["upload"]["path"], payload)
    return await client.post(
        f"{API}/{artwork_id}/photos/{ticket.json()['photo']['id']}/complete",
        headers=owner.headers,
    )


# ----------------------------------------------------------------------------- artworks


async def test_personal_artwork_without_academy(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student, description="첫 작품")
    assert artwork["academy_id"] is None and artwork["student_membership_id"] is None
    assert artwork["work_date"] == clock.local_today().isoformat()
    assert artwork["progress"] == "NOT_STARTED" and artwork["photo_count"] == 0

    listing = await client.get(API, headers=student.headers)
    assert [a["id"] for a in listing.json()["items"]] == [artwork["id"]]

    edited = await client.patch(
        f"{API}/{artwork['id']}",
        json={"title": "석고 소묘 (수정)", "work_date": "2026-11-01", "description": None},
        headers=student.headers,
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "석고 소묘 (수정)" and edited.json()["description"] is None

    # 강사 계정은 작품을 만들 수 없다
    teacher = await actors.signup("INSTRUCTOR")
    assert (await client.post(API, json={"title": "x"}, headers=teacher.headers)).status_code == 403

    assert (
        await client.delete(f"{API}/{artwork['id']}", headers=student.headers)
    ).status_code == 204
    assert (await client.get(f"{API}/{artwork['id']}", headers=student.headers)).status_code == 404
    assert (await client.get(API, headers=student.headers)).json()["total"] == 0


async def test_academy_class_task_links(client: httpx.AsyncClient, world: World) -> None:
    student = world.students[0]
    task = await client.post(
        f"{world.base}/tasks",
        json={"class_id": world.class_id, "title": "과제"},
        headers=world.teacher.headers,
    )
    task_id = task.json()["id"]

    linked = await _artwork(client, student, academy_id=world.academy_id, task_id=task_id)
    assert linked["student_membership_id"] == student.membership_id
    assert linked["class_id"] == world.class_id  # 과제의 반이 자동 연결
    assert linked["task_id"] == task_id

    # 소속되지 않은 학원 / 배정되지 않은 반 / 배정되지 않은 과제 → 422
    outsider = world.students[2]  # 반 미배정
    for body in (
        {"academy_id": "00000000-0000-4000-8000-000000000000"},
        {"academy_id": world.academy_id, "class_id": world.class_id},
        {"academy_id": world.academy_id, "task_id": task_id},
        {"class_id": world.class_id},  # 학원 없이 반만
    ):
        response = await client.post(API, json={"title": "x"} | body, headers=outsider.headers)
        assert response.status_code == 422, body
        assert response.json()["error"]["code"] == "INVALID_ARTWORK_LINK"

    # 학원 연결 해제 → 반·과제도 해제
    unlinked = await client.patch(
        f"{API}/{linked['id']}", json={"academy_id": None}, headers=student.headers
    )
    assert unlinked.status_code == 200
    body = unlinked.json()
    assert (body["academy_id"], body["class_id"], body["task_id"]) == (None, None, None)


# ----------------------------------------------------------------------------- photos


async def test_stage_photo_upload_flow(
    client: httpx.AsyncClient, actors, storage: FakeStorage
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    data = image_bytes("JPEG", (64, 48))

    ticket = await client.post(
        f"{API}/{artwork['id']}/photos",
        json={
            "stage": "SKETCH",
            "content_type": "image/jpeg",
            "file_size": len(data),
            "file_name": "스케치.JPG",
        },
        headers=student.headers,
    )
    assert ticket.status_code == 201, ticket.text
    upload = ticket.json()["upload"]
    photo = ticket.json()["photo"]
    assert photo["status"] == "PENDING"
    # 서버가 만든 안전한 경로: {owner}/{artwork}/{photo}.jpg (사용자 파일명 미사용)
    assert upload["path"] == f"{student.user_id}/{artwork['id']}/{photo['id']}.jpg"
    assert upload["bucket"] == "artworks" and upload["token"]
    # 사용자 토큰으로 Storage를 호출 (service_role 아님)
    assert storage.calls[-1][2] == student.headers["Authorization"].removeprefix("Bearer ")

    # 아직 업로드 전 완료 → 409, 사진은 PENDING 유지 (재시도 가능)
    early = await client.post(
        f"{API}/{artwork['id']}/photos/{photo['id']}/complete", headers=student.headers
    )
    assert early.status_code == 409 and early.json()["error"]["code"] == "UPLOAD_NOT_FOUND"

    storage.put(upload["path"], data)
    done = await client.post(
        f"{API}/{artwork['id']}/photos/{photo['id']}/complete", headers=student.headers
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "ACTIVE" and body["is_representative"] is True
    assert (body["width"], body["height"], body["size_bytes"]) == (64, 48, len(data))

    # 완료 재호출은 같은 결과 (멱등)
    again = await client.post(
        f"{API}/{artwork['id']}/photos/{photo['id']}/complete", headers=student.headers
    )
    assert again.status_code == 200 and again.json() == body

    # 단계 여러 장 + 진행 상태
    assert (
        await _upload(client, storage, student, artwork["id"], "SKETCH", image_bytes(color="green"))
    ).status_code == 200
    progress_photo = await _upload(client, storage, student, artwork["id"], "PROGRESS")
    assert progress_photo.status_code == 200
    progress = (await client.get(f"{API}/{artwork['id']}/progress", headers=student.headers)).json()
    assert progress["progress"] == "PROGRESS" and progress["completed"] is False
    counts = {s["stage"]: s["photo_count"] for s in progress["stages"]}
    assert counts == {"SKETCH": 2, "PROGRESS": 1, "FINAL": 0}
    assert progress["stages"][0]["representative_photo_id"] == photo["id"]

    await _upload(client, storage, student, artwork["id"], "FINAL", image_bytes(color="white"))
    detail = (
        await client.get(f"{API}/{artwork['id']}?include_urls=true", headers=student.headers)
    ).json()
    assert detail["progress"] == "FINAL" and detail["photo_count"] == 4
    assert [p["stage"] for p in detail["photos"]] == ["SKETCH", "SKETCH", "PROGRESS", "FINAL"]
    assert all(p["url"].startswith("https://storage.test/object/sign/") for p in detail["photos"])
    assert detail["cover_photo_id"] == next(
        p["id"] for p in detail["photos"] if p["stage"] == "FINAL"
    )

    url = await client.get(
        f"{API}/{artwork['id']}/photos/{photo['id']}/url", headers=student.headers
    )
    assert url.status_code == 200 and "signed" in url.json()["url"]


async def test_invalid_files_are_rejected(
    client: httpx.AsyncClient, actors, storage: FakeStorage
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    photos = f"{API}/{artwork['id']}/photos"

    # 요청 단계: 형식·확장자·크기
    for body, code in (
        ({"content_type": "image/gif", "file_size": 10}, "UNSUPPORTED_FILE_TYPE"),
        (
            {"content_type": "image/png", "file_size": 10, "file_name": "a.exe"},
            "UNSUPPORTED_FILE_TYPE",
        ),
        ({"content_type": "image/png", "file_size": 50 * 1024 * 1024}, "FILE_TOO_LARGE"),
    ):
        response = await client.post(
            photos, json={"stage": "SKETCH"} | body, headers=student.headers
        )
        assert response.status_code == 422 and response.json()["error"]["code"] == code
    bad_stage = await client.post(
        photos,
        json={"stage": "COLOR", "content_type": "image/png", "file_size": 1},
        headers=student.headers,
    )
    assert bad_stage.status_code == 422

    # 완료 단계: 실제 내용 검증 → 사진 DELETED + Storage 파일 삭제
    for data, code in (
        (b"<?php echo 1; ?>", "INVALID_IMAGE"),
        (image_bytes("JPEG"), "INVALID_IMAGE"),
    ):
        response = await _upload(client, storage, student, artwork["id"], data=data)
        assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert storage.objects == {}  # 거부된 파일은 정리됨
    listing = await client.get(photos, headers=student.headers)
    assert listing.json() == []


async def test_duplicate_upload_and_limit(
    client: httpx.AsyncClient, actors, storage: FakeStorage, app
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    same = image_bytes(color="purple")
    assert (await _upload(client, storage, student, artwork["id"], data=same)).status_code == 200
    duplicate = await _upload(client, storage, student, artwork["id"], "PROGRESS", data=same)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_PHOTO"
    assert len(storage.objects) == 1

    # 단계별 최대 장수 (설정값)
    app.state.settings.artwork_max_photos_per_stage = 2
    try:
        assert (
            await _upload(client, storage, student, artwork["id"], data=image_bytes(color="cyan"))
        ).status_code == 200
        over = await client.post(
            f"{API}/{artwork['id']}/photos",
            json={"stage": "SKETCH", "content_type": "image/png", "file_size": 100},
            headers=student.headers,
        )
        assert over.status_code == 409 and over.json()["error"]["code"] == "PHOTO_LIMIT_REACHED"
    finally:
        app.state.settings.artwork_max_photos_per_stage = 10


async def test_replace_representative_and_delete(
    client: httpx.AsyncClient, actors, storage: FakeStorage
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    first = (
        await _upload(client, storage, student, artwork["id"], data=image_bytes(color="red"))
    ).json()
    second = (
        await _upload(client, storage, student, artwork["id"], data=image_bytes(color="lime"))
    ).json()
    assert first["is_representative"] and not second["is_representative"]

    # 대표 사진 변경
    switched = await client.patch(
        f"{API}/{artwork['id']}/photos/{second['id']}",
        json={"is_representative": True},
        headers=student.headers,
    )
    assert switched.json()["is_representative"] is True
    photos = (await client.get(f"{API}/{artwork['id']}/photos", headers=student.headers)).json()
    assert [p["id"] for p in photos if p["is_representative"]] == [second["id"]]

    # 교체: 새 사진이 대표를 이어받고 기존 파일은 삭제
    old_path = next(path for path in storage.objects if second["id"] in path)
    replaced = await _upload(
        client,
        storage,
        student,
        artwork["id"],
        stage="SKETCH",
        data=image_bytes(color="navy"),
        replaces_photo_id=second["id"],
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["is_representative"] is True
    assert old_path not in storage.objects
    photos = (await client.get(f"{API}/{artwork['id']}/photos", headers=student.headers)).json()
    assert {p["id"] for p in photos} == {first["id"], replaced.json()["id"]}

    # 대표 사진 삭제 → 남은 사진이 대표
    deleted = await client.delete(
        f"{API}/{artwork['id']}/photos/{replaced.json()['id']}", headers=student.headers
    )
    assert deleted.status_code == 204
    photos = (await client.get(f"{API}/{artwork['id']}/photos", headers=student.headers)).json()
    assert [(p["id"], p["is_representative"]) for p in photos] == [(first["id"], True)]
    assert len(storage.objects) == 1


async def test_storage_failures_keep_db_consistent(
    client: httpx.AsyncClient, actors, storage: FakeStorage
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    photos = f"{API}/{artwork['id']}/photos"
    request = {"stage": "SKETCH", "content_type": "image/png", "file_size": 100}

    # 1) 업로드 URL 발급 실패 → 503, 사진 행 남지 않음
    storage.fail = {"upload_url"}
    failed = await client.post(photos, json=request, headers=student.headers)
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    storage.fail = set()
    retry_ticket = await client.post(photos, json=request, headers=student.headers)
    assert retry_ticket.status_code == 201  # 단계 장수 제한에 실패한 요청이 포함되지 않음

    # 2) 완료 처리 중 다운로드 실패 → 503, PENDING 유지 → 복구 후 재시도 성공
    data = image_bytes(color="olive")
    storage.put(retry_ticket.json()["upload"]["path"], data)
    complete = f"{photos}/{retry_ticket.json()['photo']['id']}/complete"
    storage.fail = {"download"}
    assert (await client.post(complete, headers=student.headers)).status_code == 503
    storage.fail = set()
    assert (await client.post(complete, headers=student.headers)).json()["status"] == "ACTIVE"

    # 3) 삭제 시 Storage 실패 → DB는 삭제됨, 파일은 다음 요청에서 정리
    storage.fail = {"delete"}
    photo_id = retry_ticket.json()["photo"]["id"]
    assert (await client.delete(f"{photos}/{photo_id}", headers=student.headers)).status_code == 204
    assert (await client.get(photos, headers=student.headers)).json() == []
    assert len(storage.objects) == 1  # 아직 남아 있음 (cleanup pending)
    storage.fail = set()
    await client.post(photos, json=request, headers=student.headers)  # 다음 쓰기 요청이 정리
    assert data not in storage.objects.values()

    # 4) Signed URL 발급 실패 → 503
    good = await _upload(client, storage, student, artwork["id"], data=image_bytes(color="teal"))
    storage.fail = {"sign"}
    url = await client.get(f"{photos}/{good.json()['id']}/url", headers=student.headers)
    assert url.status_code == 503
    storage.fail = set()


async def test_expired_upload(
    client: httpx.AsyncClient, actors, storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    ticket = await client.post(
        f"{API}/{artwork['id']}/photos",
        json={"stage": "SKETCH", "content_type": "image/png", "file_size": 100},
        headers=student.headers,
    )
    storage.put(ticket.json()["upload"]["path"], image_bytes())
    later = clock.utc_now() + dt.timedelta(hours=2)
    monkeypatch.setattr(clock, "utc_now", lambda: later)
    expired = await client.post(
        f"{API}/{artwork['id']}/photos/{ticket.json()['photo']['id']}/complete",
        headers=student.headers,
    )
    assert expired.status_code == 409 and expired.json()["error"]["code"] == "UPLOAD_EXPIRED"
    assert storage.objects == {}


async def test_concurrent_completion_is_idempotent(
    client: httpx.AsyncClient, actors, storage: FakeStorage
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    ticket = await client.post(
        f"{API}/{artwork['id']}/photos",
        json={"stage": "FINAL", "content_type": "image/png", "file_size": 100},
        headers=student.headers,
    )
    storage.put(ticket.json()["upload"]["path"], image_bytes())
    path = f"{API}/{artwork['id']}/photos/{ticket.json()['photo']['id']}/complete"
    responses = await asyncio.gather(
        *[client.post(path, headers=student.headers) for _ in range(5)]
    )
    assert [r.status_code for r in responses] == [200] * 5
    assert len({r.json()["uploaded_at"] for r in responses}) == 1
    photos = (await client.get(f"{API}/{artwork['id']}/photos", headers=student.headers)).json()
    assert len(photos) == 1 and photos[0]["is_representative"]


# ----------------------------------------------------------------------------- access


async def test_other_students_cannot_access(
    client: httpx.AsyncClient, world: World, storage: FakeStorage
) -> None:
    owner, other = world.students[0], world.students[1]
    artwork = await _artwork(client, owner, academy_id=world.academy_id)
    photo = (await _upload(client, storage, owner, artwork["id"])).json()
    base = f"{API}/{artwork['id']}"

    for method, path, body in (
        ("GET", base, None),
        ("PATCH", base, {"title": "x"}),
        ("DELETE", base, None),
        ("GET", f"{base}/photos", None),
        ("GET", f"{base}/progress", None),
        (
            "POST",
            f"{base}/photos",
            {"stage": "SKETCH", "content_type": "image/png", "file_size": 1},
        ),
        ("GET", f"{base}/photos/{photo['id']}/url", None),
        ("DELETE", f"{base}/photos/{photo['id']}", None),
        ("POST", f"{base}/photos/{photo['id']}/complete", None),
    ):
        response = await client.request(method, path, json=body, headers=other.headers)
        assert response.status_code == 404, (method, path)
    # 학생은 강사용 작품 API를 쓸 수 없다
    staff_path = f"{world.base}/artworks/{artwork['id']}"
    assert (await client.get(staff_path, headers=other.headers)).status_code == 403


async def test_instructor_sees_only_managed_students(
    client: httpx.AsyncClient, world: World, storage: FakeStorage, build_world
) -> None:  # type: ignore[no-untyped-def]
    s1, s3 = world.students[0], world.students[2]  # s3은 반 미배정
    linked = await _artwork(client, s1, academy_id=world.academy_id, title="학원 작품")
    personal = await _artwork(client, s1, title="개인 작품")
    not_managed = await _artwork(client, s3, academy_id=world.academy_id, title="반 없는 학생 작품")
    photo = (await _upload(client, storage, s1, linked["id"])).json()
    staff = f"{world.base}/artworks"

    listing = await client.get(staff, headers=world.teacher.headers)
    assert [a["title"] for a in listing.json()["items"]] == ["학원 작품"]
    assert listing.json()["items"][0]["student"]["membership_id"] == s1.membership_id
    owner_listing = await client.get(staff, headers=world.owner.headers)
    assert {a["title"] for a in owner_listing.json()["items"]} == {"학원 작품", "반 없는 학생 작품"}

    detail = await client.get(
        f"{staff}/{linked['id']}?include_urls=true", headers=world.teacher.headers
    )
    assert detail.status_code == 200
    assert detail.json()["photos"][0]["url"]
    # 강사 토큰으로 Signed URL 발급 (Storage RLS가 강사 권한을 다시 검사)
    assert storage.calls[-1][2] == world.teacher.headers["Authorization"].removeprefix("Bearer ")
    url = await client.get(
        f"{staff}/{linked['id']}/photos/{photo['id']}/url", headers=world.teacher.headers
    )
    assert url.status_code == 200

    # 비담당 학생 작품 403, 개인 작품 404, 비담당 강사 403
    assert (
        await client.get(f"{staff}/{not_managed['id']}", headers=world.teacher.headers)
    ).status_code == 403
    assert (
        await client.get(f"{staff}/{personal['id']}", headers=world.teacher.headers)
    ).status_code == 404
    assert (
        await client.get(f"{staff}/{linked['id']}", headers=world.other_teacher.headers)
    ).status_code == 403
    filtered = await client.get(
        f"{staff}?student_membership_id={s3.membership_id}", headers=world.teacher.headers
    )
    assert filtered.status_code == 403

    # 다른 학원 원장: 404
    other_world = await build_world("다른 학원", admin=world.admin)
    cross = await client.get(
        f"{other_world.base}/artworks/{linked['id']}", headers=other_world.owner.headers
    )
    assert cross.status_code == 404

    # 학생이 학원을 떠나면 강사도 더 이상 볼 수 없다
    await client.delete(f"{world.base}/members/me", headers=s1.headers)
    assert (
        await client.get(f"{staff}/{linked['id']}", headers=world.teacher.headers)
    ).status_code in (403, 404)
