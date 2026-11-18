"""v1.1 원본 제시물·시험 조건·표현 의도 E2E: 실제 API(로컬) + 로컬 PostgreSQL + 실제 브라우저.

외부 서비스만 로컬 대체: Supabase 인증 토큰, Storage(메모리 — 브라우저 업로드를 Playwright가
/__e2e/storage/put으로 중계). AI 호출 없음. 운영 DB·운영 API에 접근하지 않는다.
usage: python -X utf8 e2e/local_reference_flow.py <tokens.json> <out_dir>
"""

import io
import json
import re
import sys
import time
from email.parser import BytesParser
from email.policy import HTTP
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image
from playwright.sync_api import Page, sync_playwright


FRONT = "http://localhost:4175"
API = "http://127.0.0.1:8010/api/v1"
TOK = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = sys.argv[2]
results = []
upload_failures = {"left": 0}
ARTWORK_URL = re.compile(r".*/artworks/[0-9a-f-]{36}$")
CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*",
        "access-control-allow-methods": "*"}


def h(user):
    return {"Authorization": f"Bearer {TOK[user]['token']}"}


def session(user):
    t = TOK[user]
    return {
        "access_token": t["token"], "refresh_token": "e2e", "expires_at": t["exp"],
        "expires_in": t["exp"] - int(time.time()), "token_type": "bearer",
        "user": {"id": t["id"], "aud": "authenticated", "role": "authenticated", "email": f"{user}@e2e.invalid",
                 "app_metadata": {}, "user_metadata": {}, "created_at": "2026-11-16T00:00:00Z"},
    }


def ctx_for(browser, user, mobile=True):
    size = {"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900}
    ctx = browser.new_context(viewport=size, is_mobile=mobile, locale="ko-KR", timezone_id="Asia/Seoul")
    ctx.add_init_script(f"localStorage.setItem('sb-e2e-project-auth-token', {json.dumps(json.dumps(session(user)))})")
    ctx.route("**/e2e-project.supabase.co/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}",
        headers={"access-control-allow-origin": "*", "access-control-allow-headers": "*"}))
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)[:200]))
    page.on("response", lambda r: page.errors.append(f"{r.status} {r.url[-80:]}") if r.status >= 500 else None)
    return ctx, page


def go(page: Page, path):
    page.goto(FRONT + path, wait_until="networkidle")
    page.wait_for_timeout(600)


def hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def png(color, size=(120, 90), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def file(name, color, fmt="PNG", mime="image/png"):
    return {"name": name, "mimeType": mime, "buffer": png(color, fmt=fmt)}


def relay_upload(route):
    """supabase.storage.uploadToSignedUrl(PUT multipart) → 메모리 Storage"""
    req = route.request
    if req.method == "OPTIONS":
        return route.fulfill(status=200, headers=CORS, body="")
    if upload_failures["left"] > 0:
        upload_failures["left"] -= 1
        return route.fulfill(status=500, headers=CORS, content_type="application/json",
                             body='{"error":"simulated","message":"simulated upload failure"}')
    m = re.search(r"/object/upload/sign/([^/]+)/(.+)$", unquote(urlparse(req.url).path))
    bucket, path = m[1], m[2]
    ct = req.headers["content-type"]
    body = req.post_data_buffer
    if ct.startswith("multipart/"):
        msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ct.encode() + b"\r\n\r\n" + body)
        body = next(p.get_payload(decode=True) for p in msg.iter_parts()
                    if p.get_param("name", header="content-disposition") != "cacheControl")
    r = httpx.post("http://127.0.0.1:8010/__e2e/storage/put", params={"bucket": bucket, "path": path},
                   content=body)
    route.fulfill(status=200, headers=CORS, content_type="application/json", body=r.text)


def new_ctx(browser, user, mobile):
    ctx, page = ctx_for(browser, user, mobile)
    ctx.route("**/storage/v1/object/upload/sign/**", relay_upload)  # 나중 등록 = 우선
    page.on("dialog", lambda d: d.accept())
    return ctx, page


def refs(user, artwork_id):
    return httpx.get(f"{API}/artworks/{artwork_id}/reference-photos", headers=h(user))


def stage_photo(user, artwork_id, color):
    data = png(color)
    t = httpx.post(f"{API}/artworks/{artwork_id}/photos", headers=h(user),
                   json={"stage": "SKETCH", "content_type": "image/png", "file_size": len(data)}).json()
    httpx.post("http://127.0.0.1:8010/__e2e/storage/put", params={"bucket": "artworks", "path": t["upload"]["path"]},
               content=data)
    return httpx.post(f"{API}/artworks/{artwork_id}/photos/{t['photo']['id']}/complete", headers=h(user))


def create_flow(page: Page):
    go(page, "/artworks/new")
    page.get_by_label("작품명").fill("[E2E] 유리컵 기초디자인")
    page.get_by_label("주제 또는 소재 (선택)").fill("유리컵과 사과")
    # 형식 오류 파일은 고르는 즉시 안내 (작품 생성 전)
    page.locator("input[type=file][multiple]").set_input_files(
        [{"name": "anim.gif", "mimeType": "image/gif", "buffer": b"GIF89a" + b"0" * 40}])
    check("잘못된 형식 안내", page.get_by_text("JPG, PNG, WEBP 사진만").first.is_visible())
    page.locator("input[type=file][multiple]").set_input_files([file("ref1.png", "green"), file("ref2.jpg", "navy", "JPEG", "image/jpeg")])
    check("원본 미리보기 2장", page.get_by_role("img", name="올릴 원본 사진").count() == 2)
    page.locator("summary", has_text="시험 조건").click()
    page.get_by_label("화지 규격").fill("4절")
    page.get_by_label("추가 시험 조건").fill("제시물 2개 이상 사용")
    page.get_by_label("시험 시간 (분)").fill("240")
    page.locator("summary", has_text="표현 의도").click()
    page.get_by_role("button", name="회전·기울이기").click()
    page.get_by_role("button", name="확대·축소").click()
    page.get_by_label("의도 설명").fill("유리컵을 기울여 역동적인 구도를 만들었다.")
    check("등록 화면 가로 스크롤 없음", not hscroll(page))
    page.screenshot(path=f"{OUT}/v11-create-mobile.png", full_page=True)
    page.get_by_role("button", name="작품 기록 시작하기").click()
    page.wait_for_url(ARTWORK_URL, timeout=20000)
    return page.url.rsplit("/", 1)[1]


def main():
    tok_students = ("student", "other")
    for name, nick in (("student", "원본E2E"), ("other", "다른학생")):  # 학생 프로필 (멱등)
        r = httpx.post(f"{API}/users/me", headers=h(name), json={"display_name": nick, "user_type": "STUDENT"})
        assert r.status_code in (200, 201), r.text
    httpx.patch(f"{API}/users/me", headers=h("student"), json={"practical_type": "BASIC_DESIGN"})
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = new_ctx(browser, "student", mobile=True)

        # 1) 등록 흐름: 주제 → 원본 사진 → 시험 조건 → 의도 → 생성 후 업로드
        aid = create_flow(page)
        art = httpx.get(f"{API}/artworks/{aid}", headers=h("student")).json()
        check("시험 조건 저장", (art["paper_size"], art["exam_conditions"], art["time_limit_minutes"])
              == ("4절", "제시물 2개 이상 사용", 240), str(art["paper_size"]))
        check("표현 의도 저장 (정의 순서)", art["expression_methods"] == ["SCALE", "ROTATE"]
              and art["expression_intent"].startswith("유리컵을"), str(art["expression_methods"]))
        listed = refs("student", aid).json()
        check("원본 2장 업로드", len(listed["items"]) == 2, str(len(listed["items"])))
        check("작품 사진과 분리 (photo_count 0)", art["photo_count"] == 0)

        # 2) 상세: 원본 ↔ 내 작품 나란히 + 조건 표시
        assert stage_photo("student", aid, "orange").status_code == 200
        go(page, f"/artworks/{aid}")
        figs = page.locator("figure")
        check("상세 비교 2칸", figs.count() == 2 and page.get_by_role("img", name="원본 제시물").is_visible()
              and page.get_by_role("img", name="내 작품").is_visible())
        b1, b2 = figs.nth(0).bounding_box(), figs.nth(1).bounding_box()
        check("모바일에서도 나란히", abs(b1["y"] - b2["y"]) < 2 and b1["x"] < b2["x"], f"{b1['y']:.0f}/{b2['y']:.0f}")
        check("조건·의도 표시", page.get_by_text("4절").is_visible()
              and page.get_by_text("확대·축소 · 회전·기울이기").is_visible())
        check("원본 썸네일 선택", page.get_by_role("button", name="원본 2 보기").is_visible())
        check("상세 가로 스크롤 없음 (모바일)", not hscroll(page))
        page.screenshot(path=f"{OUT}/v11-detail-mobile.png", full_page=True)

        # 3) 수정: 교체·삭제·의도 수정
        go(page, f"/artworks/{aid}/edit")
        before = [p["id"] for p in refs("student", aid).json()["items"]]
        with page.expect_file_chooser() as fc:
            page.get_by_role("button", name="원본 1 교체").click()
        fc.value.set_files([file("ref1b.png", "purple")])
        page.wait_for_timeout(1500)
        after = [p["id"] for p in refs("student", aid).json()["items"]]
        check("교체: 같은 자리, 새 사진", len(after) == 2 and after[0] != before[0] and after[1] == before[1])
        page.get_by_role("button", name="원본 2 삭제").click()
        page.wait_for_timeout(1500)
        check("삭제", [p["id"] for p in refs("student", aid).json()["items"]] == [after[0]])
        with page.expect_file_chooser() as fc:
            page.get_by_role("button", name="사진 추가").click()
        fc.value.set_files([file("ref3.webp", "teal", "WEBP", "image/webp")])
        page.wait_for_timeout(1500)
        check("기존 작품에 추가 (WebP)", len(refs("student", aid).json()["items"]) == 2)
        page.get_by_role("button", name="회전·기울이기").click()  # 선택 해제
        page.get_by_label("의도 설명").fill("")
        check("수정 화면 가로 스크롤 없음", not hscroll(page))
        page.screenshot(path=f"{OUT}/v11-edit-mobile.png", full_page=True)
        page.get_by_role("button", name="저장하기").click()
        page.wait_for_url(ARTWORK_URL, timeout=15000)
        art = httpx.get(f"{API}/artworks/{aid}", headers=h("student")).json()
        check("의도 수정 저장", art["expression_methods"] == ["SCALE"] and art["expression_intent"] is None
              and art["paper_size"] == "4절", str(art["expression_methods"]))
        ci = httpx.get(f"{API}/artworks/{aid}/comparison-input", headers=h("student")).json()
        check("v1.2 입력 준비 완료", ci["readiness"]["ready"] and ci["intent"]["status"] == "PROVIDED"
              and len(ci["references"]) == 2)

        # 4) 업로드 실패 → 입력 유지 + 재시도 (작품 중복 생성 없음)
        upload_failures["left"] = 1
        go(page, "/artworks/new")
        page.get_by_label("작품명").fill("[E2E] 업로드 재시도")
        page.locator("input[type=file][multiple]").set_input_files([file("r1.png", "gold"), file("r2.png", "maroon")])
        page.get_by_role("button", name="작품 기록 시작하기").click()
        retry = page.get_by_role("button", name="원본 사진 다시 올리기")
        retry.wait_for(timeout=15000)
        check("실패 안내 + 입력 유지", page.get_by_text("원본 사진 1장을 올리지 못했어요").is_visible()
              and page.get_by_label("작품명").input_value() == "[E2E] 업로드 재시도")
        page.screenshot(path=f"{OUT}/v11-retry-mobile.png", full_page=True)
        retry.click()
        page.wait_for_url(ARTWORK_URL, timeout=15000)
        rid = page.url.rsplit("/", 1)[1]
        mine = [a for a in httpx.get(f"{API}/artworks", headers=h("student"), params={"limit": 50}).json()["items"]
                if a["title"] == "[E2E] 업로드 재시도"]
        check("재시도 후 2장, 작품 1개", len(refs("student", rid).json()["items"]) == 2 and len(mine) == 1,
              f"artworks={len(mine)}")
        page.close()
        ctx.close()

        # 5) 데스크톱 상세
        ctx, page = new_ctx(browser, "student", mobile=False)
        go(page, f"/artworks/{aid}")
        figs = page.locator("figure")
        b1, b2 = figs.nth(0).bounding_box(), figs.nth(1).bounding_box()
        check("데스크톱 나란히", abs(b1["y"] - b2["y"]) < 2 and b1["x"] < b2["x"])
        check("데스크톱 가로 스크롤 없음", not hscroll(page))
        page.screenshot(path=f"{OUT}/v11-detail-desktop.png", full_page=True)

        # 6) 기존 방식 작품 (새 필드 없음) 상세 정상
        old = httpx.post(f"{API}/artworks", headers=h("student"), json={"title": "[E2E] 예전 방식"}).json()
        go(page, f"/artworks/{old['id']}")
        check("기존 작품 상세 정상 + 원본 추가 안내", page.get_by_text("원본 사진 추가").is_visible()
              and not page.errors, str(page.errors[:2]))
        page.close()
        ctx.close()
        browser.close()

    # 7) 다른 학생 접근 차단
    other = [httpx.get(f"{API}/artworks/{aid}/reference-photos", headers=h(tok_students[1])).status_code,
             httpx.get(f"{API}/artworks/{aid}/comparison-input", headers=h(tok_students[1])).status_code]
    check("다른 학생 404", other == [404, 404], str(other))

    failed = [r for r in results if not r[1]]
    json.dump([{"name": n, "ok": ok, "detail": d} for n, ok, d in results],
              open(f"{OUT}/v11-results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
