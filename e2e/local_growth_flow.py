"""v1.0 학생 개인 성장 분석 E2E: 실제 API(로컬) + 로컬 PostgreSQL + 실제 브라우저.

외부 서비스만 로컬 대체 (Supabase 인증 토큰, 저장소, AI는 원문 문장을 그대로 쓰는 가짜 — 실제 호출 없음).
usage: python e2e_growth.py <tokens.json> <out_dir>
"""

import json
import sys
import time

import httpx
from playwright.sync_api import Page, sync_playwright

FRONT = "http://localhost:4175"
API = "http://127.0.0.1:8010/api/v1"
TOK = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = sys.argv[2]
results = []


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


def section(page: Page, title):
    return page.locator("section", has=page.get_by_role("heading", name=title, exact=True))


def hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")


def drain():
    return httpx.post("http://127.0.0.1:8010/__e2e/drain").json()


def artwork_with_feedback(user, title, work_date, body, approve=True):
    art = httpx.post(f"{API}/artworks", headers=h(user),
                     json={"title": title, "practical_type": "DRAWING", "work_date": work_date}).json()
    note = httpx.post(f"{API}/artworks/{art['id']}/feedback-notes", headers=h(user),
                      json={"source": "INSTRUCTOR", "body": body, "request_summary": True}).json()
    drain()
    fid = httpx.get(f"{API}/feedback-notes/{note['id']}", headers=h(user)).json()["feedback_id"]
    if approve:
        fb = httpx.get(f"{API}/feedbacks/{fid}", headers=h(user)).json()
        r = httpx.post(f"{API}/feedbacks/{fid}/approve", headers=h(user), json={"version": fb["version"]})
        assert r.status_code == 200, r.text
    return art["id"], fid


with sync_playwright() as p:
    b = p.chromium.launch()
    sctx, student = ctx_for(b, "student")

    # --- 학생 가입 (학생 전용: 유형 선택 없음) ------------------------------------------
    go(student, "/onboarding")
    check("온보딩에 강사 선택 없음 (학생 전용)", student.get_by_text("강사·원장").count() == 0)
    student.get_by_label("공개 닉네임").fill("성장E2E")
    student.get_by_role("button", name="다음").click()
    student.wait_for_timeout(1200)
    me = httpx.get(f"{API}/users/me", headers=h("student")).json()
    check("학생 프로필 생성", me.get("user_type") == "STUDENT", str(me.get("user_type")))
    httpx.patch(f"{API}/users/me", headers=h("student"), json={"practical_type": "DRAWING"})
    httpx.post(f"{API}/ai-processing-consents", headers=h("student"),
               json={"policy_version": "2026-12-ai-v2", "agreed": True, "birth_year_month": "2000-01"})

    # --- 데이터 부족 상태 (확정 첨삭 0) --------------------------------------------------
    go(student, "/archive?tab=report")
    check("데이터 부족 안내", student.get_by_text("작품 하나부터 차근차근").count() > 0
          or student.get_by_text("첨삭을 확정하면 분석이 시작돼요").count() > 0)

    # --- 첨삭 기록 4개 (이전 2: 4문장, 최근 2: 2문장) ----------------------------------
    long_notes = [
        ("9월 정물", "2026-09-10", "구도가 안정적으로 잡혔다. 컵의 명암 대비가 약하다. 비례를 다시 재서 고쳐라. 다음에는 큰 덩어리부터 먼저 잡아라."),
        ("10월 정물", "2026-10-08", "화면 구도가 좋다. 그림자 쪽 명암이 너무 밝다. 병의 비례가 길어 보인다. 다음 작품은 비례를 십자선으로 확인해라."),
    ]
    short_notes = [
        ("10월 석고", "2026-10-25", "구도가 차분하다. 명암 단계가 부족하다."),
        ("11월 석고", "2026-11-12", "구도 배치가 좋아졌다. 어두운 면 명암이 약하다."),
    ]
    ids = [artwork_with_feedback("student", *n) for n in long_notes + short_notes]
    analysis = httpx.get(f"{API}/growth/me/weaknesses", headers=h("student")).json()
    by_tag = {t["tag"]: t for t in analysis["tags"]}
    check("API: 9개 태그 반복 실수 (명암 4작품)", by_tag["VALUE"]["weakness_artwork_count"] == 4)
    check("API: 형태·비례 이전 2 → 최근 0 (덜 언급됨)", by_tag["FORM_PROPORTION"]["trend"] == "LESS_FREQUENT",
          by_tag["FORM_PROPORTION"]["trend"])
    check("API: 첨삭 분량 차이 주의", any("항목 수가 적어요" in c for c in analysis["comparison_context"]["cautions"]),
          str(analysis["comparison_context"]))
    check("API: 최근 연습 과제 2개", len(analysis["practice_tips"]) == 2)
    check("API: 기간별 첨삭 횟수", [b["feedback_count"] for b in analysis["timeline"]] == [1, 2, 1],
          str([(b["bucket_start"], b["feedback_count"]) for b in analysis["timeline"]]))

    # --- 분석 리포트 화면 (모바일) -------------------------------------------------------
    go(student, "/archive?tab=report")
    stats = section(student, "학습 기록 요약").inner_text()
    check("요약: 기록된 작품·누적 첨삭", "4점" in stats and "4건" in stats, stats.replace("\n", " | "))
    check("요약: 최근 활동", "최근 활동" in stats and "11월 석고" in stats)
    mistakes = section(student, "반복 실수 (9개 항목)").inner_text()
    check("반복 실수: 명암·형태·비례 (9개 태그 라벨)", "명암" in mistakes and "형태·비례" in mistakes, mistakes.replace("\n", " | "))
    compare = section(student, "과거와 최근 피드백 비교").inner_text()
    check("과거·최근 비교: 덜 언급됨", "덜 언급됨" in compare)
    check("과거·최근 비교: 실력 향상 단정 금지 안내", "실력이 늘었다는 뜻은 아니에요" in compare)
    check("과거·최근 비교: 첨삭 분량 주의", "항목 수가 적어요" in compare)
    bars = section(student, "항목별 잘한 점·개선할 점").inner_text()
    check("항목별 강점·약점: 구도(잘한 점) 포함", "구도" in bars and "명암" in bars)
    period = section(student, "기간별 첨삭 횟수").locator("li").count()
    check("기간별 첨삭 횟수 막대 3개", period == 3, str(period))
    check("핵심 한 줄 요약: 9개 태그 라벨", "명암" in section(student, "핵심 한 줄 요약").inner_text())

    tips = section(student, "최근 연습 과제")
    check("최근 연습 과제 2개 표시", tips.locator("li").count() == 2)
    check("연습 과제: 반복 실수 관련 표시", tips.get_by_text("반복 실수 관련").count() >= 1)
    student.screenshot(path=f"{OUT}/growth-mobile.png", full_page=True)
    tips.get_by_role("button", name="연습 과제로 담기").first.click()
    student.wait_for_timeout(1500)
    tips = section(student, "최근 연습 과제")
    check("연습 과제로 담기 → 체크 표시", tips.get_by_text("연습했으면 체크").count() == 1)
    tips.get_by_text("연습했으면 체크").click()
    student.wait_for_timeout(1500)
    tips = section(student, "최근 연습 과제")
    check("완료 체크 → 연습 완료", tips.get_by_text("연습 완료").count() == 1)
    recs = httpx.get(f"{API}/growth/me/recommendations?scope=PERSONAL&limit=50", headers=h("student")).json()["items"]
    check("완료 기록 저장 (기존 맞춤 과제와 같은 기록)", [r["status"] for r in recs] == ["COMPLETED"], str([r["status"] for r in recs]))
    check("모바일 가로 스크롤 없음 (분석 리포트)", not hscroll(student))
    tip_id = analysis["practice_tips"][0]["tip"]["item_id"]

    # --- 다른 학생: 데이터 격리 ---------------------------------------------------------
    httpx.post(f"{API}/users/me", headers=h("other"), json={"display_name": "다른학생", "user_type": "STUDENT"})
    httpx.patch(f"{API}/users/me", headers=h("other"), json={"practical_type": "DRAWING"})
    other_analysis = httpx.get(f"{API}/growth/me/weaknesses", headers=h("other")).json()
    check("다른 학생 분석에 내 데이터 없음", other_analysis["tags"] == [] and other_analysis["practice_tips"] == []
          and other_analysis["totals"]["artwork_count"] == 0)
    check("다른 학생이 내 연습 과제 담기 → 404",
          httpx.post(f"{API}/growth/me/practice-tips/{tip_id}/task", headers=h("other")).status_code == 404)
    check("다른 학생이 내 첨삭 → 404", httpx.get(f"{API}/feedbacks/{ids[0][1]}", headers=h("other")).status_code == 404)
    octx, other = ctx_for(b, "other")
    go(other, "/archive?tab=report")
    check("다른 학생 화면: 데이터 부족 상태", other.get_by_text("작품 하나부터 차근차근").count() > 0)

    # --- 기존 학생 기능 회귀 ----------------------------------------------------------
    go(student, f"/artworks/{ids[0][0]}")
    check("작품 상세 화면", student.get_by_text("9월 정물").count() > 0)
    go(student, f"/feedbacks/{ids[0][1]}")
    check("첨삭 결과 화면 (확정됨 + 태그)", student.get_by_text("확정됨").count() > 0
          and student.locator("ul[aria-label='첨삭 분류'] li").count() >= 2)
    go(student, "/home")
    check("홈 화면", "/home" in student.url)
    go(student, "/growth/recommendations")
    check("맞춤 연습 과제 화면에 담은 과제", student.get_by_text("큰 덩어리부터").count() > 0
          or student.get_by_text("십자선").count() > 0)

    dctx, desk = ctx_for(b, "student", mobile=False)
    go(desk, "/archive?tab=report")
    check("데스크톱 가로 스크롤 없음", not hscroll(desk))
    errs = {n: pg.errors for n, pg in (("student", student), ("other", other), ("desk", desk)) if pg.errors}
    check("페이지 오류·5xx 없음", not errs, str(errs)[:300])
    b.close()

fails = [r for r in results if not r[1]]
print(f"\nPASS {len(results) - len(fails)} / FAIL {len(fails)}")
sys.exit(1 if fails else 0)
