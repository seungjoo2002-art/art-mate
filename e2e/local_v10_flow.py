"""v1.0 full-stack E2E: real API (local) + real browser. Auth provider/storage/LLM are local fakes."""

import json
import subprocess
import sys
import time

import httpx
from playwright.sync_api import Page, sync_playwright

FRONT = "http://localhost:4175"
API = "http://127.0.0.1:8010/api/v1"
TOK = json.load(open(sys.argv[1], encoding="utf-8"))
DB = sys.argv[2]
OUT = sys.argv[3]
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def h(user):
    return {"Authorization": f"Bearer {TOK[user]['token']}"}


def sql(query, *args):
    """로컬 E2E DB에만 실행 (백엔드 가상환경의 asyncpg)."""
    code = ";".join([
        "import asyncio,asyncpg,sys,json",
        "f=lambda: asyncpg.connect(%r)" % DB,
    ]) + chr(10) + chr(10).join([
        "async def m():",
        "    c = await f()",
        "    await c.execute(%r, *json.loads(sys.argv[1]))" % query,
        "    await c.close()",
        "asyncio.run(m())",
    ])
    subprocess.run(["uv", "run", "python", "-c", code, json.dumps(list(args))], check=True,
                   cwd=sys.argv[4])



def session(user):
    t = TOK[user]
    return {
        "access_token": t["token"],
        "refresh_token": "e2e",
        "expires_at": t["exp"],
        "expires_in": t["exp"] - int(time.time()),
        "token_type": "bearer",
        "user": {"id": t["id"], "aud": "authenticated", "role": "authenticated", "email": f"{user}@e2e.invalid",
                 "app_metadata": {}, "user_metadata": {}, "created_at": "2026-11-16T00:00:00Z"},
    }


def ctx_for(browser, user, mobile=False):
    size = {"width": 390, "height": 844} if mobile else {"width": 1366, "height": 900}
    ctx = browser.new_context(viewport=size, is_mobile=mobile, locale="ko-KR", timezone_id="Asia/Seoul")
    ctx.add_init_script(
        f"localStorage.setItem('sb-e2e-project-auth-token', {json.dumps(json.dumps(session(user)))})"
    )
    ctx.route(
        "**/e2e-project.supabase.co/**",
        lambda r: r.fulfill(status=200, content_type="application/json", body="{}",
                            headers={"access-control-allow-origin": "*", "access-control-allow-headers": "*"}),
    )
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)[:200]))
    page.on("response", lambda r: page.errors.append(f"{r.status} {r.url[-80:]}") if r.status >= 500 else None)
    return ctx, page


def go(page: Page, path):
    page.goto(FRONT + path, wait_until="networkidle")
    page.wait_for_timeout(500)


def onboard(page: Page, nickname, role_label):
    go(page, "/onboarding")
    page.get_by_role("tab", name=role_label).click()
    page.get_by_label("공개 닉네임").fill(nickname)
    page.get_by_role("button", name="다음").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)


def hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")


with sync_playwright() as p:
    b = p.chromium.launch()
    ctxs = {}
    pages = {}
    for user in ("owner", "admin", "student", "teacher2", "other"):
        ctxs[user], pages[user] = ctx_for(b, user)
    owner, admin, student, teacher2, other = (pages[k] for k in ("owner", "admin", "student", "teacher2", "other"))

    # --- 1. 역할별 가입 ---------------------------------------------------------------
    onboard(owner, "원장E2E", "강사·원장")
    check("강사 가입 → 강사 첫 화면", owner.url.endswith("/instructor") or "/instructor" in owner.url, owner.url)
    check("승인 전 강사: 학원 연결 안내", owner.get_by_text("학원을 연결해 주세요").count() > 0)
    me = httpx.get(f"{API}/users/me", headers=h("owner")).json()
    check("강사 프로필 user_type", me["user_type"] == "INSTRUCTOR", me["user_type"])

    onboard(student, "학생E2E", "학생")
    # 학생은 실기 유형 설정(/setup) 후 홈
    check("학생 가입 → 학생 영역(/setup)", "/setup" in student.url, student.url)
    httpx.patch(f"{API}/users/me", headers=h("student"), json={"practical_type": "DRAWING"})
    httpx.post(f"{API}/users/me", headers=h("other"), json={"display_name": "다른학생", "user_type": "STUDENT", "practical_type": "DRAWING"})
    httpx.patch(f"{API}/users/me", headers=h("other"), json={"practical_type": "DRAWING"})
    onboard(teacher2, "강사E2E", "강사·원장")

    # 관리자: API로는 만들 수 없음 → 로컬 DB에서 지정 (운영과 같은 방식)
    httpx.post(f"{API}/users/me", headers=h("admin"), json={"display_name": "운영자", "user_type": "STUDENT"})
    sql("UPDATE profiles SET user_type='ADMIN' WHERE id=$1::uuid", TOK["admin"]["id"])

    # 역할 영역 분리
    go(student, "/instructor")
    check("학생이 강사 화면 접근 → 학생 홈으로", "/instructor" not in student.url, student.url)
    go(owner, "/home")
    check("강사가 학생 화면 접근 → 강사 화면으로", "/instructor" in owner.url, owner.url)
    go(teacher2, "/admin/academies")
    check("강사가 관리자 화면 접근 차단", "/admin" not in teacher2.url, teacher2.url)

    # --- 2. 학원 등록 신청 → 승인 -----------------------------------------------------
    go(owner, "/instructor")
    owner.get_by_label("학원 이름").last.fill("E2E 미술학원")
    owner.get_by_role("button", name="등록 신청").click()
    owner.wait_for_timeout(1500)
    check("학원 등록 신청 → 승인 대기 표시", owner.get_by_text("승인 대기").count() > 0)
    academy_id = httpx.get(f"{API}/academies?mine=true", headers=h("owner")).json()["items"][0]["id"]
    go(owner, f"/instructor/academies/{academy_id}")
    check("승인 전 학원 화면 차단 (UI)", owner.get_by_text("이 학원의 강사 화면을 열 수 없어요").count() > 0)
    r = httpx.post(f"{API}/academies/{academy_id}/join-requests", headers=h("student"), json={})
    check("승인 전 학원에는 소속 신청 불가 (API)", r.status_code >= 400, str(r.status_code))

    go(admin, "/admin/academies")
    admin.get_by_role("button", name="승인").first.click()
    admin.wait_for_timeout(1200)
    st = httpx.get(f"{API}/academies/{academy_id}", headers=h("owner")).json()["status"]
    check("관리자 승인 → ACTIVE", st == "ACTIVE", st)

    go(owner, "/instructor")
    check("승인 후 강사 대시보드로", f"/instructor/academies/{academy_id}" in owner.url, owner.url)
    check("대시보드 학원 이름", owner.get_by_role("heading", name="E2E 미술학원").count() > 0)

    # --- 3. 학생·강사 소속 신청 → 승인 → 반 배정 -------------------------------------
    for page, name in ((student, "학생"), (teacher2, "강사")):
        go(page, "/my/academies" if page is student else "/instructor")
        page.get_by_label("학원 이름").first.fill("E2E")
        page.get_by_role("button", name="찾기").click()
        page.wait_for_timeout(800)
        page.get_by_role("button", name="소속 신청").first.click()
        page.wait_for_timeout(1000)
        check(f"{name} 소속 신청", page.get_by_text("신청함").count() > 0 or page.get_by_text("승인을 기다리고 있어요").count() > 0)
    go(teacher2, "/instructor")
    check("소속 승인 전 강사: 대기 화면", teacher2.get_by_text("승인을 기다리고 있어요").count() > 0)

    go(owner, f"/instructor/academies/{academy_id}/manage?tab=requests")
    for _ in range(2):
        owner.get_by_role("button", name="승인", exact=True).first.click()
        owner.wait_for_timeout(1000)
    members = httpx.get(f"{API}/academies/{academy_id}/members", headers=h("owner")).json()["items"]
    roles = sorted(m["role"] for m in members)
    check("소속 승인 → 멤버", roles == ["INSTRUCTOR", "OWNER", "STUDENT"], str(roles))

    go(owner, f"/instructor/academies/{academy_id}/manage")
    owner.get_by_label("반 이름").fill("E2E 입시반")
    owner.get_by_role("button", name="반 만들기").click()
    owner.wait_for_timeout(1000)
    owner.get_by_text("E2E 입시반").first.click()
    owner.wait_for_load_state("networkidle")
    owner.wait_for_timeout(800)
    for who in ("강사E2E", "학생E2E"):  # 담당 강사 + 학생 (해당 줄의 배정 버튼)
        owner.locator("li", has_text=who).get_by_role("button", name="배정", exact=True).first.click()
        owner.wait_for_timeout(1000)
    class_id = owner.url.rstrip("/").split("/")[-1]
    cm = httpx.get(f"{API}/academies/{academy_id}/classes/{class_id}/members", headers=h("owner")).json()["items"]
    check("반 배정 (담당 강사 + 학생)", sorted(m["role"] for m in cm if m["status"] == "ACTIVE") == ["INSTRUCTOR", "STUDENT"],
          str([(m["display_name"], m["role"]) for m in cm]))

    # --- 4. 학생 작품(학원·반 연결) + 강사 첨삭 기록 + AI 정리 --------------------------
    go(student, "/artworks/new")
    student.get_by_label("작품명").fill("E2E 유리컵 정물")
    student.get_by_label("학원 (선택)").select_option(label="E2E 미술학원")
    student.wait_for_timeout(800)
    student.get_by_label("반 (선택)").select_option(label="E2E 입시반")
    student.get_by_role("button", name="작품 기록 시작하기").click()
    student.wait_for_url(lambda u: "/artworks/" in u and not u.rstrip("/").endswith("/new"), timeout=15000)
    artwork_id = student.url.rstrip("/").split("/")[-1]
    art = httpx.get(f"{API}/artworks/{artwork_id}", headers=h("student")).json()
    check("작품이 학원·반에 연결", art["academy_id"] == academy_id and art["class_id"] == class_id)

    httpx.post(f"{API}/ai-processing-consents", headers=h("student"),
               json={"policy_version": "2026-12-ai-v2", "agreed": True, "birth_year_month": "2000-01"})
    go(student, f"/artworks/{artwork_id}/notes/new")
    student.get_by_role("radio", name="강사 첨삭").click() if student.get_by_role("radio", name="강사 첨삭").count() else None
    student.get_by_label("첨삭 내용").fill(
        "구도는 화면 중앙에 안정적으로 잘 잡았다. 오른쪽 컵의 명암이 약해 형태가 떠 보인다. "
        "어두운 면을 한 톤 더 눌러 덩어리감을 살려라. 다음에는 큰 형태부터 먼저 잡아라."
    )
    box = student.get_by_text("저장하고 AI로 정리하기")
    if box.count():
        cb = student.locator("input[type=checkbox]").first
        if not cb.is_checked():
            box.click()
    student.get_by_role("button", name="저장하기").click()
    student.wait_for_timeout(1500)
    drained = httpx.post("http://127.0.0.1:8010/__e2e/drain").json()
    check("AI 정리 작업 처리 (가짜 AI, 실제 호출 없음)", drained["processed"] >= 1, str(drained))

    # --- 5. 강사: 대시보드 → 검토 → 승인 ----------------------------------------------
    t2 = teacher2
    go(t2, "/instructor")
    check("담당 강사 대시보드", f"/instructor/academies/{academy_id}" in t2.url, t2.url)
    check("검토 대기 1건 이상", t2.get_by_text("E2E 유리컵 정물").count() > 0)
    go(t2, f"/instructor/academies/{academy_id}/artworks")
    check("담당 학생 작품 목록", t2.get_by_text("E2E 유리컵 정물").count() > 0)
    t2.get_by_text("E2E 유리컵 정물").first.click()
    t2.wait_for_load_state("networkidle")
    t2.wait_for_timeout(800)
    check("작품 상세: 단계 표시", t2.get_by_role("heading", name="스케치").count() > 0)
    check("작품 상세: 이 작품의 첨삭", t2.get_by_text("글 첨삭").count() > 0)
    t2.get_by_text("글 첨삭").first.click()
    t2.wait_for_load_state("networkidle")
    t2.wait_for_timeout(800)
    check("검토 화면: 원문 전체", t2.get_by_text("큰 형태부터 먼저 잡아라").count() > 0)
    chips = t2.locator("ul[aria-label='첨삭 분류'] li").all_inner_texts()
    labels = [c.split("\n")[0] for c in chips]
    check("검토 화면: 9개 태그 체계로 표시", set(labels) <= {"구도", "형태·비례", "명암", "색채", "원근·공간감", "질감·표현", "완성도", "시간 관리", "기타"} and len(labels) >= 2, str(labels))
    t2.screenshot(path=f"{OUT}/review-desktop.png", full_page=True)
    t2.get_by_role("button", name="승인하기").click()
    t2.wait_for_timeout(1500)
    check("강사 승인 → 승인됨", t2.get_by_text("승인됨").count() > 0)
    fid = t2.url.rstrip("/").split("/")[-1]

    # --- 6. 학생: 승인 결과 확인 ----------------------------------------------------
    go(student, f"/feedbacks/{fid}")
    check("학생 화면: 확정됨", student.get_by_text("확정됨").count() > 0)
    check("학생 화면: 선생님 확인 안내", student.get_by_text("선생님이 확인한 정리예요").count() > 0)
    check("학생 화면: 태그", student.locator("ul[aria-label='첨삭 분류'] li").count() >= 2)

    # --- 7. 보안·격리 (실제 API) ----------------------------------------------------
    codes = {
        "다른 학생 → 학원 작품 목록": httpx.get(f"{API}/academies/{academy_id}/artworks", headers=h("other")).status_code,
        "다른 학생 → 첨삭 상세": httpx.get(f"{API}/feedbacks/{fid}", headers=h("other")).status_code,
        "다른 학생 → 작품": httpx.get(f"{API}/artworks/{artwork_id}", headers=h("other")).status_code,
        "학생 → 강사 검토 API": httpx.get(f"{API}/academies/{academy_id}/feedbacks", headers=h("student")).status_code,
        "강사 → 반 생성(원장·관리자 전용)": httpx.post(f"{API}/academies/{academy_id}/classes", headers=h("teacher2"), json={"name": "x"}).status_code,
        "강사 → 관리자 API": httpx.get(f"{API}/admin/academies", headers=h("teacher2")).status_code,
        "원장 → 관리자 API": httpx.get(f"{API}/admin/academies", headers=h("owner")).status_code,
    }
    for name, code in codes.items():
        check(f"차단: {name}", code in (403, 404), str(code))

    # --- 8. 모바일 화면 -------------------------------------------------------------
    mctx, mobile = ctx_for(b, "teacher2", mobile=True)
    for path in (f"/instructor/academies/{academy_id}", f"/instructor/academies/{academy_id}/feedbacks/{fid}",
                 f"/instructor/academies/{academy_id}/manage"):
        go(mobile, path)
        check(f"모바일 가로 스크롤 없음 {path.split(academy_id)[-1] or '/'}", not hscroll(mobile))
    mobile.screenshot(path=f"{OUT}/manage-mobile.png", full_page=True)
    go(mobile, f"/instructor/academies/{academy_id}")
    mobile.screenshot(path=f"{OUT}/dashboard-mobile.png", full_page=True)
    sctx, smobile = ctx_for(b, "student", mobile=True)
    go(smobile, "/my/academies")
    check("학생 모바일 내 학원 가로 스크롤 없음", not hscroll(smobile))
    smobile.screenshot(path=f"{OUT}/student-academies-mobile.png", full_page=True)
    go(owner, f"/instructor/academies/{academy_id}")
    owner.screenshot(path=f"{OUT}/dashboard-desktop.png", full_page=True)

    errs = {k: v.errors for k, v in {**pages, "mobile": mobile, "smobile": smobile}.items() if v.errors}
    check("페이지 오류·5xx 없음", not errs, str(errs)[:400])
    b.close()

fails = [r for r in results if not r[1]]
print(f"\nPASS {len(results) - len(fails)} / FAIL {len(fails)}")
sys.exit(1 if fails else 0)
