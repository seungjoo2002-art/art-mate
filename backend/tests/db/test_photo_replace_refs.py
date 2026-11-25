"""단계 사진 교체 (아카이브 상세 사진 교체 버튼).

- 교체 사진은 교체 전 사진의 단계·등록 순서(uploaded_at)·대표 여부를 이어받는다
- 교체 전 사진을 기준 사진으로 삼은 피드백은 연결이 그대로 남고, 파일도 남아 계속 볼 수 있다
  (image_refs: replaced=true, current_photo_id=교체한 사진)
- 피드백 기준 사진이 아니었으면 예전처럼 파일을 지운다
- 작품을 지우면 남겨 둔 파일도 정리
"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from tests.db.conftest import Actor
from tests.db.test_v098_timeline_refs import _artwork, _note, _photo, _ref_ids
from tests.fake_storage import FakeStorage, image_bytes

API = "/api/v1"


async def _replace(  # type: ignore[no-untyped-def]
    client, storage: FakeStorage, owner: Actor, artwork_id: str, target: dict, color: str
) -> dict:
    payload = image_bytes("PNG", color=color, size=(77, 31))
    ticket = await client.post(
        f"{API}/artworks/{artwork_id}/photos",
        json={
            "stage_id": target["stage_id"],
            "content_type": "image/png",
            "file_size": len(payload),
            "replaces_photo_id": target["id"],
        },
        headers=owner.headers,
    )
    assert ticket.status_code == 201, ticket.text
    storage.put(ticket.json()["upload"]["path"], payload)
    done = await client.post(
        f"{API}/artworks/{artwork_id}/photos/{ticket.json()['photo']['id']}/complete",
        headers=owner.headers,
    )
    assert done.status_code == 200, done.text
    return done.json()


async def test_replace_keeps_order_and_feedback_reference(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    sketch = artwork["stage_plan"][0]
    first = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    second = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    note = await _note(
        client,
        student,
        artwork["id"],
        stage_id=sketch["id"],
        reference_photo_ids=[first["id"]],
        reference_confirmed=True,
    )
    first_path = next(path for path in storage.objects if first["id"] in path)

    new = await _replace(client, storage, student, artwork["id"], first, "orange")
    # 등록 순서·대표 이어받음
    assert new["uploaded_at"] == first["uploaded_at"]
    assert new["is_representative"] is True and new["stage_id"] == sketch["id"]
    detail = (await client.get(f"{API}/artworks/{artwork['id']}", headers=student.headers)).json()
    ids = [p["id"] for p in detail["photos"]]
    assert ids == [new["id"], second["id"]]

    # 피드백 기준 사진은 교체 전 사진 그대로, 파일도 남아 URL을 받을 수 있음
    assert first_path in storage.objects
    read = (await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)).json()
    assert _ref_ids(read["image_refs"]) == [first["id"]]
    ref = read["image_refs"]["photos"][0]
    assert ref["photo_status"] == "DELETED"
    assert ref["replaced"] is True and ref["current_photo_id"] == new["id"]
    url = await client.get(
        f"{API}/artworks/{artwork['id']}/photos/{first['id']}/url", headers=student.headers
    )
    assert url.status_code == 200, url.text

    # 기준 사진이 아닌 사진 교체 → 파일 삭제 (예전과 같음)
    second_path = next(path for path in storage.objects if second["id"] in path)
    await _replace(client, storage, student, artwork["id"], second, "purple")
    assert second_path not in storage.objects
    gone = await client.get(
        f"{API}/artworks/{artwork['id']}/photos/{second['id']}/url", headers=student.headers
    )
    assert gone.status_code == 404

    # 작품 삭제 → 남겨 둔 파일도 정리
    deleted = await client.delete(f"{API}/artworks/{artwork['id']}", headers=student.headers)
    assert deleted.status_code == 204
    assert first_path not in storage.objects


async def test_legacy_manual_representative_is_ignored_everywhere(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    """예전에 직접 고른 대표(DB is_representative)가 첫 사진이 아니어도, 데이터를 고치지 않고
    목록·상세·단계 요약 모두 단계에서 가장 먼저 등록한 사진을 대표로."""
    storage: FakeStorage = app.state.storage
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    sketch, _, final = artwork["stage_plan"]
    s1 = await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])
    f1 = await _photo(client, storage, student, artwork["id"], stage_id=final["id"])
    f2 = await _photo(client, storage, student, artwork["id"], stage_id=final["id"])
    # 예전 데이터 재현: 완성 단계에서 두 번째 사진을 직접 대표로 지정해 둔 상태
    async with app.state.database.engine.begin() as conn:
        await conn.execute(
            text("UPDATE artwork_photos SET is_representative = (id = :f2) WHERE stage_id = :st"),
            {"f2": f2["id"], "st": final["id"]},
        )

    detail = (await client.get(f"{API}/artworks/{artwork['id']}", headers=student.headers)).json()
    listed = (await client.get(f"{API}/artworks", headers=student.headers)).json()
    item = next(a for a in listed["items"] if a["id"] == artwork["id"])
    # 작품 썸네일: 단계 우선순위 그대로(가장 늦은 단계) + 그 단계 첫 사진
    assert detail["cover_photo_id"] == item["cover_photo_id"] == f1["id"]
    reps = {p["stage_id"]: p["id"] for p in detail["photos"] if p["is_representative"]}
    assert reps == {sketch["id"]: s1["id"], final["id"]: f1["id"]}
    # DB 값은 그대로 (일괄 수정 없음)
    async with app.state.database.engine.begin() as conn:
        flagged = (
            await conn.execute(
                text("SELECT id FROM artwork_photos WHERE stage_id = :st AND is_representative"),
                {"st": final["id"]},
            )
        ).scalar_one()
    assert str(flagged) == f2["id"]
