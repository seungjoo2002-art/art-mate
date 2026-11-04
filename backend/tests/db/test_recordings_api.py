"""피드백 녹음 (F-11): 동의, 업로드·완료, 오디오 검증, 중복, Storage 실패, 접근 권한, 삭제 정리."""

import asyncio

import httpx
import pytest

from tests.db.conftest import Actor, World
from tests.fake_storage import FakeStorage, audio_bytes

VERSION = "2026-11-v1"


@pytest.fixture
def audio(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.audio_storage


async def _consent(client: httpx.AsyncClient, student: Actor, **body) -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.post(
        "/api/v1/recording-consents",
        json={"policy_version": VERSION, "agreed": True} | body,
        headers=student.headers,
    )


async def _artwork(client: httpx.AsyncClient, student: Actor, **body) -> str:  # type: ignore[no-untyped-def]
    created = await client.post(
        "/api/v1/artworks", json={"title": "녹음 작품"} | body, headers=student.headers
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _ticket_body(data: bytes, content_type: str = "audio/webm;codecs=opus", **extra) -> dict:  # type: ignore[no-untyped-def]
    return {
        "content_type": content_type,
        "file_size": len(data),
        "duration_ms": 42_000,
        "speaker_notice_confirmed": True,
    } | extra


async def _record(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient,
    audio: FakeStorage,
    student: Actor,
    artwork_id: str,
    data: bytes | None = None,
    content_type: str = "audio/webm;codecs=opus",
    **extra,
) -> httpx.Response:
    payload = data if data is not None else audio_bytes("webm")
    base = f"/api/v1/artworks/{artwork_id}/recordings"
    ticket = await client.post(
        base, json=_ticket_body(payload, content_type, **extra), headers=student.headers
    )
    assert ticket.status_code == 201, ticket.text
    audio.put(ticket.json()["upload"]["path"], payload)
    return await client.post(
        f"{base}/{ticket.json()['recording']['id']}/complete", headers=student.headers
    )


# ----------------------------------------------------------------------------- consent


async def test_consent_required_and_recorded(client: httpx.AsyncClient, actors, audio) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    artwork_id = await _artwork(client, student)
    base = f"/api/v1/artworks/{artwork_id}/recordings"

    status = (await client.get("/api/v1/recording-consents/me", headers=student.headers)).json()
    assert status == {"required_version": VERSION, "is_valid": False, "consent": None}
    no_consent = await client.post(base, json=_ticket_body(audio_bytes()), headers=student.headers)
    assert no_consent.status_code == 409
    assert no_consent.json()["error"]["code"] == "RECORDING_CONSENT_REQUIRED"
    assert no_consent.json()["error"]["details"]["required_version"] == VERSION

    # 잘못된 버전·동의하지 않음 → 422
    assert (await _consent(client, student, policy_version="old")).status_code == 422
    assert (await _consent(client, student, agreed=False)).status_code == 422

    granted = await _consent(client, student, granted_by="GUARDIAN")
    assert granted.status_code == 201
    body = granted.json()
    assert body["is_valid"] is True and body["consent"]["granted_by"] == "GUARDIAN"
    # 같은 동의 재요청은 그대로 (멱등)
    again = await _consent(client, student, granted_by="GUARDIAN")
    assert again.json()["consent"]["id"] == body["consent"]["id"]

    recorded = await _record(client, audio, student, artwork_id)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["consent_id"] == body["consent"]["id"]
    assert recorded.json()["speaker_notice_confirmed"] is True

    # 강사 고지 확인 없이 업로드 요청 불가
    no_notice = await client.post(
        base,
        json=_ticket_body(audio_bytes(), speaker_notice_confirmed=False),
        headers=student.headers,
    )
    assert no_notice.status_code == 422

    # 동의 철회 → 새 녹음 불가, 기존 녹음은 유지
    assert (
        await client.delete("/api/v1/recording-consents/me", headers=student.headers)
    ).status_code == 204
    blocked = await client.post(base, json=_ticket_body(audio_bytes()), headers=student.headers)
    assert blocked.json()["error"]["code"] == "RECORDING_CONSENT_REQUIRED"
    assert len((await client.get(base, headers=student.headers)).json()) == 1
    assert (
        await client.delete("/api/v1/recording-consents/me", headers=student.headers)
    ).status_code == 404

    # 강사 계정은 녹음 동의·업로드 API를 쓸 수 없다
    teacher = await actors.signup("INSTRUCTOR")
    assert (await _consent(client, teacher)).status_code == 403


async def test_concurrent_consents_keep_one_active(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    responses = await asyncio.gather(*[_consent(client, student) for _ in range(4)])
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["consent"]["id"] for r in responses}) == 1


# ----------------------------------------------------------------------------- upload


async def test_upload_complete_and_playback(client: httpx.AsyncClient, actors, audio) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await _consent(client, student)
    artwork_id = await _artwork(client, student)
    base = f"/api/v1/artworks/{artwork_id}/recordings"
    data = audio_bytes("webm")

    ticket = await client.post(
        base,
        json=_ticket_body(
            data, file_name="첨삭.webm", title="명암 첨삭", recorded_at="2026-11-04T16:30:00+09:00"
        ),
        headers=student.headers,
    )
    assert ticket.status_code == 201, ticket.text
    recording = ticket.json()["recording"]
    upload = ticket.json()["upload"]
    assert upload["bucket"] == "feedback-audio"
    assert upload["path"] == f"{student.user_id}/{artwork_id}/{recording['id']}.webm"
    assert recording["status"] == "PENDING" and recording["content_type"] == "audio/webm"
    assert recording["transcription_status"] == "NOT_REQUESTED"
    # 사용자 토큰으로 Storage 호출
    assert audio.calls[-1][2] == student.headers["Authorization"].removeprefix("Bearer ")

    complete = f"{base}/{recording['id']}/complete"
    early = await client.post(complete, headers=student.headers)
    assert early.status_code == 409 and early.json()["error"]["code"] == "UPLOAD_NOT_FOUND"
    audio.put(upload["path"], data)
    done = await client.post(complete, headers=student.headers)
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "ACTIVE" and body["size_bytes"] == len(data)
    assert body["duration_ms"] == 42_000 and body["title"] == "명암 첨삭"
    assert (await client.post(complete, headers=student.headers)).json() == body  # 멱등

    listing = (await client.get(f"{base}?include_urls=true", headers=student.headers)).json()
    assert [r["id"] for r in listing] == [recording["id"]]
    assert listing[0]["url"].startswith("https://storage.test/object/sign/feedback-audio/")
    detail = await client.get(f"{base}/{recording['id']}", headers=student.headers)
    assert detail.json()["id"] == recording["id"]
    url = await client.get(f"{base}/{recording['id']}/url", headers=student.headers)
    assert url.status_code == 200 and url.json()["expires_at"]

    # WAV는 서버가 길이를 계산해 보정 (클라이언트 42초 → 실제 1초)
    wav = await _record(client, audio, student, artwork_id, audio_bytes("wav"), "audio/wav")
    assert wav.json()["duration_ms"] == 1000

    # 삭제 → Storage 정리
    path = upload["path"]
    assert (
        await client.delete(f"{base}/{recording['id']}", headers=student.headers)
    ).status_code == 204
    assert path not in audio.objects
    assert (
        await client.get(f"{base}/{recording['id']}", headers=student.headers)
    ).status_code == 404


async def test_invalid_audio_is_rejected(client: httpx.AsyncClient, actors, audio) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await _consent(client, student)
    artwork_id = await _artwork(client, student)
    base = f"/api/v1/artworks/{artwork_id}/recordings"

    for body, code in (
        (_ticket_body(b"x", "video/webm"), "UNSUPPORTED_FILE_TYPE"),
        (_ticket_body(b"x", file_name="voice.mp3"), "UNSUPPORTED_FILE_TYPE"),
        (_ticket_body(b"x", file_size=200 * 1024 * 1024), "FILE_TOO_LARGE"),
        (_ticket_body(b"x", duration_ms=3 * 3600 * 1000), "AUDIO_TOO_LONG"),
    ):
        response = await client.post(base, json=body, headers=student.headers)
        assert response.status_code == 422, body
        assert response.json()["error"]["code"] == code

    for data, content_type in (
        (b"<html><script>alert(1)</script></html>" * 3, "audio/webm"),
        (audio_bytes("ogg"), "audio/webm"),  # 선언과 실제 형식 불일치
    ):
        rejected = await _record(client, audio, student, artwork_id, data, content_type)
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "INVALID_AUDIO"
    assert audio.objects == {}
    assert (await client.get(base, headers=student.headers)).json() == []


async def test_duplicate_and_storage_failures(client: httpx.AsyncClient, actors, audio) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await _consent(client, student)
    artwork_id = await _artwork(client, student)
    base = f"/api/v1/artworks/{artwork_id}/recordings"
    data = audio_bytes("mp4")

    assert (await _record(client, audio, student, artwork_id, data, "audio/mp4")).status_code == 200
    duplicate = await _record(client, audio, student, artwork_id, data, "audio/mp4")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RECORDING"
    assert len(audio.objects) == 1

    # 업로드 URL 발급 실패 → 503, 행 남지 않음
    audio.fail = {"upload_url"}
    failed = await client.post(base, json=_ticket_body(data), headers=student.headers)
    assert failed.status_code == 503
    audio.fail = set()

    # 완료 처리 중 다운로드 실패 → 503, 재시도 성공
    other = audio_bytes("ogg")
    ticket = await client.post(base, json=_ticket_body(other, "audio/ogg"), headers=student.headers)
    audio.put(ticket.json()["upload"]["path"], other)
    complete = f"{base}/{ticket.json()['recording']['id']}/complete"
    audio.fail = {"download"}
    assert (await client.post(complete, headers=student.headers)).status_code == 503
    audio.fail = set()
    assert (await client.post(complete, headers=student.headers)).json()["status"] == "ACTIVE"

    # 삭제 시 Storage 실패 → DB는 삭제, 파일은 다음 요청에서 정리
    audio.fail = {"delete"}
    rid = ticket.json()["recording"]["id"]
    assert (await client.delete(f"{base}/{rid}", headers=student.headers)).status_code == 204
    assert other in audio.objects.values()
    audio.fail = set()
    await client.post(base, json=_ticket_body(audio_bytes()), headers=student.headers)
    assert other not in audio.objects.values()

    # 재생 URL 발급 실패 → 503
    first = (await client.get(base, headers=student.headers)).json()[0]
    audio.fail = {"sign"}
    assert (
        await client.get(f"{base}/{first['id']}/url", headers=student.headers)
    ).status_code == 503
    audio.fail = set()


async def test_deleting_artwork_cleans_recordings(client: httpx.AsyncClient, actors, audio) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await _consent(client, student)
    artwork_id = await _artwork(client, student)
    await _record(client, audio, student, artwork_id)
    assert len(audio.objects) == 1
    assert (
        await client.delete(f"/api/v1/artworks/{artwork_id}", headers=student.headers)
    ).status_code == 204
    assert audio.objects == {}


# ----------------------------------------------------------------------------- access


async def test_recording_access_control(
    client: httpx.AsyncClient, world: World, audio, build_world
) -> None:  # type: ignore[no-untyped-def]
    s1, s2, s3 = world.students  # s3: 반 미배정
    for student in (s1, s3):
        await _consent(client, student)
    academy_art = await _artwork(client, s1, academy_id=world.academy_id)
    personal_art = await _artwork(client, s1)
    unmanaged_art = await _artwork(client, s3, academy_id=world.academy_id)
    rec = (await _record(client, audio, s1, academy_art)).json()
    personal_rec = (await _record(client, audio, s1, personal_art)).json()
    unmanaged_rec = (await _record(client, audio, s3, unmanaged_art)).json()

    # 다른 학생: 전부 404
    for path in (
        f"/api/v1/artworks/{academy_art}/recordings",
        f"/api/v1/artworks/{academy_art}/recordings/{rec['id']}",
        f"/api/v1/artworks/{academy_art}/recordings/{rec['id']}/url",
    ):
        assert (await client.get(path, headers=s2.headers)).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/artworks/{academy_art}/recordings/{rec['id']}", headers=s2.headers
        )
    ).status_code == 404

    staff = f"{world.base}/artworks"
    # 담당 강사: 학원 연결 작품 녹음 조회·재생 가능 (강사 토큰으로 서명)
    listing = await client.get(
        f"{staff}/{academy_art}/recordings?include_urls=true", headers=world.teacher.headers
    )
    assert listing.status_code == 200 and listing.json()[0]["url"]
    assert audio.calls[-1][2] == world.teacher.headers["Authorization"].removeprefix("Bearer ")
    meta = await client.get(
        f"{staff}/{academy_art}/recordings/{rec['id']}", headers=world.teacher.headers
    )
    assert meta.json()["duration_ms"] == 42_000
    assert (
        await client.get(
            f"{staff}/{academy_art}/recordings/{rec['id']}/url", headers=world.teacher.headers
        )
    ).status_code == 200

    # 개인 작품 녹음: 404, 비담당 학생: 403, 비담당 강사: 403, 원장: 학원 전체 가능
    assert (
        await client.get(f"{staff}/{personal_art}/recordings", headers=world.teacher.headers)
    ).status_code == 404
    assert (
        await client.get(
            f"{staff}/{personal_art}/recordings/{personal_rec['id']}/url",
            headers=world.owner.headers,
        )
    ).status_code == 404
    assert (
        await client.get(f"{staff}/{unmanaged_art}/recordings", headers=world.teacher.headers)
    ).status_code == 403
    assert (
        await client.get(f"{staff}/{academy_art}/recordings", headers=world.other_teacher.headers)
    ).status_code == 403
    owner_view = await client.get(
        f"{staff}/{unmanaged_art}/recordings/{unmanaged_rec['id']}", headers=world.owner.headers
    )
    assert owner_view.status_code == 200
    # 학생은 강사용 녹음 API를 쓸 수 없다
    assert (
        await client.get(f"{staff}/{academy_art}/recordings", headers=s1.headers)
    ).status_code == 403

    # 다른 학원: 404
    other = await build_world("다른 미술학원", admin=world.admin)
    cross = await client.get(
        f"{other.base}/artworks/{academy_art}/recordings", headers=other.owner.headers
    )
    assert cross.status_code == 404
