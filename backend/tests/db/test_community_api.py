"""v0.8 작품 공유 동의·공유 이미지·커뮤니티(게시물·좋아요·저장·댓글·신고·관리)."""

import asyncio
import io

import httpx
import pytest
from PIL import Image

from tests.db.conftest import Actor, World
from tests.db.test_artworks_api import _upload
from tests.fake_storage import FakeStorage

API = "/api/v1"
VERSION = "2026-11-share-v1"


@pytest.fixture
def photos(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.storage


@pytest.fixture
def shared(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.shared_storage


async def _final_artwork(client, photos, owner: Actor, title="정물 완성작", **body) -> str:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks",
        json={"title": title, "practical_type": "BASIC_DESIGN", "work_category": "MOCK_EXAM"}
        | body,
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    artwork_id = created.json()["id"]
    uploaded = await _upload(client, photos, owner, artwork_id, "FINAL")
    assert uploaded.status_code == 200, uploaded.text
    return artwork_id


async def _share(
    client, owner: Actor, artwork_id: str, purpose="COMMUNITY", **body
) -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.put(
        f"{API}/artworks/{artwork_id}/sharing/{purpose}",
        json={"scope": "PLATFORM", "policy_version": VERSION, "agreed": True} | body,
        headers=owner.headers,
    )


async def _post(client, owner: Actor, artwork_id: str, **body) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/community/posts",
        json={"artwork_id": artwork_id, "title": "첫 기초디자인"} | body,
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


# ============================================================================ 공유 동의·이미지


async def test_sharing_consent_and_derived_image(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, photos: FakeStorage, shared: FakeStorage
) -> None:
    student = await actors.signup("STUDENT", name="김작가")
    bare = (
        await client.post(f"{API}/artworks", json={"title": "스케치만"}, headers=student.headers)
    ).json()["id"]
    no_final = await _share(client, student, bare)
    assert no_final.json()["error"]["code"] == "FINAL_PHOTO_REQUIRED"

    artwork_id = await _final_artwork(client, photos, student)
    wrong = await _share(client, student, artwork_id, policy_version="old")
    assert wrong.status_code == 422
    academy_scope = await _share(client, student, artwork_id, scope="ACADEMY")
    assert academy_scope.json()["error"]["code"] == "SHARING_SCOPE_INVALID"  # 개인 작품

    granted = await _share(client, student, artwork_id, author_display="NAME")
    assert granted.status_code == 200, granted.text
    body = granted.json()
    assert body["community"]["scope"] == "PLATFORM" and body["reference"] is None
    image = body["image"]
    assert image["url"].startswith("https://storage.test/object/sign/shared-artworks/")
    # 파생 이미지: 별도 버킷, JPEG, 원본 경로·원본 버킷 URL 미노출
    path = next(iter(shared.objects))
    # 경로에 사용자·작품 ID 없음 (익명 공개 시 URL로 작성자 식별 방지)
    assert str(student.user_id) not in path and artwork_id not in path and path.endswith(".jpg")
    assert student.user_id.hex not in path
    assert Image.open(io.BytesIO(shared.objects[path])).format == "JPEG"
    assert "/artworks/" not in image["url"].split("shared-artworks")[1]
    assert not any("object/sign/artworks/" in str(v) for v in body.values())
    assert shared.calls[-1][2] == student.headers["Authorization"].removeprefix("Bearer ")

    # 같은 동의 재요청: 변경 없음 / 범위·표시 변경: 이전 동의 CHANGED + 새 동의 (이력)
    await _share(client, student, artwork_id, author_display="NAME")
    await _share(client, student, artwork_id, author_display="ANONYMOUS")
    reference = await _share(client, student, artwork_id, purpose="REFERENCE")
    assert reference.json()["reference"]["purpose"] == "REFERENCE"
    assert len(shared.objects) == 1  # 이미지는 작품당 1개
    history = (
        await client.get(f"{API}/artworks/{artwork_id}/sharing/history", headers=student.headers)
    ).json()
    assert [(h["purpose"], h["revoked_reason"]) for h in history] == [
        ("COMMUNITY", "CHANGED"),
        ("COMMUNITY", None),
        ("REFERENCE", None),
    ]

    # 다른 학생은 남의 작품 공유 설정 불가
    other = await actors.signup("STUDENT")
    assert (await _share(client, other, artwork_id)).status_code == 404
    assert (
        await client.get(f"{API}/artworks/{artwork_id}/sharing", headers=other.headers)
    ).status_code == 404

    # 한 목적만 철회하면 이미지 유지, 모두 철회하면 파일 삭제
    after_community = await client.delete(
        f"{API}/artworks/{artwork_id}/sharing/COMMUNITY", headers=student.headers
    )
    assert after_community.json()["community"] is None and after_community.json()["image"]
    assert len(shared.objects) == 1
    after_all = await client.delete(
        f"{API}/artworks/{artwork_id}/sharing/REFERENCE", headers=student.headers
    )
    assert after_all.json()["image"] is None
    assert shared.objects == {}
    again = await client.delete(
        f"{API}/artworks/{artwork_id}/sharing/REFERENCE", headers=student.headers
    )
    assert again.status_code == 404


# ============================================================================ 게시물·공개 범위


async def test_post_visibility_scopes_and_crud(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, photos: FakeStorage, build_world, actors
) -> None:
    author = world.students[0]
    public_art = await _final_artwork(client, photos, author, "공개 작품")
    academy_art = await _final_artwork(
        client, photos, author, "학원 공개 작품", academy_id=world.academy_id
    )
    # 동의 없이 게시 불가
    no_consent = await client.post(
        f"{API}/community/posts",
        json={"artwork_id": public_art, "title": "x"},
        headers=author.headers,
    )
    assert no_consent.json()["error"]["code"] == "SHARING_CONSENT_REQUIRED"
    await _share(client, author, public_art)  # 익명 기본
    await _share(client, author, academy_art, scope="ACADEMY", author_display="NAME")
    public_post = await _post(client, author, public_art, body="첫 게시물")
    academy_post = await _post(client, author, academy_art)
    assert public_post["author"] == {
        "display_name": author_name(world),
        "is_anonymous": False,
        "is_me": True,
    }
    dup = await client.post(
        f"{API}/community/posts",
        json={"artwork_id": public_art, "title": "again"},
        headers=author.headers,
    )
    assert dup.json()["error"]["code"] == "POST_ALREADY_EXISTS"

    # 같은 학원 학생: 둘 다 보임, 공개 게시물은 익명
    classmate = world.students[1]
    feed = (await client.get(f"{API}/community/posts", headers=classmate.headers)).json()
    assert {p["id"] for p in feed["items"]} == {public_post["id"], academy_post["id"]}
    by_id = {p["id"]: p for p in feed["items"]}
    assert by_id[public_post["id"]]["author"]["display_name"] == "익명 학생"
    assert by_id[academy_post["id"]]["author"]["display_name"] == author_name(world)
    assert by_id[public_post["id"]]["artwork_id"] is None  # 남의 작품 ID 비노출
    assert by_id[academy_post["id"]]["visibility"] == {
        "scope": "ACADEMY",
        "academy_id": world.academy_id,
    }
    # 다른 학원 사용자·학원 없는 사용자: 공개 게시물만, 학원 게시물은 404
    other_world = await build_world("다른 학원", admin=world.admin)
    outsider = other_world.students[0]
    loner = await actors.signup("STUDENT")
    for viewer in (outsider, loner):
        items = (await client.get(f"{API}/community/posts", headers=viewer.headers)).json()["items"]
        assert [p["id"] for p in items] == [public_post["id"]]
        hidden = await client.get(
            f"{API}/community/posts/{academy_post['id']}", headers=viewer.headers
        )
        assert hidden.status_code == 404
        assert (
            await client.put(
                f"{API}/community/posts/{academy_post['id']}/like", headers=viewer.headers
            )
        ).status_code == 404
    # 강사도 볼 수 있다 (같은 학원)
    assert (
        await client.get(
            f"{API}/community/posts/{academy_post['id']}", headers=world.teacher.headers
        )
    ).status_code == 200
    # 필터
    filtered = await client.get(
        f"{API}/community/posts?practical_type=WATERCOLOR", headers=classmate.headers
    )
    assert filtered.json()["total"] == 0
    academy_only = await client.get(
        f"{API}/community/posts?academy_id={world.academy_id}", headers=classmate.headers
    )
    assert [p["id"] for p in academy_only.json()["items"]] == [academy_post["id"]]

    # 수정·삭제는 작성자만
    edit = await client.patch(
        f"{API}/community/posts/{public_post['id']}",
        json={"title": "수정됨"},
        headers=classmate.headers,
    )
    assert edit.status_code == 403
    edited = await client.patch(
        f"{API}/community/posts/{public_post['id']}",
        json={"title": "수정됨", "practical_type": "DRAWING"},
        headers=author.headers,
    )
    assert edited.json()["title"] == "수정됨" and edited.json()["practical_type"] == "DRAWING"
    assert (
        await client.delete(f"{API}/community/posts/{public_post['id']}", headers=classmate.headers)
    ).status_code == 403
    assert (
        await client.delete(f"{API}/community/posts/{public_post['id']}", headers=author.headers)
    ).status_code == 204
    assert (
        await client.get(f"{API}/community/posts/{public_post['id']}", headers=classmate.headers)
    ).status_code == 404
    # 동의는 남아 있어 다시 게시 가능
    await _post(client, author, public_art, title="다시 올림")
    mine = (await client.get(f"{API}/community/posts/me", headers=author.headers)).json()
    assert mine["total"] == 2

    # 강사 계정은 게시 불가 (학생 본인 작품만)
    assert (
        await client.post(
            f"{API}/community/posts",
            json={"artwork_id": public_art, "title": "x"},
            headers=world.teacher.headers,
        )
    ).status_code == 403


def author_name(world: World) -> str:
    return "아트메이트 미술학원-학생1"


# ============================================================================ 좋아요·저장·철회


async def test_likes_bookmarks_and_withdrawal(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, photos: FakeStorage, shared: FakeStorage
) -> None:
    author = await actors.signup("STUDENT")
    viewers = [await actors.signup("STUDENT") for _ in range(3)]
    artwork_id = await _final_artwork(client, photos, author)
    await _share(client, author, artwork_id)
    post = await _post(client, author, artwork_id)
    url = f"{API}/community/posts/{post['id']}"

    # 동시·중복 좋아요 → 1번만
    results = await asyncio.gather(
        *[client.put(f"{url}/like", headers=viewers[0].headers) for _ in range(5)]
    )
    assert all(r.status_code == 200 for r in results)
    assert (await client.get(url, headers=viewers[0].headers)).json()["like_count"] == 1
    await client.put(f"{url}/like", headers=viewers[1].headers)
    unliked = await client.delete(f"{url}/like", headers=viewers[1].headers)
    assert unliked.json() == {"post_id": post["id"], "liked": False, "like_count": 1}
    again = await client.delete(f"{url}/like", headers=viewers[1].headers)
    assert again.json()["like_count"] == 1
    detail = (await client.get(url, headers=viewers[0].headers)).json()
    assert detail["liked"] is True and detail["bookmarked"] is False

    await client.put(f"{url}/bookmark", headers=viewers[0].headers)
    await client.put(f"{url}/bookmark", headers=viewers[0].headers)
    saved = (await client.get(f"{API}/community/bookmarks", headers=viewers[0].headers)).json()
    assert [p["id"] for p in saved["items"]] == [post["id"]] and saved["items"][0]["bookmarked"]

    # 원작자 공유 철회 → 게시물·저장 목록·좋아요 모두 즉시 사라짐, 이미지 삭제
    await client.delete(f"{API}/artworks/{artwork_id}/sharing/COMMUNITY", headers=author.headers)
    assert (await client.get(url, headers=viewers[0].headers)).status_code == 404
    assert (await client.get(f"{API}/community/bookmarks", headers=viewers[0].headers)).json()[
        "total"
    ] == 0
    assert (await client.get(f"{API}/community/posts", headers=viewers[0].headers)).json()[
        "total"
    ] == 0
    assert (await client.put(f"{url}/like", headers=viewers[2].headers)).status_code == 404
    assert shared.objects == {}


async def test_artwork_deletion_withdraws_sharing(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, photos: FakeStorage, shared: FakeStorage
) -> None:
    author = await actors.signup("STUDENT")
    viewer = await actors.signup("STUDENT")
    artwork_id = await _final_artwork(client, photos, author)
    await _share(client, author, artwork_id)
    post = await _post(client, author, artwork_id)
    assert (
        await client.delete(f"{API}/artworks/{artwork_id}", headers=author.headers)
    ).status_code == 204
    assert (
        await client.get(f"{API}/community/posts/{post['id']}", headers=viewer.headers)
    ).status_code == 404
    assert shared.objects == {}


# ============================================================================ 댓글


async def test_comments_permissions_counts_and_rate_limit(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, photos: FakeStorage, app
) -> None:
    author = await actors.signup("STUDENT")
    alice = await actors.signup("STUDENT", name="앨리스")
    bob = await actors.signup("STUDENT")
    artwork_id = await _final_artwork(client, photos, author)
    await _share(client, author, artwork_id)
    post = await _post(client, author, artwork_id)
    base = f"{API}/community/posts/{post['id']}/comments"

    created = await client.post(
        base, json={"body": "  명암 대비가 좋아요  "}, headers=alice.headers
    )
    assert created.status_code == 201
    comment = created.json()
    assert comment["body"] == "명암 대비가 좋아요" and comment["author"]["display_name"] == "앨리스"
    assert (await client.post(base, json={"body": "   "}, headers=alice.headers)).status_code == 422
    assert (
        await client.post(base, json={"body": "x" * 1001}, headers=alice.headers)
    ).status_code == 422
    await client.post(base, json={"body": "두 번째"}, headers=bob.headers)
    listing = (await client.get(base, headers=author.headers)).json()
    assert [c["body"] for c in listing["items"]] == ["명암 대비가 좋아요", "두 번째"]
    assert (await client.get(f"{API}/community/posts/{post['id']}", headers=bob.headers)).json()[
        "comment_count"
    ] == 2

    cid = comment["id"]
    assert (
        await client.patch(
            f"{API}/community/comments/{cid}", json={"body": "탈취"}, headers=bob.headers
        )
    ).status_code == 403
    assert (
        await client.delete(f"{API}/community/comments/{cid}", headers=author.headers)
    ).status_code == 403
    edited = await client.patch(
        f"{API}/community/comments/{cid}", json={"body": "수정"}, headers=alice.headers
    )
    assert edited.json()["body"] == "수정"
    assert (
        await client.delete(f"{API}/community/comments/{cid}", headers=alice.headers)
    ).status_code == 204
    assert (await client.get(f"{API}/community/posts/{post['id']}", headers=bob.headers)).json()[
        "comment_count"
    ] == 1

    app.state.settings.community_comments_per_10min = 2
    try:
        # bob은 이미 1개 → 1개 더 가능, 그다음은 제한
        assert (
            await client.post(base, json={"body": "하나"}, headers=bob.headers)
        ).status_code == 201
        limited = await client.post(base, json={"body": "둘"}, headers=bob.headers)
        assert limited.json()["error"]["code"] == "RATE_LIMITED"
        assert limited.headers["retry-after"] == "600"
    finally:
        app.state.settings.community_comments_per_10min = 20


# ============================================================================ 신고·관리


async def test_reports_auto_hide_and_admin_moderation(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, photos: FakeStorage
) -> None:
    author = await actors.signup("STUDENT")
    reporters = [await actors.signup("STUDENT") for _ in range(3)]
    admin = await actors.admin()
    artwork_id = await _final_artwork(client, photos, author)
    await _share(client, author, artwork_id)
    post = await _post(client, author, artwork_id)
    url = f"{API}/community/posts/{post['id']}"

    own = await client.post(f"{url}/reports", json={"reason": "SPAM"}, headers=author.headers)
    assert own.json()["error"]["code"] == "CANNOT_REPORT_OWN_CONTENT"
    first = await client.post(
        f"{url}/reports", json={"reason": "SPAM", "detail": "광고"}, headers=reporters[0].headers
    )
    assert first.status_code == 201 and first.json()["status"] == "OPEN"
    dup = await client.post(
        f"{url}/reports", json={"reason": "ABUSE"}, headers=reporters[0].headers
    )
    assert dup.json()["error"]["code"] == "ALREADY_REPORTED"
    for reporter in reporters[1:]:
        await client.post(f"{url}/reports", json={"reason": "SPAM"}, headers=reporter.headers)
    # 서로 다른 3명 → 자동 숨김: 다른 사람에게 404, 작성자는 HIDDEN + 사유
    assert (await client.get(url, headers=reporters[0].headers)).status_code == 404
    mine = (await client.get(url, headers=author.headers)).json()
    assert mine["status"] == "HIDDEN" and "자동 숨김" in mine["hidden_reason"]

    # 일반 사용자는 관리 API 403
    assert (
        await client.get(f"{API}/admin/community/reports", headers=author.headers)
    ).status_code == 403
    reports = (await client.get(f"{API}/admin/community/reports", headers=admin.headers)).json()
    assert reports["total"] == 3 and reports["items"][0]["open_report_count"] == 3
    assert reports["items"][0]["target_status"] == "HIDDEN"
    dismissed = await client.post(
        f"{API}/admin/community/reports/{first.json()['id']}/dismiss",
        json={"note": "문제 없음", "restore": True},
        headers=admin.headers,
    )
    assert (
        dismissed.json()["status"] == "DISMISSED" and dismissed.json()["target_status"] == "ACTIVE"
    )
    assert (await client.get(url, headers=reporters[0].headers)).status_code == 200
    # 같은 대상의 다른 신고도 함께 처리됨
    assert (await client.get(f"{API}/admin/community/reports", headers=admin.headers)).json()[
        "total"
    ] == 0
    handled = await client.post(
        f"{API}/admin/community/reports/{first.json()['id']}/resolve",
        json={"action": "NONE"},
        headers=admin.headers,
    )
    assert handled.json()["error"]["code"] == "REPORT_ALREADY_HANDLED"

    # 댓글 신고 → 관리자 숨김 처리
    comment = (
        await client.post(
            f"{url}/comments", json={"body": "광고 댓글"}, headers=reporters[1].headers
        )
    ).json()
    report = await client.post(
        f"{API}/community/comments/{comment['id']}/reports",
        json={"reason": "SPAM"},
        headers=author.headers,
    )
    resolved = await client.post(
        f"{API}/admin/community/reports/{report.json()['id']}/resolve",
        json={"action": "HIDE", "note": "광고"},
        headers=admin.headers,
    )
    assert resolved.json()["status"] == "RESOLVED" and resolved.json()["target_status"] == "HIDDEN"
    others = (await client.get(f"{url}/comments", headers=reporters[0].headers)).json()
    assert others["total"] == 0
    own_view = (await client.get(f"{url}/comments", headers=reporters[1].headers)).json()
    assert own_view["items"][0]["status"] == "HIDDEN"

    # 게시물 직접 숨김·복구 + 이력
    assert (
        await client.post(
            f"{API}/admin/community/posts/{post['id']}/hide",
            json={"reason": "검토"},
            headers=admin.headers,
        )
    ).status_code == 204
    assert (await client.get(url, headers=reporters[0].headers)).status_code == 404
    assert (
        await client.post(f"{API}/admin/community/posts/{post['id']}/unhide", headers=admin.headers)
    ).status_code == 204
    logs = (
        await client.get(f"{API}/admin/community/moderation-logs", headers=admin.headers)
    ).json()
    actions = [entry["action"] for entry in reversed(logs["items"])]
    # 같은 트랜잭션에서 남긴 이력은 시각이 같아 순서가 정해지지 않으므로 묶음으로 비교
    assert actions[0] == "AUTO_HIDE_POST"
    assert sorted(actions) == sorted(
        [
            "AUTO_HIDE_POST",
            "UNHIDE_POST",
            "DISMISS_REPORT",
            "HIDE_COMMENT",
            "RESOLVE_REPORT",
            "HIDE_POST",
            "UNHIDE_POST",
        ]
    )
    assert logs["items"][-1]["actor_name"] is None  # 시스템 자동 숨김
