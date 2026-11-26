"""v1.3 AI 수정본 E2E: 실제 API(로컬) + 로컬 PostgreSQL + 실제 브라우저 (모바일·데스크톱).

외부 서비스만 로컬 대체: Supabase 인증 토큰, Storage(메모리 — 가짜 Signed URL을 Playwright가
/__e2e/storage/get 응답으로 채움), 이미지 수정 AI(원본을 흑백+동그라미로 바꾸는 가짜 — 실제 OpenAI 호출 없음).
usage: python -X utf8 e2e/local_ai_revision_flow.py <tokens.json> <out_dir>
"""

import io
import json
import sys
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from PIL import Image, ImageDraw
from playwright.sync_api import Page, sync_playwright

FRONT = "http://localhost:4175"
BASE = "http://127.0.0.1:8010"
API = f"{BASE}/api/v1"
TOK = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = sys.argv[2]
results = []
timings = {}


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def h(user):
    return {"Authorization": f"Bearer {TOK[user]['token']}"}


def session(user):
    t = TOK[user]
    return {
        "access_token": t["token"], "refresh_token": "e2e", "expires_at": t["exp"],
        "expires_in": t["exp"] - int(time.time()), "token_type": "bearer",
        "user": {"id": t["id"], "aud": "authenticated", "role": "authenticated",
                 "email": f"{user}@e2e.invalid", "app_metadata": {}, "user_metadata": {},
                 "created_at": "2026-11-16T00:00:00Z"},
    }


def serve_storage(route):
    # https://storage.test/object/sign/{bucket}/{path}?token=...
    parts = unquote(urlparse(route.request.url).path).split("/object/sign/", 1)[1]
    bucket, path = parts.split("/", 1)
    r = httpx.get(f"{BASE}/__e2e/storage/get", params={"bucket": bucket, "path": path})
    route.fulfill(status=r.status_code, body=r.content,
                  headers={"content-type": r.headers.get("content-type", "image/jpeg"),
                           "access-control-allow-origin": "*"})


def ctx_for(browser, user, mobile=True):
    size = {"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900}
    ctx = browser.new_context(viewport=size, is_mobile=mobile, has_touch=mobile,
                              locale="ko-KR", timezone_id="Asia/Seoul")
    ctx.add_init_script(
        f"localStorage.setItem('sb-e2e-project-auth-token', {json.dumps(json.dumps(session(user)))})")
    ctx.route("**/e2e-project.supabase.co/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}",
        headers={"access-control-allow-origin": "*", "access-control-allow-headers": "*"}))
    ctx.route("https://storage.test/**", serve_storage)
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)[:200]))
    page.on("response", lambda r: page.errors.append(f"{r.status} {r.url[-80:]}")
            if r.status >= 500 else None)
    return ctx, page


def go(page: Page, path):
    page.goto(FRONT + path, wait_until="networkidle")
    page.wait_for_timeout(700)


def shot(page: Page, name):
    page.screenshot(path=f"{OUT}/{name}.png", full_page=True)


def hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")


def drain():
    return httpx.post(f"{BASE}/__e2e/drain").json()


def drawing(size, seed):
    """연필 정물 비슷한 그림 (사람 작품 사진 대신 쓰는 합성 이미지)."""
    img = Image.new("RGB", size, (236, 232, 224))
    d = ImageDraw.Draw(img)
    w, hgt = size
    d.ellipse((w * 0.15, hgt * 0.45, w * 0.45, hgt * 0.75), outline=(60, 60, 60), width=5)  # 사과
    d.rectangle((w * 0.55, hgt * 0.25, w * 0.75, hgt * 0.75), outline=(70, 70, 70), width=5)  # 병
    d.ellipse((w * 0.55, hgt * 0.22, w * 0.75, hgt * 0.28), outline=(70, 70, 70), width=4)
    d.line((0, hgt * 0.78, w, hgt * 0.78), fill=(120, 120, 120), width=3)
    d.text((10, 10), f"sketch {seed}", fill=(90, 90, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def upload(user, artwork_id, stage_id, data, replaces=None):
    body = {"stage_id": stage_id, "content_type": "image/jpeg", "file_size": len(data)}
    if replaces:
        body["replaces_photo_id"] = replaces
    t = httpx.post(f"{API}/artworks/{artwork_id}/photos", headers=h(user), json=body).json()
    httpx.post(f"{BASE}/__e2e/storage/put", params={"bucket": "artworks", "path": t["upload"]["path"]},
               content=data)
    done = httpx.post(f"{API}/artworks/{artwork_id}/photos/{t['photo']['id']}/complete", headers=h(user))
    assert done.status_code == 200, done.text
    return done.json()


def note(user, artwork_id, stage_id, photo_id, body):
    n = httpx.post(f"{API}/artworks/{artwork_id}/feedback-notes", headers=h(user), json={
        "source": "INSTRUCTOR", "body": body, "stage_id": stage_id,
        "reference_photo_ids": [photo_id], "reference_confirmed": True, "request_summary": True,
    })
    assert n.status_code == 201, n.text
    return n.json()


def touch_drag(page: Page, x1, y, x2, steps=8):
    cdp = page.context.new_cdp_session(page)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x1, "y": y}]})
    for i in range(1, steps + 1):
        x = x1 + (x2 - x1) * i / steps
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
        page.wait_for_timeout(16)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    page.wait_for_timeout(500)


def touch_swipe(page: Page, x, y, dx=0, dy=0, steps=12):
    """손가락 스와이프 (CDP 터치 이벤트 → 브라우저 기본 스크롤·scroll-snap이 실제로 동작)."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    for i in range(1, steps + 1):
        point = {"x": x + dx * i / steps, "y": y + dy * i / steps}
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [point]})
        page.wait_for_timeout(16)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    page.wait_for_timeout(1000)


def page_text(page: Page):
    return page.locator("main").inner_text()


with sync_playwright() as p:
    browser = p.chromium.launch()

    # ------------------------------------------------------------------ 준비 (API)
    for user, name in (("student", "AI수정E2E"), ("other", "다른학생")):
        r = httpx.post(f"{API}/users/me", headers=h(user), json={"display_name": name, "user_type": "STUDENT"})
        assert r.status_code in (200, 201, 409), r.text
        httpx.patch(f"{API}/users/me", headers=h(user), json={"practical_type": "DRAWING"})
    httpx.post(f"{API}/ai-processing-consents", headers=h("student"),
               json={"policy_version": "2026-12-ai-v2", "agreed": True, "birth_year_month": "2000-01"})
    art = httpx.post(f"{API}/artworks", headers=h("student"), json={
        "title": "[E2E] 정물 소묘", "practical_type": "DRAWING", "topic": "유리병과 사과"}).json()
    sketch, color, final = art["stage_plan"]
    p1 = upload("student", art["id"], sketch["id"], drawing((600, 800), 1))   # 세로
    p2 = upload("student", art["id"], sketch["id"], drawing((900, 600), 2))   # 가로
    p3 = upload("student", art["id"], sketch["id"], drawing((700, 700), 3))   # 정사각 (피드백 없음)
    note("student", art["id"], sketch["id"], p1["id"],
         "구도는 안정적이다. 유리병 입구 타원이 지나치게 납작하다. 사과의 명암 대비를 더 강하게 줘라. 다음엔 시간 배분을 신경 써라.")
    note("student", art["id"], sketch["id"], p2["id"],
         "배치가 좋다. 사물 간 앞뒤 공간감이 부족하다. 뒤쪽 사물의 윤곽을 더 흐리게 처리해라.")
    drain()
    aid = art["id"]

    # ================================================================== 모바일
    ctx, m = ctx_for(browser, "student", mobile=True)

    # 1) 아카이브 상세: 단계 피드백 보기 바로 아래 AI 수정본 보기 (0개), 같은 폭, 사진 슬라이드 그대로
    go(m, f"/artworks/{aid}")
    stage_sec = m.locator("section", has=m.get_by_role("link", name="스케치 AI 수정본 보기 0개"))
    view = stage_sec.get_by_role("link", name="스케치 단계 피드백 보기", exact=False)
    ai = m.get_by_role("link", name="스케치 AI 수정본 보기 0개")
    check("아카이브: 'AI 수정본 보기 (0개)' 버튼 표시", ai.count() == 1, ai.inner_text() if ai.count() else "")
    if ai.count() and view.count():
        vb, ab = view.bounding_box(), ai.bounding_box()
        check("아카이브: 피드백 보기와 같은 폭, 바로 아래",
              abs(vb["width"] - ab["width"]) < 2 and 0 < ab["y"] - (vb["y"] + vb["height"]) < 16,
              f"view={vb} ai={ab}")
    check("아카이브: 원본 사진 슬라이드 3장 그대로", m.get_by_text("1 / 3").count() >= 1)
    check("아카이브: 가로 스크롤 없음", not hscroll(m))
    shot(m, "m01_archive_detail")

    # 2) AI 수정본 화면 (수정본 없음)
    ai.click()
    m.wait_for_timeout(900)
    check("상세: 제목 '스케치 AI 수정본'", m.get_by_role("heading", name="스케치 AI 수정본").count() == 1)
    check("상세: 사진 1 / 3", "사진 1 / 3" in page_text(m))
    check("상세: 빈 상태 안내", "아직 생성된 AI 수정본이 없어요." in page_text(m))
    check("상세: 피드백 화면 이동 버튼", m.get_by_role("link", name="이 사진 피드백 화면으로 가기").count() == 1)
    check("상세: 하단 안내 문구", "학습용 참고 이미지예요" in page_text(m))
    shot(m, "m02_ai_page_empty")

    # 3) 단계별 피드백 화면: 개선사항 패널
    go(m, f"/artworks/{aid}/feedback?stage={sketch['id']}&photo={p1['id']}")
    panel = m.locator("section[aria-label='AI 수정에 반영할 개선사항']")
    check("피드백: 개선사항 패널 표시", panel.count() == 1)
    boxes = panel.locator("input[type=checkbox]")
    check("피드백: 사진 1 개선사항 2개, 기본 전체 선택",
          boxes.count() == 2 and all(boxes.nth(i).is_checked() for i in range(boxes.count())),
          panel.inner_text().replace("\n", " | ")[:200])
    check("피드백: 다른 사진 피드백(공간감) 미포함", "공간감" not in panel.inner_text())
    check("피드백: 외부 AI 전달 안내", "외부 AI(OpenAI)로 전달돼요" in panel.inner_text())
    shot(m, "m03_feedback_panel")

    # 사진 넘기면 개선사항도 바뀜
    m.get_by_role("tab", name="2번째 사진").click()
    m.wait_for_timeout(1200)
    panel = m.locator("section[aria-label='AI 수정에 반영할 개선사항']")
    check("피드백: 사진 2로 넘기면 사진 2 개선사항", "공간감" in panel.inner_text() and "타원" not in panel.inner_text())
    m.get_by_role("tab", name="3번째 사진").click()
    m.wait_for_timeout(1200)
    panel = m.locator("section[aria-label='AI 수정에 반영할 개선사항']")
    check("피드백: 피드백 없는 사진 → 생성 버튼 없음·안내",
          panel.count() == 1 and "연결된 피드백이 없어요" in panel.inner_text()
          and panel.get_by_role("button", name="피드백 반영 수정하기").count() == 0)
    m.get_by_role("tab", name="1번째 사진").click()
    m.wait_for_timeout(1200)

    # 4) 동의 → 돌아와서 1개만 골라 생성
    panel = m.locator("section[aria-label='AI 수정에 반영할 개선사항']")
    panel.locator("label").nth(1).click()  # 두 번째(수정 방법) 해제
    panel.get_by_role("button", name="피드백 반영 수정하기").click()
    m.wait_for_timeout(1000)
    check("동의: 외부 AI 이미지 처리 동의 화면으로 이동", "purpose=VISUAL_CRITIQUE" in m.url)
    consent_text = page_text(m)
    check("동의서: 목적·실제 작품 아님·보관·거부 권리",
          all(k in consent_text for k in ("학습용 수정 예시", "실력 평가 결과가 아니에요", "30일", "그대로 쓸 수 있어요")))
    shot(m, "m04_consent")
    m.get_by_label("태어난 해").select_option("2000")
    m.get_by_label("태어난 달").select_option("01")
    m.locator("label", has_text="AI(OpenAI)로 보내는 데 동의합니다").click()
    m.get_by_role("button", name="동의하기").click()
    m.wait_for_timeout(1500)
    check("동의 후 피드백 화면으로 복귀", "/feedback" in m.url, m.url)
    panel = m.locator("section[aria-label='AI 수정에 반영할 개선사항']")
    panel.locator("label").nth(1).click()  # 다시 하나만
    kept = panel.locator("label").nth(0).inner_text().split("\n")[-1].strip()
    dropped = panel.locator("label").nth(1).inner_text().split("\n")[-1].strip()
    t0 = time.monotonic()
    panel.get_by_role("button", name="피드백 반영 수정하기").click()
    m.wait_for_timeout(1200)
    check("생성 요청: 대기 상태 표시 (가짜 진행률 없음)", "생성 대기 중이에요." in panel.inner_text(), panel.inner_text()[:160])
    check("생성 요청: 중복 클릭 방지 (버튼 비활성)",
          panel.get_by_role("button", name="만드는 중…").is_disabled())
    shot(m, "m05_generating")

    # 5) 생성 중 다른 화면 이동 → Worker 처리 → 돌아오면 완료 (새로고침해도 재호출 없음)
    go(m, "/archive")
    before = drain()
    t_drain = time.monotonic()
    go(m, f"/artworks/{aid}/feedback?stage={sketch['id']}&photo={p1['id']}")
    panel = m.locator("section[aria-label='AI 수정에 반영할 개선사항']")
    check("화면 복귀 후 완료 표시", "AI 수정본이 준비됐어요." in panel.inner_text(), panel.inner_text()[:160])
    timings["e2e_request_to_ready_s"] = round(time.monotonic() - t0, 2)
    m.reload(wait_until="networkidle")
    after = drain()
    check("새로고침해도 이미지 수정 재호출 없음", after["image_calls"] == before["image_calls"] == 1,
          f"{before} {after}")
    revs = httpx.get(f"{API}/artworks/{aid}/stages/{sketch['id']}/ai-revisions", headers=h("student")).json()
    r1 = revs["revisions"][0]
    timings["fake_timings"] = r1["timings"]
    check("API: 고른 1개 개선사항만 스냅샷",
          len(r1["improvements"]) == 1 and r1["improvements"][0]["text"] == kept, f"{kept} / {r1['improvements']}")

    # 6) 비교 화면
    m.locator("section[aria-label='AI 수정에 반영할 개선사항']").get_by_role("link", name="원본과 비교해 보기").click()
    m.wait_for_timeout(1500)
    check("비교: 기본 모드 '비교'", m.get_by_role("tab", name="비교").get_attribute("aria-selected") == "true")
    slider = m.get_by_role("slider", name="원본과 AI 수정작 비교 위치")
    check("비교: 슬라이더 50%에서 시작", slider.get_attribute("aria-valuenow") == "50")
    check("비교: '원본'·'AI 수정작' 라벨", m.locator("text=AI 수정작").count() >= 2)
    box = m.locator("[class*='compare']").first
    bb = box.bounding_box()
    natural = m.evaluate("""() => { const i = document.querySelector('img[alt="원본 작품"]');
        return [i.naturalWidth, i.naturalHeight] }""")
    check("비교: 상자 비율 = 원본 비율 (잘림·왜곡 없음)",
          abs(bb["width"] / bb["height"] - natural[0] / natural[1]) < 0.02, f"{bb} {natural}")
    fit = m.evaluate("""() => [...document.querySelectorAll('[class*=compare] img')]
        .map(i => getComputedStyle(i).objectFit)""")
    check("비교: 두 이미지 모두 contain (늘리지 않음)", fit == ["contain", "contain"], str(fit))
    shot(m, "m06_compare")

    # 터치로 손잡이 끌기 → 비교 위치만 바뀌고 사진은 넘어가지 않음
    y = bb["y"] + bb["height"] * 0.5
    touch_drag(m, bb["x"] + bb["width"] * 0.5, y, bb["x"] + bb["width"] * 0.15)
    v = int(slider.get_attribute("aria-valuenow"))
    check("비교(터치): 손잡이 왼쪽으로 이동", v < 30, str(v))
    check("비교(터치): 사진 페이지 그대로 (1 / 3)", "사진 1 / 3" in page_text(m))
    touch_swipe(m, bb["x"] + bb["width"] * 0.7, y, dx=-250)
    check("비교(터치 스와이프): 이미지 위 가로 스와이프로 사진이 넘어가지 않음", "사진 1 / 3" in page_text(m))
    m.evaluate("window.scrollTo(0, 0)")
    m.wait_for_timeout(300)
    scroll_before = m.evaluate("window.scrollY")
    bb = box.bounding_box()
    touch_swipe(m, bb["x"] + 40, bb["y"] + bb["height"] * 0.6, dy=-240)
    check("비교(터치): 이미지 위 세로 스와이프는 화면 스크롤", m.evaluate("window.scrollY") > scroll_before,
          f"{scroll_before} → {m.evaluate('window.scrollY')}")
    m.evaluate("window.scrollTo(0, 0)")
    m.wait_for_timeout(300)

    # 모드 전환
    m.get_by_role("tab", name="AI 수정작").click()
    m.wait_for_timeout(500)
    check("AI 수정작 모드: 'AI 수정 예시' 표시", m.locator("text=AI 수정 예시").count() >= 1)
    shot(m, "m07_revision_mode")
    m.get_by_role("tab", name="원본").click()
    m.wait_for_timeout(500)
    check("원본 모드: '원본' 배지", m.locator("[class*=badge]", has_text="원본").count() >= 1)
    # 원본 모드에서는 가로 스와이프로 사진 이동
    bb2 = m.locator("[class*=track]").first.bounding_box()
    touch_swipe(m, bb2["x"] + bb2["width"] * 0.8, bb2["y"] + bb2["height"] / 2, dx=-280)
    check("원본 모드(터치 스와이프): 다음 사진으로 이동", "사진 2 / 3" in page_text(m), page_text(m)[:40])
    check("사진 2: 수정본 없음 안내", "아직 생성된 AI 수정본이 없어요." in page_text(m))
    m.get_by_role("button", name="이전 원본 사진").click()
    m.wait_for_timeout(700)
    check("이전 사진 버튼: 사진 1 / 3", "사진 1 / 3" in page_text(m))

    # 개선사항·이력
    imp = m.locator("section[aria-label='수정에 요청한 개선사항']")
    check("요청한 개선사항: 고른 1개만", kept in imp.inner_text() and dropped not in imp.inner_text(),
          imp.inner_text()[:160])
    check("요청한 개선사항: '01.' 번호와 카테고리", "01." in imp.inner_text())

    # 두 번째 버전 (다른 선택) → 이력 2개
    cand = httpx.get(f"{API}/artworks/{aid}/photos/{p1['id']}/ai-revision-candidates", headers=h("student")).json()
    r2 = httpx.post(f"{API}/artworks/{aid}/photos/{p1['id']}/ai-revisions", headers=h("student"),
                    json={"selected_keys": [c["key"] for c in cand["candidates"]]})
    check("API: 다른 선택은 새 버전 (202)", r2.status_code == 202 and r2.json()["version"] == 2)
    same = httpx.post(f"{API}/artworks/{aid}/photos/{p1['id']}/ai-revisions", headers=h("student"),
                      json={"selected_keys": [c["key"] for c in cand["candidates"]]})
    check("API: 같은 요청은 기존 결과 재사용 (200)", same.status_code == 200 and same.json()["id"] == r2.json()["id"])
    m.reload(wait_until="networkidle")
    m.wait_for_timeout(800)
    check("생성 중 새로고침: 상태 유지 (대기)", "생성 대기 중이에요." in page_text(m))
    drain()
    m.wait_for_timeout(5500)  # 화면이 4초마다 상태 확인
    check("상태 확인으로 새 수정본 표시 (v2)", "AI 수정 예시 v2" in page_text(m), page_text(m)[:200])
    m.get_by_role("button", name="수정 이력 보기 (2개)").click()
    m.wait_for_timeout(500)
    items = m.locator("[class*=historyItem]")
    check("수정 이력: 2개 (썸네일·버전·모델)", items.count() == 2 and "gpt-image-2.5-flare" in items.first.inner_text())
    shot(m, "m08_history")
    items.nth(1).get_by_role("button", name="원본과 비교하기").click()
    m.wait_for_timeout(800)
    check("이력에서 v1 선택 → 화면·개선사항 v1로", "AI 수정 예시 v1" in page_text(m))
    m.get_by_role("button", name="수정 이력 보기 (2개)").click()
    m.once("dialog", lambda d: d.accept())
    m.locator("[class*=historyItem]").nth(1).get_by_role("button", name="v1 수정본 삭제").click()
    m.wait_for_timeout(1200)
    check("수정 이력: v1 삭제 후 1개", m.get_by_role("button", name="수정 이력 보기 (1개)").count() == 1)
    detail = httpx.get(f"{API}/artworks/{aid}", headers=h("student")).json()
    check("수정본 삭제 후에도 원본 사진 3장 그대로",
          sum(1 for ph in detail["photos"] if ph["stage_id"] == sketch["id"]) == 3)
    check("AI 수정본 화면: 가로 스크롤 없음", not hscroll(m))

    # 7) 사진 교체 → 새 사진은 수정본 없음, 교체 전 수정본은 이력으로
    new1 = upload("student", aid, sketch["id"], drawing((600, 800), 9), replaces=p1["id"])
    go(m, f"/artworks/{aid}/stages/{sketch['id']}/ai-revisions?photo={new1['id']}")
    check("교체 후: 새 사진은 수정본 없음", "아직 생성된 AI 수정본이 없어요." in page_text(m))
    m.get_by_role("button", name="수정 이력 보기 (1개)").click()
    m.wait_for_timeout(400)
    check("교체 후: 교체 전 사진의 수정본은 이력에", "교체 전 사진의 수정본" in page_text(m))
    shot(m, "m09_after_replace")
    go(m, f"/artworks/{aid}")
    check("아카이브: 개수 반영 'AI 수정본 보기 (1개)'",
          m.get_by_role("link", name="스케치 AI 수정본 보기 1개").count() == 1)
    detail = httpx.get(f"{API}/artworks/{aid}", headers=h("student")).json()
    check("대표·사진 수: AI 수정본 미포함",
          detail["photo_count"] == 3 and detail["cover_photo_id"] in {new1["id"], p2["id"], p3["id"]})
    check("모바일: 화면 오류 없음", not m.errors, str(m.errors[:3]))
    ctx.close()

    # ================================================================== 데스크톱
    ctx, d = ctx_for(browser, "student", mobile=False)
    # 사진 2에 수정본 하나 만들기
    c2 = httpx.get(f"{API}/artworks/{aid}/photos/{p2['id']}/ai-revision-candidates", headers=h("student")).json()
    httpx.post(f"{API}/artworks/{aid}/photos/{p2['id']}/ai-revisions", headers=h("student"),
               json={"selected_keys": [c["key"] for c in c2["candidates"]]})
    drain()
    go(d, f"/artworks/{aid}/stages/{sketch['id']}/ai-revisions?photo={p2['id']}")
    check("데스크톱: 사진 2 / 3 비교 모드", "사진 2 / 3" in page_text(d)
          and d.get_by_role("tab", name="비교").get_attribute("aria-selected") == "true")
    slider = d.get_by_role("slider", name="원본과 AI 수정작 비교 위치")
    bb = d.locator("[class*='compare']").first.bounding_box()
    d.mouse.move(bb["x"] + bb["width"] * 0.5, bb["y"] + bb["height"] * 0.5)
    d.mouse.down()
    d.mouse.move(bb["x"] + bb["width"] * 0.85, bb["y"] + bb["height"] * 0.5, steps=10)
    d.mouse.up()
    d.wait_for_timeout(400)
    v = int(slider.get_attribute("aria-valuenow"))
    check("데스크톱(마우스): 손잡이 오른쪽으로", v > 75, str(v))
    check("데스크톱(마우스): 사진은 그대로 2 / 3", "사진 2 / 3" in page_text(d))
    slider.focus()
    d.keyboard.press("ArrowLeft")
    d.wait_for_timeout(200)
    check("데스크톱(키보드): ←로 5% 이동, 사진 그대로",
          int(slider.get_attribute("aria-valuenow")) == v - 5 and "사진 2 / 3" in page_text(d))
    natural = d.evaluate("""() => { const i = document.querySelector('img[alt="원본 작품"]');
        return [i.naturalWidth, i.naturalHeight] }""")
    check("데스크톱: 가로 원본도 비율 유지", abs(bb["width"] / bb["height"] - natural[0] / natural[1]) < 0.02,
          f"{bb} {natural}")
    shot(d, "d01_compare_landscape")
    d.get_by_role("button", name="다음 원본 사진").click()
    d.wait_for_timeout(700)
    check("데스크톱: 다음 사진 버튼 → 3 / 3 (수정본 없음)", "사진 3 / 3" in page_text(d)
          and "아직 생성된 AI 수정본이 없어요." in page_text(d))
    go(d, f"/artworks/{aid}")
    shot(d, "d02_archive_detail")
    go(d, f"/artworks/{aid}/feedback?stage={sketch['id']}&photo={p2['id']}")
    shot(d, "d03_feedback_panel")
    check("데스크톱: 가로 스크롤 없음", not hscroll(d))
    check("데스크톱: 화면 오류 없음", not d.errors, str(d.errors[:3]))
    ctx.close()

    # ================================================================== 다른 학생
    rid = r1["id"]
    check("다른 학생: 수정본 404", httpx.get(f"{API}/ai-revisions/{rid}", headers=h("other")).status_code == 404)
    check("다른 학생: 단계 목록 404", httpx.get(
        f"{API}/artworks/{aid}/stages/{sketch['id']}/ai-revisions", headers=h("other")).status_code == 404)
    browser.close()

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{passed}/{len(results)} passed")
json.dump({"results": results, "timings": timings}, open(f"{OUT}/results.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
sys.exit(0 if passed == len(results) else 1)
