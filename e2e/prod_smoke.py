"""ART MATE 운영 사이트 실사용 점검 (Playwright, Python).

실제 브라우저로 로그인하고, 그 브라우저 세션의 토큰으로 운영 API·Storage를 그대로 호출한다.
Mock 없음: 성공하면 실제 운영 DB·Storage에 기록된 것이다.

계정은 환경변수로만 받는다 (명령줄·파일에 비밀번호를 남기지 않음):
  ARTMATE_STUDENT_EMAIL / ARTMATE_STUDENT_PASSWORD      (필수)

모드
  (기본)   읽기 전용: 로그인 → 역할별 화면 순회(데스크톱·모바일) → 조회 API. 아무것도 만들지 않는다.
  --write  테스트 작품 "[E2E] …" 생성 → 단계 사진 업로드(실제 Storage) → 글 첨삭 → 상세 화면 확인
           → 끝나면 그 작품을 삭제 (--keep 이면 남김). 기존 데이터는 건드리지 않는다.
  --stt    (--write 필요) 녹음 업로드 → 서버 STT 요청 → 완료까지 대기 시간 측정.
           계정에 녹음 동의가 이미 있어야 한다 (스크립트가 동의를 대신 하지 않음).
           --audio 로 음성 파일(wav/webm/mp3/m4a/ogg)을 지정. 말소리가 있어야 전사문이 나온다.

예)  python -X utf8 e2e/prod_smoke.py --write --stt --audio sample.wav --out e2e-out
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import struct
import sys
import time
import wave
import zlib
from pathlib import Path

from playwright.sync_api import APIRequestContext, Browser, Page, sync_playwright

FRONT = os.environ.get("ARTMATE_FRONT_URL", "https://art-mate-two.vercel.app")
API = os.environ.get("ARTMATE_API_URL", "https://art-mate-dwc9.onrender.com") + "/api/v1"
VIEWPORTS = {"desktop": {"width": 1280, "height": 800}, "mobile": {"width": 390, "height": 844}}
COMMON_PAGES = ["/home", "/archive", "/practice", "/community", "/my", "/my/edit", "/notifications"]
STUDENT_PAGES = [*COMMON_PAGES, "/growth/reports", "/growth/recommendations", "/artworks/new"]

results: list[dict] = []


def record(area: str, check: str, ok: bool | None, detail: str = "", kind: str = "real") -> None:
    """ok=None 은 건너뜀(미검증). kind: real(운영 실제 호출) / browser(실제 화면)."""
    status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    results.append({"area": area, "check": check, "status": status, "kind": kind, "detail": detail})
    print(f"[{status}] {area} · {check} {('- ' + detail) if detail else ''}", flush=True)


# ----------------------------------------------------------------------------- 테스트 파일


def make_png(size: int = 96) -> bytes:
    """외부 라이브러리 없이 만든 RGB PNG (그라데이션)."""
    raw = b"".join(
        b"\x00" + bytes(v for x in range(size) for v in (x * 2 % 256, y * 2 % 256, 160)) for y in range(size)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(tag + data))
        return struct.pack(">I", len(data)) + tag + data + crc

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


def audio_duration_ms(path: Path) -> int:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path)) as w:
            return int(w.getnframes() / w.getframerate() * 1000)
    return int(os.environ.get("ARTMATE_AUDIO_DURATION_MS", "10000"))


# ----------------------------------------------------------------------------- 브라우저


def login(browser: Browser, email: str, password: str, viewport: str) -> tuple[Page, str | None]:
    ctx = browser.new_context(viewport=VIEWPORTS[viewport], is_mobile=viewport == "mobile", locale="ko-KR")
    page = ctx.new_page()
    page.goto(f"{FRONT}/login", wait_until="networkidle")
    page.locator("input[type=email]").fill(email)
    page.locator("input[type=password]").fill(password)
    page.locator("button[type=submit]").first.click()
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
    except Exception:
        return page, None
    page.wait_for_load_state("networkidle")
    token = page.evaluate(
        """() => { for (const k of Object.keys(localStorage)) if (/^sb-.*-auth-token$/.test(k)) {
             try { return JSON.parse(localStorage.getItem(k)).access_token } catch (e) {} } return null }"""
    )
    return page, token


def visit(page: Page, path: str, area: str, viewport: str, out: Path | None) -> None:
    errors: list[str] = []
    bad: list[str] = []
    on_console = lambda m: errors.append(m.text[:200]) if m.type == "error" else None  # noqa: E731
    on_pageerror = lambda e: errors.append("PAGEERROR " + str(e)[:200])  # noqa: E731
    on_response = (  # noqa: E731
        lambda r: (
            bad.append(f"{r.status} {r.request.method} {r.url.split('?')[0][-90:]}")
            if r.status >= 400 and ("onrender" in r.url or "supabase" in r.url)
            else None
        )
    )
    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)
    try:
        page.goto(FRONT + path, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        final = page.url.replace(FRONT, "")
        hscroll = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        server_err = [b for b in bad if b.startswith("5")]
        ok = not server_err and not any(e.startswith("PAGEERROR") for e in errors) and not hscroll
        detail = f"→ {final}" if final != path else ""
        if bad:
            detail += f" http={bad[:4]}"
        if errors:
            detail += f" console={errors[:2]}"
        if hscroll:
            detail += " 가로스크롤"
        record(area, f"{viewport} {path}", ok, detail.strip(), kind="browser")
        if out:
            page.screenshot(path=str(out / f"{area}-{viewport}{path.replace('/', '_')}.png"), full_page=True)
    finally:
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)


# ----------------------------------------------------------------------------- API


def api_ctx(pw, token: str) -> APIRequestContext:
    return pw.request.new_context(extra_http_headers={"Authorization": f"Bearer {token}"}, timeout=90000)


def check_get(api: APIRequestContext, area: str, path: str) -> dict | list | None:
    res = api.get(API + path)
    ok = res.status < 400
    record(area, f"GET {path}", ok, "" if ok else f"{res.status} {res.text()[:160]}")
    return res.json() if ok and "json" in res.headers.get("content-type", "") else None


def storage_put(api: APIRequestContext, upload: dict, data: bytes, content_type: str) -> int:
    # supabase-js uploadToSignedUrl 과 같은 요청 (upload.url = 서명된 업로드 URL)
    res = api.put(upload["url"], data=data, headers={"Content-Type": content_type, "x-upsert": "false"})
    return res.status


def student_write_flow(pw, api: APIRequestContext, page: Page, args, out: Path | None) -> None:
    area = "학생-쓰기"
    stamp = dt.datetime.now().strftime("%m%d-%H%M%S")
    res = api.post(
        f"{API}/artworks", data={"title": f"[E2E] 운영 점검 {stamp}", "topic": "자동 점검용 (삭제 예정)"}
    )
    record(
        area,
        "작품 생성 POST /artworks",
        res.status == 201,
        f"{res.status} {res.text()[:160]}" if res.status != 201 else "",
    )
    if res.status != 201:
        return
    artwork = res.json()
    aid = artwork["id"]
    try:
        stages = artwork.get("stages") or []
        stage_id = stages[0]["id"] if stages else None
        png = make_png()
        res = api.post(
            f"{API}/artworks/{aid}/photos",
            data={
                "content_type": "image/png",
                "file_size": len(png),
                "file_name": "e2e.png",
                "kind": "STAGE",
                "stage_id": stage_id,
            },
        )
        record(
            area,
            "사진 업로드 요청",
            res.status == 201,
            "" if res.status == 201 else f"{res.status} {res.text()[:160]}",
        )
        if res.status == 201:
            ticket = res.json()
            st = storage_put(api, ticket["upload"], png, "image/png")
            record(area, "Storage 업로드 (실제 Supabase)", st in (200, 201), f"HTTP {st}")
            res = api.post(f"{API}/artworks/{aid}/photos/{ticket['photo']['id']}/complete")
            record(
                area,
                "사진 업로드 완료",
                res.status == 200,
                "" if res.status == 200 else f"{res.status} {res.text()[:160]}",
            )
            res = api.get(f"{API}/artworks/{aid}/photos/{ticket['photo']['id']}/url")
            record(area, "사진 조회 URL", res.status == 200, "" if res.status == 200 else str(res.status))
        body = "명암 대비를 조금 더 강하게, 유리컵 하이라이트를 살려 보세요. (E2E 점검)"
        res = api.post(
            f"{API}/artworks/{aid}/feedback-notes",
            data={"source": "INSTRUCTOR", "body": body, "stage_id": stage_id},
        )
        record(
            area,
            "글 첨삭 작성",
            res.status == 201,
            "" if res.status == 201 else f"{res.status} {res.text()[:160]}",
        )
        check_get(api, area, f"/artworks/{aid}/feedback-notes")
        visit(page, f"/artworks/{aid}", area, "desktop", out)
        has_note = page.get_by_text("유리컵 하이라이트", exact=False).count() > 0
        record(area, "상세 화면에 첨삭 표시", has_note, kind="browser")
        if args.stt:
            stt_flow(api, aid, stage_id, args)
    finally:
        if args.keep:
            record(area, "정리", None, f"--keep: 작품 {aid} 남김")
        else:
            res = api.delete(f"{API}/artworks/{aid}")
            record(area, "테스트 작품 삭제", res.status == 204, str(res.status))


def stt_flow(api: APIRequestContext, aid: str, stage_id: str | None, args) -> None:
    area = "STT"
    consent = api.get(f"{API}/recording-consents/me")
    cj = consent.json() if consent.status == 200 else {}
    if not cj.get("is_valid"):
        record(area, "녹음 동의", None, "유효한 녹음 동의 없음 → 녹음 단계 건너뜀 (앱에서 먼저 동의)")
        return
    if not args.audio:
        record(area, "녹음 파일", None, "--audio 미지정")
        return
    audio = Path(args.audio)
    data = audio.read_bytes()
    ctype = mimetypes.guess_type(audio.name)[0] or "audio/wav"
    ctype = {"audio/x-wav": "audio/wav", "audio/wave": "audio/wav"}.get(ctype, ctype)
    res = api.post(
        f"{API}/artworks/{aid}/recordings",
        data={
            "content_type": ctype,
            "file_size": len(data),
            "duration_ms": audio_duration_ms(audio),
            "file_name": audio.name,
            "stage_id": stage_id,
            "speaker_notice_confirmed": True,
        },
    )
    record(
        area,
        "녹음 업로드 요청",
        res.status == 201,
        "" if res.status == 201 else f"{res.status} {res.text()[:200]}",
    )
    if res.status != 201:
        return
    ticket = res.json()
    rid = ticket["recording"]["id"]
    record(area, "녹음 Storage 업로드", storage_put(api, ticket["upload"], data, ctype) in (200, 201))
    res = api.post(f"{API}/artworks/{aid}/recordings/{rid}/complete")
    record(
        area,
        "녹음 업로드 완료",
        res.status == 200,
        "" if res.status == 200 else f"{res.status} {res.text()[:160]}",
    )
    t0 = time.monotonic()
    res = api.post(
        f"{API}/artworks/{aid}/recordings/{rid}/transcription", data={"auto_summarize": args.summary}
    )
    record(area, "서버 STT 요청", res.status in (200, 201, 202), f"{res.status} {res.text()[:160]}")
    status = None
    while time.monotonic() - t0 < args.stt_timeout:
        time.sleep(15)
        st = api.get(f"{API}/artworks/{aid}/recordings/{rid}/transcription")
        status = st.json().get("transcription_status") if st.status == 200 else f"HTTP {st.status}"
        if status in ("COMPLETED", "FAILED"):
            break
    waited = int(time.monotonic() - t0)
    record(area, "서버 STT 완료", status == "COMPLETED", f"status={status}, {waited}s 소요")
    tr = api.get(f"{API}/artworks/{aid}/recordings/{rid}/transcript")
    if tr.status == 200:
        text = json.dumps(tr.json(), ensure_ascii=False)
        record(area, "전사문 조회", True, text[:120])
    if args.summary:
        sm = api.get(f"{API}/artworks/{aid}/recordings/{rid}/summary")
        record("AI요약", "요약 조회 (실제 OpenAI)", sm.status == 200, f"{sm.status} {sm.text()[:200]}")


# ----------------------------------------------------------------------------- main


def run_role(pw, browser: Browser, role: str, email: str, password: str, args, out: Path | None) -> None:
    for vp in ("desktop", "mobile"):
        page, token = login(browser, email, password, vp)
        record(
            role,
            f"{vp} 로그인",
            token is not None,
            "" if token else f"로그인 실패, url={page.url}",
            kind="browser",
        )
        if not token:
            page.context.close()
            continue
        pages = STUDENT_PAGES
        for path in pages:
            visit(page, path, role, vp, out)
        if vp == "desktop":
            api = api_ctx(pw, token)
            me = check_get(api, role, "/users/me")
            if me:
                record(role, "역할", True, f"user_type={me.get('user_type')}")
            check_get(api, role, "/academies")
            listing = check_get(api, role, "/artworks?limit=5")
            items = (listing or {}).get("items", []) if isinstance(listing, dict) else []
            if items:
                visit(page, f"/artworks/{items[0]['id']}", role, vp, out)
                check_get(api, role, f"/artworks/{items[0]['id']}/recordings")
                check_get(api, role, f"/artworks/{items[0]['id']}/feedback-notes")
            if role == "학생":
                check_get(api, role, "/growth/me/summary")
                check_get(api, role, "/growth/me/timeline")
                if args.write:
                    student_write_flow(pw, api, page, args, out)
            api.dispose()
        page.context.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--stt", action="store_true")
    ap.add_argument(
        "--summary", action="store_true", help="STT 후 AI 요약 자동 요청 (운영에서 켜져 있을 때만)"
    )
    ap.add_argument("--audio")
    ap.add_argument("--stt-timeout", type=int, default=900)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", help="스크린샷·결과 JSON 저장 폴더")
    args = ap.parse_args()
    if args.stt and not args.write:
        ap.error("--stt 는 --write 와 함께 사용")
    s_email, s_pw = os.environ.get("ARTMATE_STUDENT_EMAIL"), os.environ.get("ARTMATE_STUDENT_PASSWORD")
    if not (s_email and s_pw):
        print("ARTMATE_STUDENT_EMAIL / ARTMATE_STUDENT_PASSWORD 환경변수가 필요합니다.", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        run_role(pw, browser, "학생", s_email, s_pw, args, out)
        browser.close()
    fails = [r for r in results if r["status"] == "FAIL"]
    print(
        f"\n합계: PASS {sum(r['status'] == 'PASS' for r in results)} / FAIL {len(fails)} / SKIP {sum(r['status'] == 'SKIP' for r in results)}"
    )
    if out:
        (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
