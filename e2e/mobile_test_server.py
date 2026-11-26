"""v1.3 AI 수정본 실기기(휴대폰) 검수용 테스트 서버 — 운영 API·DB·Supabase·OpenAI를 쓰지 않는다.

한 프로세스가 같은 출처(origin)에서 모두 제공한다:
- 실제 FastAPI 앱 (이 브랜치 코드) + 테스트 전용 PostgreSQL (마이그레이션 0017 적용)
- Supabase 대체 `/__sb`: Storage(업로드·Signed URL·다운로드·삭제, 디스크 저장)와 Auth(빈 응답).
  백엔드는 실제 SupabaseStorage 클라이언트로 이 대체 서버를 부른다 → 학생 토큰으로 업로드·Signed URL
  발급·임시 결과 최종 저장 흐름이 운영과 같은 코드로 동작한다. (Storage RLS는 여기서 검사하지 않음 —
  RLS 함수는 DB 테스트에서 검증)
- 백그라운드 Worker (2초마다 큐 확인): AI 첨삭 정리는 원문 문장을 그대로 쓰는 가짜, 이미지 수정은
  **모의(Mock) 편집기** — 실제 서비스와 같은 상태(대기→생성 중→저장 대기→완료), 저장, 이력이 동작한다.
- 같은 커밋으로 빌드한 프론트엔드 (`--dist`)
- `/__test/` 검수 안내·테스트 계정 로그인 링크·모의 실패 다음 1회 지정

usage (backend/에서):
  uv run python ../e2e/mobile_test_server.py --origin http://192.168.0.10:8020 --port 8020 \
      --db postgresql://postgres@127.0.0.1:5432/artmate_mobile --dist ../e2e-out/mobile-dist \
      --data ../e2e-out/mobile-storage
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import mimetypes
import re
import secrets
import sys
import threading
import time
import uuid
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path
from urllib.parse import quote

parser = argparse.ArgumentParser()
parser.add_argument("--origin", required=True, help="휴대폰에서 여는 주소 (예: http://192.168.0.10:8020)")
parser.add_argument("--port", type=int, default=8020)
parser.add_argument("--db", required=True)
parser.add_argument("--dist", required=True, help="이 서버 주소로 빌드한 프론트엔드")
parser.add_argument("--data", required=True, help="테스트 Storage 파일 저장 폴더")
parser.add_argument("--backend", default=str(Path(__file__).resolve().parents[1] / "backend"))
parser.add_argument("--mock-delay", type=float, default=8.0, help="모의 이미지 수정 소요 시간(초)")
parser.add_argument("--no-seed", action="store_true")
parser.add_argument("--daily-limit", type=int, default=30, help="학생별 하루 생성 한도 (검수용)")
args = parser.parse_args()
sys.path.insert(0, args.backend)

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Request, Response  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402
from PIL import Image, ImageDraw, ImageOps  # noqa: E402

from tests.conftest import make_settings  # noqa: E402  (ENV_FILE='' → .env·운영 설정을 읽지 않음)
from tests.auth_utils import TEST_SUPABASE_URL, TokenFactory, make_verifier  # noqa: E402
from app.integrations.ai.gemini import LlmResponse  # noqa: E402
from app.integrations.ai.openai_image import ImageEditError, ImageEditResult  # noqa: E402
from app.integrations.supabase.storage import HttpSignedUrlFetcher, SupabaseStorage  # noqa: E402
from app.main import create_app  # noqa: E402
from app.worker.runner import JobRunner  # noqa: E402

ORIGIN = args.origin.rstrip("/")
SB = f"{ORIGIN}/__sb"
ANON = "mobile-test-anon"
DATA = Path(args.data)
DATA.mkdir(parents=True, exist_ok=True)
DIST = Path(args.dist)
assert (DIST / "index.html").exists(), "--dist 에 빌드된 프론트엔드가 없습니다"
LINE = re.compile(r"^\[(\d+)\](?: \d\d:\d\d)? (.+)$")
CATS = ["COMPOSITION", "VALUE", "PROPORTION", "FORM"]


# --------------------------------------------------------------------------- 가짜 AI


class GroundedLlm:
    """AI 첨삭 정리 대체: 원문 문장을 그대로 항목으로 (근거 대조 통과, 외부 호출 없음)."""

    model_name = "mobile-test-llm"

    async def generate(self, *, system: str, prompt: str, schema: dict) -> LlmResponse:
        segs = [(int(m[1]), m[2]) for m in (LINE.match(line) for line in prompt.splitlines()) if m]

        def item(i: int) -> dict:
            return {"text": segs[i][1], "category": CATS[i % 4], "evidence": [segs[i][0]]}

        data = {
            "summary": " ".join(t for _, t in segs[:2]),
            "strengths": [item(0)] if len(segs) > 0 else [],
            "weaknesses": [item(1)] if len(segs) > 1 else [],
            "fixes": [item(2)] if len(segs) > 2 else [],
            "next_tips": [item(3)] if len(segs) > 3 else [],
            "weakness_categories": [CATS[i % 4] for i in (1, 2) if len(segs) > i],
            "insufficient_content": not segs,
        }
        return LlmResponse(json.dumps(data, ensure_ascii=False), 100, 50, "STOP", self.model_name)


class MockImageEditor:
    """모의 이미지 수정: 지연 후 원본을 요청 크기에 왜곡 없이 맞추고 주황 표시를 덧그린다.

    결과에 'MOCK'을 새겨 실제 AI 결과와 혼동하지 않게 한다. `/__test/mock?fail=코드`로 다음 1회 실패.
    """

    model_name = "mock-image-edit"

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.fail_next: str | None = None
        self.calls = 0

    async def edit(self, *, images, prompt: str, size: str, user_key: str) -> ImageEditResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail_next:
            code, self.fail_next = self.fail_next, None
            raise ImageEditError(code, f"mock failure {code}", retryable=code in RETRYABLE)
        w, h = (int(v) for v in size.split("x")) if "x" in size else (1024, 1024)
        with Image.open(io.BytesIO(images[0].data)) as src:
            fitted = ImageOps.contain(src.convert("RGB"), (w, h))
        out = Image.new("RGB", (w, h), (238, 236, 230))
        out.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
        draw = ImageDraw.Draw(out)
        for i in range(3):
            r = min(w, h) * (0.18 + 0.08 * i)
            draw.ellipse((w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r), outline=(242, 147, 58), width=8)
        draw.rectangle((0, 0, 150, 40), fill=(242, 147, 58))
        draw.text((12, 12), "MOCK EDIT", fill=(31, 31, 31))
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=85)
        return ImageEditResult(buf.getvalue(), "jpeg", 1500, 1200, 300, 1400, self.model_name)


RETRYABLE = {"IMAGE_RATE_LIMITED", "IMAGE_UNAVAILABLE"}


# --------------------------------------------------------------------------- 앱

tokens = TokenFactory()
ACCOUNTS = {
    "student1": ("검수학생1", "작품·피드백 준비됨, 이미지 동의는 직접"),
    "student2": ("검수학생2", "빈 계정 (직접 작품·사진·피드백 등록)"),
    "other": ("다른학생", "다른 학생 접근 차단 확인용"),
}
EXP = int(time.time()) + 14 * 24 * 3600
USERS = {name: uuid.uuid5(uuid.NAMESPACE_URL, f"artmate-mobile-test/{name}") for name in ACCOUNTS}
TOKENS = {name: tokens.token(uid, exp=EXP) for name, uid in USERS.items()}

settings = make_settings(
    database_url=args.db,
    supabase_url=SB,
    supabase_anon_key=ANON,
    cors_origins=[ORIGIN],
    stt_enabled=False,
    ai_summary_enabled=True,
    image_edit_enabled=True,
    # 검수 중 한도에 막히지 않게 (한도 동작 자체는 자동 테스트로 검증)
    image_edit_daily_limit=args.daily_limit,
    image_edit_monthly_limit=max(args.daily_limit * 10, 20),
    image_edit_service_daily_limit=0,
    image_edit_service_monthly_budget_usd=0,
    worker_poll_seconds=2.0,
    log_level="WARNING",
)
app = create_app(settings)
app.state.token_verifier = make_verifier(tokens)
STORAGE_API = f"{SB}/storage/v1"


def storage(bucket: str) -> SupabaseStorage:
    return SupabaseStorage(api_url=STORAGE_API, anon_key=ANON, bucket=bucket, timeout=30)


app.state.storage = storage(settings.storage_bucket)
app.state.audio_storage = storage(settings.recording_bucket)
app.state.shared_storage = storage(settings.shared_bucket)
app.state.revision_storage = storage(settings.image_edit_bucket)
editor = MockImageEditor(args.mock_delay)


# ----------------------------------------------------------------- Supabase Storage 대체 (/__sb)


def _file(bucket: str, path: str) -> Path:
    target = (DATA / bucket / path).resolve()
    assert str(target).startswith(str(DATA.resolve()))
    return target


def _sign(bucket: str, path: str, kind: str = "sign") -> str:
    return f"/object/{kind}/{bucket}/{quote(path)}?token={secrets.token_urlsafe(8)}"


@app.post("/__sb/storage/v1/object/upload/sign/{bucket}/{path:path}", include_in_schema=False)
async def sb_upload_url(bucket: str, path: str) -> dict:
    return {"url": _sign(bucket, path, "upload/sign")}


@app.put("/__sb/storage/v1/object/upload/sign/{bucket}/{path:path}", include_in_schema=False)
async def sb_upload(bucket: str, path: str, request: Request) -> dict:
    body = await request.body()
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/"):
        msg = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body
        )
        body = next(
            p.get_payload(decode=True)
            for p in msg.iter_parts()
            if p.get_param("name", header="content-disposition") != "cacheControl"
        )
    target = _file(bucket, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {"Key": f"{bucket}/{path}"}


@app.post("/__sb/storage/v1/object/sign/{bucket}", include_in_schema=False)
async def sb_sign(bucket: str, request: Request) -> list:
    data = await request.json()
    return [
        {"path": p, "signedURL": _sign(bucket, p), "error": None}
        for p in data.get("paths", [])
        if _file(bucket, p).exists()
    ]


@app.get("/__sb/storage/v1/object/sign/{bucket}/{path:path}", include_in_schema=False)
@app.get("/__sb/storage/v1/object/authenticated/{bucket}/{path:path}", include_in_schema=False)
async def sb_get(bucket: str, path: str) -> Response:
    target = _file(bucket, path)
    if not target.exists():
        return JSONResponse({"error": "not_found", "message": "Object not found"}, status_code=404)
    kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return Response(target.read_bytes(), media_type=kind, headers={"cache-control": "no-store"})


@app.post("/__sb/storage/v1/object/{bucket}/{path:path}", include_in_schema=False)
async def sb_server_upload(bucket: str, path: str, request: Request) -> Response:
    target = _file(bucket, path)
    if target.exists():
        return JSONResponse(
            {"statusCode": "409", "error": "Duplicate", "message": "The resource already exists"},
            status_code=400,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await request.body())
    return JSONResponse({"Key": f"{bucket}/{path}"})


@app.delete("/__sb/storage/v1/object/{bucket}", include_in_schema=False)
async def sb_delete(bucket: str, request: Request) -> list:
    data = await request.json()
    removed = []
    for p in data.get("prefixes", []):
        target = _file(bucket, p)
        if target.exists():
            target.unlink()
            removed.append({"name": p})
    return removed


@app.api_route("/__sb/auth/v1/{rest:path}", methods=["GET", "POST", "PUT"], include_in_schema=False)
async def sb_auth(rest: str) -> Response:
    if rest.startswith("logout"):
        return Response(status_code=204)
    return JSONResponse({})


# ----------------------------------------------------------------- 검수 안내·로그인


def _session(name: str) -> dict:
    return {
        "access_token": TOKENS[name],
        "refresh_token": "mobile-test",
        "expires_at": EXP,
        "expires_in": EXP - int(time.time()),
        "token_type": "bearer",
        "user": {
            "id": str(USERS[name]),
            "aud": "authenticated",
            "role": "authenticated",
            "email": f"{name}@mobile-test.invalid",
            "app_metadata": {},
            "user_metadata": {},
            "created_at": "2026-11-26T00:00:00Z",
        },
    }


STORAGE_KEY = f"sb-{httpx.URL(SB).host.split('.')[0]}-auth-token"


@app.get("/__test/login", include_in_schema=False)
async def test_login(as_: str = "student1", to: str = "/archive") -> HTMLResponse:
    session = json.dumps(json.dumps(_session(as_)))
    return HTMLResponse(
        f"<script>localStorage.setItem({json.dumps(STORAGE_KEY)}, {session});"
        f"location.replace({json.dumps(to)});</script>"
    )


@app.get("/__test/mock", include_in_schema=False)
async def test_mock(fail: str | None = None, delay: float | None = None) -> dict:
    """다음 모의 이미지 수정 1회를 실패시키거나 지연 시간을 바꾼다 (검수용)."""
    if fail:
        editor.fail_next = fail
    if delay is not None:
        editor.delay = max(0.0, min(delay, 120.0))
    return {"fail_next": editor.fail_next, "delay": editor.delay, "calls": editor.calls}


@app.get("/__test/", include_in_schema=False)
async def test_home() -> HTMLResponse:
    rows = "".join(
        f'<li><a href="/__test/login?as_={n}">{label}</a> — {desc}</li>'
        for n, (label, desc) in ACCOUNTS.items()
    )
    fails = "".join(
        f'<li><a href="/__test/mock?fail={c}">{c}</a></li>'
        for c in ("IMAGE_RESULT_UNKNOWN", "IMAGE_RATE_LIMITED", "IMAGE_BLOCKED")
    )
    return HTMLResponse(
        "<meta name=viewport content='width=device-width'>"
        "<body style='font-family:sans-serif;padding:16px;line-height:1.6'>"
        "<h2>ART MATE v1.3 AI 수정본 검수 (테스트 서버)</h2>"
        "<p>운영과 분리된 테스트 DB·Storage·모의 AI입니다. 실제 OpenAI를 부르지 않습니다.</p>"
        f"<h3>계정으로 들어가기</h3><ul>{rows}</ul>"
        f"<h3>다음 1회 모의 실패</h3><ul>{fails}</ul>"
        "<p><a href='/__test/mock?delay=3'>생성 3초</a> · <a href='/__test/mock?delay=20'>생성 20초</a>"
        " (기본 8초)</p></body>"
    )


# ----------------------------------------------------------------- 프론트엔드 (SPA)


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str) -> FileResponse:
    target = (DIST / full_path).resolve()
    if full_path and target.is_file() and str(target).startswith(str(DIST.resolve())):
        return FileResponse(target)
    return FileResponse(DIST / "index.html", headers={"cache-control": "no-store"})


# ----------------------------------------------------------------- Worker·준비 데이터


async def worker_loop(stop: asyncio.Event) -> None:
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=None,
        llm=GroundedLlm(),
        fetcher=HttpSignedUrlFetcher(timeout=30),
        worker_id="mobile-test",
        image_editor=editor,
    )
    await runner.run_forever(stop)


def drawing(size: tuple[int, int], label: str, colored: bool) -> bytes:
    img = Image.new("RGB", size, (236, 232, 224))
    d = ImageDraw.Draw(img)
    w, h = size
    fill = (214, 90, 70) if colored else None
    d.ellipse((w * 0.15, h * 0.45, w * 0.45, h * 0.75), outline=(60, 60, 60), width=5, fill=fill)
    d.rectangle((w * 0.55, h * 0.25, w * 0.75, h * 0.75), outline=(70, 70, 70), width=5)
    d.ellipse((w * 0.55, h * 0.22, w * 0.75, h * 0.28), outline=(70, 70, 70), width=4)
    d.line((0, h * 0.78, w, h * 0.78), fill=(120, 120, 120), width=3)
    d.text((12, 12), label, fill=(90, 90, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def seed() -> None:
    api = f"http://127.0.0.1:{args.port}/api/v1"

    def h(name: str) -> dict:
        return {"Authorization": f"Bearer {TOKENS[name]}"}

    for _ in range(60):
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(f"{api}/health", timeout=2).status_code == 200:
                break
        time.sleep(1)
    for name, (label, _) in ACCOUNTS.items():
        httpx.post(f"{api}/users/me", headers=h(name), json={"display_name": label, "user_type": "STUDENT"})
        httpx.patch(f"{api}/users/me", headers=h(name), json={"practical_type": "DRAWING"})
    listed = httpx.get(f"{api}/artworks", headers=h("student1")).json()
    if listed.get("total"):
        return  # 이미 준비됨
    httpx.post(
        f"{api}/ai-processing-consents",
        headers=h("student1"),
        json={"policy_version": settings.ai_consent_version, "agreed": True, "birth_year_month": "2000-01"},
    )
    art = httpx.post(
        f"{api}/artworks",
        headers=h("student1"),
        json={"title": "[검수] 정물 소묘", "practical_type": "DRAWING", "topic": "유리병과 사과"},
    ).json()
    stages = art["stage_plan"]

    def upload(stage_id: str, data: bytes) -> dict:
        ticket = httpx.post(
            f"{api}/artworks/{art['id']}/photos",
            headers=h("student1"),
            json={"stage_id": stage_id, "content_type": "image/jpeg", "file_size": len(data)},
        ).json()
        path = ticket["upload"]["path"]
        httpx.put(f"{SB}/storage/v1/object/upload/sign/artworks/{quote(path)}?token=t", content=data)
        return httpx.post(
            f"{api}/artworks/{art['id']}/photos/{ticket['photo']['id']}/complete", headers=h("student1")
        ).json()

    notes = [
        "구도는 안정적이다. 유리병 입구 타원이 지나치게 납작하다. 사과의 명암 대비를 더 강하게 줘라.",
        "배치가 좋다. 사물 간 앞뒤 공간감이 부족하다. 뒤쪽 사물의 윤곽을 더 흐리게 처리해라.",
        "선 정리가 깔끔하다. 바닥면 투시가 맞지 않는다. 바닥 타원을 눈높이에 맞춰 다시 잡아라.",
    ]
    plan = [
        (stages[0]["id"], (600, 800), "sketch 1", False, notes[0]),
        (stages[0]["id"], (900, 600), "sketch 2", False, notes[1]),
        (stages[0]["id"], (700, 700), "sketch 3 (no feedback)", False, None),
        (stages[1]["id"], (600, 800), "progress 1", True, notes[2]),
        (stages[-1]["id"], (600, 800), "final 1", True, notes[0]),
    ]
    for stage_id, size, label, colored, note in plan:
        photo = upload(stage_id, drawing(size, label, colored))
        if note:
            httpx.post(
                f"{api}/artworks/{art['id']}/feedback-notes",
                headers=h("student1"),
                json={
                    "source": "INSTRUCTOR",
                    "body": note,
                    "stage_id": stage_id,
                    "reference_photo_ids": [photo["id"]],
                    "reference_confirmed": True,
                    "request_summary": True,
                },
            )


_app_lifespan = app.router.lifespan_context


@contextlib.asynccontextmanager
async def _lifespan(application):  # type: ignore[no-untyped-def]
    """앱의 원래 lifespan(DB 연결 등) 안에서 Worker 루프와 준비 데이터 생성을 함께 돌린다."""
    async with _app_lifespan(application) as state:
        stop = asyncio.Event()
        worker = asyncio.create_task(worker_loop(stop))
        if not args.no_seed:
            threading.Thread(target=seed, daemon=True).start()
        try:
            yield state
        finally:
            stop.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(worker, timeout=5)


app.router.lifespan_context = _lifespan


if __name__ == "__main__":
    print(f"검수 안내: {ORIGIN}/__test/   (JWT issuer {TEST_SUPABASE_URL})", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
