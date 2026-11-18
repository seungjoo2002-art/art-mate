"""Local full-stack E2E server: real FastAPI app + local PostgreSQL.

Replaced external services only: Supabase Auth (test ES256 key), Storage (in-memory),
LLM (grounded fake that echoes source sentences). Writes user tokens to argv[2].
POST /__e2e/drain runs the job queue once (like the GitHub Actions worker).
POST /__e2e/storage/put stores a browser upload (relayed by Playwright) in the in-memory Storage.
"""

import json
import re
import sys
import time
import uuid

BACKEND = sys.argv[1]
OUT = sys.argv[2]
DB = sys.argv[3]
sys.path.insert(0, BACKEND)

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from tests.conftest import make_settings  # noqa: E402  (sets ENV_FILE='' — no .env)
from tests.auth_utils import TEST_SUPABASE_URL, TokenFactory, make_verifier  # noqa: E402
from tests.fake_ai import FakeFetcher, FakeStt  # noqa: E402
from tests.fake_storage import FakeStorage  # noqa: E402
from app.integrations.ai.gemini import LlmResponse  # noqa: E402
from app.main import create_app  # noqa: E402
from app.worker.runner import JobRunner  # noqa: E402

LINE = re.compile(r"^\[(\d+)\](?: \d\d:\d\d)? (.+)$")
CATS = ["COMPOSITION", "VALUE", "PROPORTION", "FORM"]


class GroundedLlm:
    """원문 문장을 그대로 항목으로 쓰는 가짜 AI (근거 대조 통과). 실제 AI 호출 없음."""

    model_name = "e2e-fake-llm"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *, system: str, prompt: str, schema: dict) -> LlmResponse:
        self.calls += 1
        segs = [(int(m[1]), m[2]) for m in (LINE.match(line) for line in prompt.splitlines()) if m]
        item = lambda i: {"text": segs[i][1], "category": CATS[i % 4], "evidence": [segs[i][0]]}  # noqa: E731
        data = {
            "summary": " ".join(t for _, t in segs[:2]),
            "strengths": [item(0)] if len(segs) > 0 else [],
            "weaknesses": [item(1)] if len(segs) > 1 else [],
            "fixes": [item(2)] if len(segs) > 2 else [],
            "next_tips": [item(3)] if len(segs) > 3 else [],
            "weakness_categories": [CATS[i % 4] for i in (1, 2) if len(segs) > i],
            "insufficient_content": not segs,
        }
        return LlmResponse(
            text=json.dumps(data, ensure_ascii=False),
            input_tokens=100,
            output_tokens=50,
            finish_reason="STOP",
            model_name=self.model_name,
        )


tokens = TokenFactory()
users = {name: uuid.uuid4() for name in ("admin", "owner", "teacher2", "student", "other")}
exp = int(time.time()) + 6 * 3600
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(
        {n: {"id": str(u), "token": tokens.token(u, exp=exp), "exp": exp} for n, u in users.items()},
        f,
    )

app = create_app(
    make_settings(
        database_url=DB,
        supabase_url=TEST_SUPABASE_URL,
        cors_origins=["http://localhost:4175", "http://127.0.0.1:4175"],
        stt_enabled=True,
        ai_summary_enabled=True,
        growth_recent_window=2,  # 작품 4개로 최근·이전 비교 확인
        log_level="WARNING",
    )
)
app.state.token_verifier = make_verifier(tokens)
app.state.storage = FakeStorage()
app.state.audio_storage = FakeStorage(bucket="feedback-audio")
app.state.shared_storage = FakeStorage(bucket="shared-artworks")
llm = GroundedLlm()


@app.post("/__e2e/drain", include_in_schema=False)
async def drain() -> dict:
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=FakeStt(),
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="e2e",
    )
    count = 0
    while count < 20 and await runner.run_once():
        count += 1
    return {"processed": count, "llm_calls": llm.calls}


@app.post("/__e2e/storage/put", include_in_schema=False)
async def storage_put(request: Request, bucket: str, path: str) -> dict:
    """브라우저가 Signed upload URL로 올린 파일을 메모리 Storage에 저장 (E2E 전용, Playwright가 중계)."""
    target = {
        s.bucket: s
        for s in (app.state.storage, app.state.audio_storage, app.state.shared_storage)
    }[bucket]
    target.put(path, await request.body())
    return {"Key": f"{bucket}/{path}"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8010, log_level="warning")
