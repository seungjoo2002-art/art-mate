"""휴대폰 사진 업로드 호환: 비표준 MIME(image/jpg)·대문자 확장자, 변환 안 된 HEIC 거부."""

from __future__ import annotations

import httpx
import pytest

from tests.db.conftest import Actor
from tests.db.test_v098_timeline_refs import _artwork
from tests.fake_storage import FakeStorage, image_bytes

API = "/api/v1"


async def _upload(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, storage: FakeStorage, owner: Actor, url: str, body: dict, data: bytes
) -> httpx.Response:
    ticket = await client.post(url, json=body | {"file_size": len(data)}, headers=owner.headers)
    assert ticket.status_code == 201, ticket.text
    storage.put(ticket.json()["upload"]["path"], data)
    photo_id = ticket.json()["photo"]["id"]
    return await client.post(f"{url}/{photo_id}/complete", headers=owner.headers)


@pytest.mark.parametrize("kind", ["photos", "reference-photos"])
async def test_jpeg_alias_and_uppercase_name_upload(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, kind: str
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    body = {"content_type": "image/jpg", "file_name": "IMG_0001.JPG"}
    if kind == "photos":
        body["stage_id"] = artwork["stage_plan"][0]["id"]
    done = await _upload(
        client,
        storage,
        student,
        f"{API}/artworks/{artwork['id']}/{kind}",
        body,
        image_bytes("JPEG", (30, 60), color="teal"),
    )
    assert done.status_code == 200, done.text
    assert done.json()["content_type"] == "image/jpeg"
    assert done.json()["width"] == 30 and done.json()["height"] == 60


async def test_unconverted_heic_is_rejected_with_type_error(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 200
    done = await _upload(
        client,
        storage,
        student,
        f"{API}/artworks/{artwork['id']}/photos",
        {
            "stage_id": artwork["stage_plan"][0]["id"],
            "content_type": "image/jpeg",
            "file_name": "renamed.jpg",
        },
        heic,
    )
    assert done.status_code == 422
    assert done.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    # 거부된 업로드는 남지 않음
    detail = (await client.get(f"{API}/artworks/{artwork['id']}", headers=student.headers)).json()
    assert detail["photos"] == []
