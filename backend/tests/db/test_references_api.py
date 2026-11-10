"""v0.8 F-15 참고작: 강사 우수 사례 확인, 추천 조건·근거, 동의·범위, 철회, 저장, 권한."""

import asyncio

import httpx
import pytest

from tests.db.conftest import Actor, World
from tests.db.test_community_api import _final_artwork, _share
from tests.db.test_growth_api import _artwork, _exec, _seed_feedback
from tests.fake_storage import FakeStorage

API = "/api/v1"


@pytest.fixture
def photos(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.storage


async def _make_learner(client, app, actors, *, practical: str = "BASIC_DESIGN") -> Actor:  # type: ignore[no-untyped-def]
    learner = await actors.signup("STUDENT")
    await client.patch(
        f"{API}/users/me", json={"practical_type": practical}, headers=learner.headers
    )
    for day, cats in enumerate(
        [["PROPORTION", "VALUE"], ["PROPORTION"], ["PROPORTION", "VALUE"], ["COLOR"]], start=1
    ):
        artwork = await _artwork(
            client, learner, day, practical_type=practical, work_category="MOCK_EXAM"
        )
        await _seed_feedback(app, learner, artwork, cats)
    return learner


async def _review(
    client, world: World, artwork_id: str, category: str, actor: Actor | None = None
) -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.post(
        f"{world.base}/references/reviews",
        json={
            "artwork_id": artwork_id,
            "category": category,
            "note": "기준선으로 비율을 잡은 방식 참고",
        },
        headers=(actor or world.teacher).headers,
    )


async def test_reference_recommendation_flow(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, photos: FakeStorage, app, actors
) -> None:
    learner = await _make_learner(client, app, actors)
    s1, s2 = world.students[0], world.students[1]

    # 아직 새로고침 전
    empty = (await client.get(f"{API}/references/me", headers=learner.headers)).json()
    assert empty["status"] == "NOT_GENERATED" and empty["items"] == []

    exemplar = await _final_artwork(client, photos, s1, "비례 우수작", academy_id=world.academy_id)
    created = await _review(client, world, exemplar, "PROPORTION")
    assert created.status_code == 201, created.text
    assert created.json()["reference_consent"] is None  # 아직 학생 동의 없음
    assert (await _review(client, world, exemplar, "PROPORTION")).json()["error"][
        "code"
    ] == "REFERENCE_REVIEW_EXISTS"

    # 강사 확인만 있고 원작자 동의 없음 → 추천 없음 (명확히)
    no_consent = (await client.post(f"{API}/references/me/refresh", headers=learner.headers)).json()
    assert no_consent["status"] == "NO_VERIFIED_REFERENCES" and no_consent["items"] == []
    assert no_consent["weaknesses"] == ["PROPORTION", "VALUE"]
    assert no_consent["message"]

    # 같은 카테고리지만 강사 확인이 없는 작품, 학생 약점이 아닌 카테고리 확인 → 제외
    unverified = await _final_artwork(
        client, photos, s2, "확인 안 된 작품", academy_id=world.academy_id
    )
    await _share(client, s2, unverified, purpose="REFERENCE")
    other_category = await _final_artwork(
        client, photos, s2, "색채 우수작", academy_id=world.academy_id
    )
    await _share(client, s2, other_category, purpose="REFERENCE")
    assert (await _review(client, world, other_category, "TEXTURE")).status_code == 201

    granted = await _share(client, s1, exemplar, purpose="REFERENCE", author_display="ANONYMOUS")
    assert granted.status_code == 200
    result = (await client.post(f"{API}/references/me/refresh", headers=learner.headers)).json()
    assert result["status"] == "READY" and result["refreshed"] is True
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert (item["weakness_category"], item["weakness_rank"], item["rank"]) == ("PROPORTION", 1, 1)
    assert [r["code"] for r in item["reasons"]] == [
        "VERIFIED_EXEMPLAR",
        "MATCHES_WEAKNESS",
        "SAME_PRACTICAL_TYPE",
        "SAME_WORK_CATEGORY",
    ]
    assert item["reasons"][0]["message"] == "'비례' 표현의 참고 사례로 강사가 확인한 작품입니다."
    assert item["reasons"][2]["message"] == "현재 연습 중인 '기초디자인' 유형과 일치합니다."
    assert item["reference_point"] == "기준선으로 비율을 잡은 방식 참고"
    assert item["author"] == {"display_name": "익명 학생", "is_anonymous": True, "is_me": False}
    assert item["image"]["url"].startswith("https://storage.test/object/sign/shared-artworks/")
    assert item["community_post_id"] is None and item["saved"] is False
    # 원작자 작품 ID·제목·학원·원본 URL은 응답에 없음
    text = str(result)
    assert exemplar not in text and "비례 우수작" not in text and "object/sign/artworks" not in text

    # 같은 입력이면 다시 만들지 않음
    again = (await client.post(f"{API}/references/me/refresh", headers=learner.headers)).json()
    assert again["refreshed"] is False and again["items"][0]["id"] == item["id"]
    by_category = (
        await client.get(f"{API}/references/me?category=VALUE", headers=learner.headers)
    ).json()
    assert by_category["items"] == []

    # 상세·저장
    detail = await client.get(f"{API}/references/me/{item['id']}", headers=learner.headers)
    assert detail.status_code == 200
    saved = await client.put(f"{API}/references/me/{item['id']}/save", headers=learner.headers)
    assert saved.json()["saved"] is True
    assert [
        i["id"]
        for i in (await client.get(f"{API}/references/me/saved", headers=learner.headers)).json()
    ] == [item["id"]]
    # 다른 학생은 남의 추천 항목에 접근 불가
    assert (
        await client.get(f"{API}/references/me/{item['id']}", headers=s2.headers)
    ).status_code == 404

    # 원작자 철회 → 추천·저장 목록에서 즉시 빠짐
    await client.delete(f"{API}/artworks/{exemplar}/sharing/REFERENCE", headers=s1.headers)
    after = (await client.get(f"{API}/references/me", headers=learner.headers)).json()
    assert after["items"] == []
    assert (await client.get(f"{API}/references/me/saved", headers=learner.headers)).json() == []
    assert (
        await client.get(f"{API}/references/me/{item['id']}", headers=learner.headers)
    ).status_code == 404


async def test_reference_scope_and_review_revocation(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, photos: FakeStorage, app, actors
) -> None:
    outsider = await _make_learner(client, app, actors)  # 학원 없음
    insider = world.students[2]  # 같은 학원 (반 미배정)
    for day, cats in enumerate([["PROPORTION"], ["PROPORTION"], ["PROPORTION", "VALUE"]], start=1):
        await _seed_feedback(app, insider, await _artwork(client, insider, day), cats)

    s1 = world.students[0]
    exemplar = await _final_artwork(
        client, photos, s1, "학원 공개 우수작", academy_id=world.academy_id
    )
    await _share(client, s1, exemplar, purpose="REFERENCE", scope="ACADEMY", author_display="NAME")
    review = (await _review(client, world, exemplar, "PROPORTION")).json()
    assert review["reference_consent"]["scope"] == "ACADEMY"

    # ACADEMY 범위: 같은 학원 학생만
    inside = (await client.post(f"{API}/references/me/refresh", headers=insider.headers)).json()
    assert inside["status"] == "READY"
    assert inside["items"][0]["author"]["display_name"].endswith("학생1")
    outside = (await client.post(f"{API}/references/me/refresh", headers=outsider.headers)).json()
    assert outside["status"] == "NO_VERIFIED_REFERENCES"
    # 본인 작품은 추천하지 않음
    for day, cats in enumerate([["PROPORTION"], ["PROPORTION"], ["PROPORTION"]], start=10):
        await _seed_feedback(app, s1, await _artwork(client, s1, day), cats)
    own = (await client.post(f"{API}/references/me/refresh", headers=s1.headers)).json()
    assert own["status"] == "NO_VERIFIED_REFERENCES"

    # 강사 확인 해제 → 근거가 사라진 추천은 제거
    revoked = await client.delete(
        f"{world.base}/references/reviews/{review['id']}", headers=world.teacher.headers
    )
    assert revoked.json()["status"] == "REVOKED"
    assert (await client.get(f"{API}/references/me", headers=insider.headers)).json()["items"] == []
    listing = (
        await client.get(f"{world.base}/references/reviews", headers=world.teacher.headers)
    ).json()
    assert listing["total"] == 0
    revoked_list = (
        await client.get(
            f"{world.base}/references/reviews?status=REVOKED", headers=world.teacher.headers
        )
    ).json()
    assert revoked_list["total"] == 1


async def test_no_repeated_weakness(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await _seed_feedback(app, student, await _artwork(client, student, 1), ["VALUE"])
    result = (await client.post(f"{API}/references/me/refresh", headers=student.headers)).json()
    assert result["status"] == "NO_REPEATED_WEAKNESS" and result["items"] == []


async def test_review_permissions_and_candidates(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, photos: FakeStorage, app, build_world
) -> None:
    s1, s3 = world.students[0], world.students[2]  # s3은 반 미배정 (담당 아님)
    linked = await _final_artwork(client, photos, s1, "학원 작품", academy_id=world.academy_id)
    personal = await _final_artwork(client, photos, s1, "개인 작품")
    unmanaged = await _final_artwork(client, photos, s3, "비담당 학생", academy_id=world.academy_id)
    assert (await _review(client, world, personal, "PROPORTION")).status_code == 404
    assert (await _review(client, world, unmanaged, "PROPORTION")).status_code == 403
    assert (
        await _review(client, world, linked, "PROPORTION", world.other_teacher)
    ).status_code == 403
    assert (await _review(client, world, linked, "PROPORTION", s1)).status_code == 403  # 학생 불가
    other = await build_world("다른 학원", admin=world.admin)
    cross = await client.post(
        f"{other.base}/references/reviews",
        json={"artwork_id": linked, "category": "PROPORTION", "note": "x"},
        headers=other.owner.headers,
    )
    assert cross.status_code == 404
    no_final = await _artwork(client, s1, 20, academy_id=world.academy_id)
    assert (await _review(client, world, no_final, "PROPORTION")).json()["error"][
        "code"
    ] == "FINAL_PHOTO_REQUIRED"
    # 원장(학원 관리자)은 비담당 학생 작품도 확인 가능
    assert (await _review(client, world, unmanaged, "FORM", world.owner)).status_code == 201

    # 후보: 승인된 첨삭에서 '잘한 점'으로 언급된 카테고리
    await _seed_feedback(app, s1, linked, ["VALUE"], strengths=("PROPORTION",))
    await _seed_feedback(app, s1, personal, ["VALUE"], strengths=("PROPORTION",))
    candidates = (
        await client.get(
            f"{world.base}/references/candidates?category=PROPORTION", headers=world.teacher.headers
        )
    ).json()
    assert [c["artwork_id"] for c in candidates] == [linked]  # 개인 작품 제외
    assert candidates[0]["strength_texts"] == ["STRENGTH PROPORTION 문장"]
    assert (
        candidates[0]["already_reviewed"] is False
        and candidates[0]["has_reference_consent"] is False
    )


async def test_concurrent_refresh_keeps_one_active_set(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, photos: FakeStorage, app, actors
) -> None:
    learner = await _make_learner(client, app, actors)
    exemplar = await _final_artwork(client, photos, world.students[0], academy_id=world.academy_id)
    await _share(client, world.students[0], exemplar, purpose="REFERENCE")
    await _review(client, world, exemplar, "PROPORTION")
    results = await asyncio.gather(
        *[client.post(f"{API}/references/me/refresh", headers=learner.headers) for _ in range(4)]
    )
    assert all(r.status_code == 200 for r in results)
    rows = await _exec(
        app,
        "SELECT count(*) FROM reference_recommendations WHERE owner_id = :u AND status = 'ACTIVE'",
        u=str(learner.user_id),
    )
    assert rows[0][0] == 1
