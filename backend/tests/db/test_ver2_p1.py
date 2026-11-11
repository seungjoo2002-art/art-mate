"""VER.2 P1: 실명·닉네임 분리, 기본 시험 목표 시간, 커뮤니티 검색, 익명 댓글."""

from __future__ import annotations

import httpx

from tests.db.conftest import Actor

API = "/api/v1"


async def _signup(client: httpx.AsyncClient, actors, **body) -> Actor:  # type: ignore[no-untyped-def]
    actor = actors.anonymous_token()
    created = await client.post(
        f"{API}/users/me", json={"user_type": "STUDENT"} | body, headers=actor.headers
    )
    assert created.status_code == 201, created.text
    return actor


async def _text_post(client, author: Actor, title: str, body: str, **extra) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/community/posts",
        json={"title": title, "body": body} | extra,
        headers=author.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def test_real_name_is_private(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await _signup(client, actors, display_name="그림왕", real_name="김실명")
    me = (await client.get(f"{API}/users/me", headers=student.headers)).json()
    assert (me["display_name"], me["real_name"]) == ("그림왕", "김실명")
    # 기존 방식 가입(실명 없음)도 그대로
    legacy = await actors.signup("STUDENT", name="옛회원")
    assert (await client.get(f"{API}/users/me", headers=legacy.headers)).json()["real_name"] is None

    # 커뮤니티 응답에는 실명이 나오지 않는다
    post = await _text_post(client, student, "질문", "명암 질문이요")
    comment = await client.post(
        f"{API}/community/posts/{post['id']}/comments",
        json={"body": "답변"},
        headers=student.headers,
    )
    assert comment.status_code == 201
    for url in (
        f"{API}/community/posts",
        f"{API}/community/posts/{post['id']}",
        f"{API}/community/posts/{post['id']}/comments",
    ):
        body = (await client.get(url, headers=legacy.headers)).text
        assert "김실명" not in body and "real_name" not in body
        assert "그림왕" in body

    changed = await client.patch(
        f"{API}/users/me", json={"real_name": "김새이름"}, headers=student.headers
    )
    assert changed.json()["real_name"] == "김새이름" and changed.json()["display_name"] == "그림왕"
    cleared = await client.patch(
        f"{API}/users/me", json={"real_name": None}, headers=student.headers
    )
    assert cleared.json()["real_name"] is None
    for bad in ({"real_name": ""}, {"real_name": "가" * 51}):
        assert (
            await client.patch(f"{API}/users/me", json=bad, headers=student.headers)
        ).status_code == 422


async def test_exam_defaults_sync(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    url = f"{API}/users/me/exam-defaults"
    initial = (await client.get(url, headers=student.headers)).json()
    assert initial["source"] == "DEFAULT"
    assert [s["stage"] for s in initial["stages"]] == ["IDEA", "SKETCH", "COLOR"]
    stages = [
        {"stage": "IDEA", "target_minutes": 30},
        {"stage": "SKETCH", "target_minutes": 60},
        {"stage": "COLOR", "target_minutes": 150},
        {"stage": "FINISH", "target_minutes": 20},
    ]
    saved = await client.put(url, json={"stages": stages}, headers=student.headers)
    assert saved.status_code == 200 and saved.json() == {"stages": stages, "source": "ACCOUNT"}
    # 다른 기기(같은 계정)에서도 같은 값
    assert (await client.get(url, headers=student.headers)).json()["stages"] == stages
    for bad in (
        {"stages": []},
        {"stages": [{"stage": "IDEA", "target_minutes": 10}] * 2},
        {"stages": [{"stage": "IDEA", "target_minutes": 0}]},
        {"stages": [{"stage": "NAP", "target_minutes": 10}]},
    ):
        assert (await client.put(url, json=bad, headers=student.headers)).status_code == 422
    other = await actors.signup("STUDENT")
    assert (await client.get(url, headers=other.headers)).json()["source"] == "DEFAULT"
    teacher = await actors.signup("INSTRUCTOR")
    assert (await client.get(url, headers=teacher.headers)).status_code == 403


async def test_community_search(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    author = await actors.signup("STUDENT")
    viewer = await actors.signup("STUDENT")
    a = await _text_post(
        client, author, "명암 단계 질문", "몇 단계로 나눠요?", category="PRACTICE_QUESTION"
    )
    b = await _text_post(client, author, "오늘 실기", "명암이 어려웠다", category="FREE")
    c = await _text_post(client, author, "할인 100%", "이벤트 공지", category="FREE")
    await _text_post(client, author, "구도 고민", "삼각 구도 vs 대각선", category="FREE")

    async def search(**params) -> dict:  # type: ignore[no-untyped-def]
        response = await client.get(f"{API}/community/posts", params=params, headers=viewer.headers)
        assert response.status_code == 200, response.text
        return response.json()

    found = await search(q="명암")
    assert {p["id"] for p in found["items"]} == {a["id"], b["id"]}  # 제목·본문
    assert found["total"] == 2
    combined = await search(q="명암", category="FREE")
    assert [p["id"] for p in combined["items"]] == [b["id"]]
    literal = await search(q="0%")
    assert [p["id"] for p in literal["items"]] == [c["id"]]  # % 는 글자 그대로
    assert (await search(q="없는말"))["total"] == 0
    paged = await search(q="명암", limit=1, offset=1)
    assert paged["total"] == 2 and len(paged["items"]) == 1
    for bad in ("명", "가" * 51):
        too = await client.get(f"{API}/community/posts", params={"q": bad}, headers=viewer.headers)
        assert too.status_code == 422


async def test_anonymous_comments(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    author = await actors.signup("STUDENT", name="글쓴이")
    commenter = await actors.signup("STUDENT", name="숨은이")
    reader = await actors.signup("STUDENT", name="구경꾼")
    post = await _text_post(
        client, author, "피드백 부탁", "구도 봐주세요", category="FEEDBACK_REQUEST"
    )
    comments = f"{API}/community/posts/{post['id']}/comments"
    anon = await client.post(
        comments, json={"body": "구도가 좋아요", "is_anonymous": True}, headers=commenter.headers
    )
    assert anon.status_code == 201
    named = await client.post(comments, json={"body": "저도 동의"}, headers=commenter.headers)
    assert named.json()["author"]["is_anonymous"] is False

    for viewer in (reader, author):
        listing = await client.get(comments, headers=viewer.headers)
        first = listing.json()["items"][0]
        assert first["author"] == {
            "display_name": "익명 학생",
            "is_anonymous": True,
            "is_me": False,
        }
        # 익명 댓글의 작성자 정보가 응답 어디에도 없다
        anon_json = str(first)
        assert "숨은이" not in anon_json and str(commenter.user_id) not in listing.text
    mine = (await client.get(comments, headers=commenter.headers)).json()["items"][0]
    assert mine["author"]["is_me"] is True and mine["author"]["display_name"] == "익명 학생"

    # 본인 수정(익명 해제 포함)·삭제, 남은 불가
    cid = anon.json()["id"]
    assert (
        await client.patch(
            f"{API}/community/comments/{cid}",
            json={"body": "구도가 정말 좋아요"},
            headers=reader.headers,
        )
    ).status_code == 403
    edited = await client.patch(
        f"{API}/community/comments/{cid}",
        json={"body": "수정", "is_anonymous": False},
        headers=commenter.headers,
    )
    assert edited.json()["author"]["display_name"] == "숨은이"
    await client.patch(
        f"{API}/community/comments/{cid}",
        json={"body": "다시 익명", "is_anonymous": True},
        headers=commenter.headers,
    )

    # 신고 → 관리자는 실제 작성자를 확인할 수 있다
    reported = await client.post(
        f"{API}/community/comments/{cid}/reports", json={"reason": "ABUSE"}, headers=reader.headers
    )
    assert reported.status_code == 201
    admin = await actors.admin()
    reports = (await client.get(f"{API}/admin/community/reports", headers=admin.headers)).json()
    target = next(r for r in reports["items"] if r["comment_id"] == cid)
    assert target["target_author_id"] == str(commenter.user_id)
    # 일반 사용자는 관리자 API 불가
    assert (
        await client.get(f"{API}/admin/community/reports", headers=reader.headers)
    ).status_code == 403
    assert (
        await client.delete(f"{API}/community/comments/{cid}", headers=commenter.headers)
    ).status_code == 204
