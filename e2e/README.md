# 운영 사이트 실사용 점검 (`prod_smoke.py`)

실제 브라우저(Playwright Chromium)로 운영 사이트에 로그인하고, **그 브라우저 세션 토큰으로 운영 API·Storage를 그대로 호출**한다. Mock이 없으므로 PASS는 운영에서 실제로 동작했다는 뜻이다.

```bash
pip install playwright && python -m playwright install chromium   # 처음 한 번

# PowerShell
$env:ARTMATE_STUDENT_EMAIL="..."; $env:ARTMATE_STUDENT_PASSWORD="..."
$env:ARTMATE_INSTRUCTOR_EMAIL="..."; $env:ARTMATE_INSTRUCTOR_PASSWORD="..."   # 선택

python -X utf8 e2e/prod_smoke.py --out e2e-out                       # 읽기 전용
python -X utf8 e2e/prod_smoke.py --write --out e2e-out               # 테스트 작품 생성→사진→첨삭→삭제
python -X utf8 e2e/prod_smoke.py --write --stt --audio sample.wav    # + 서버 STT 소요 시간 측정
python -X utf8 e2e/prod_smoke.py --write --stt --summary --audio sample.wav   # + AI 요약 (운영에서 켜진 경우)
```

| 모드 | 운영에 남는 것 |
| --- | --- |
| 기본 | 없음 (로그인·조회만) |
| `--write` | 없음 — `[E2E] 운영 점검 …` 작품을 만들고 끝에 삭제 (`--keep`이면 남김) |
| `--stt` | 위와 같음. 녹음 동의는 **앱에서 테스트 계정으로 미리** 해 둬야 한다 (스크립트가 대신 동의하지 않음) |
| `--summary` | 실제 OpenAI 호출 1건 (과금) |

- 테스트 전용 계정만 사용한다. 실제 학생 계정으로 `--write`를 실행하지 않는다.
- 강사 화면은 그 강사가 속한 학원(academy)과 학생 소속이 있어야 학생 작품이 보인다.
- 결과: 콘솔 `[PASS]/[FAIL]/[SKIP]`, `--out` 폴더에 스크린샷과 `results.json`.

## 로컬 전체 스택 E2E (v1.0 강사·학원 흐름)

실제 API(로컬) + 로컬 PostgreSQL + 실제 브라우저. 외부 서비스만 대체한다: Supabase 인증(테스트 서명 키), Storage(메모리), AI(원문 문장을 그대로 쓰는 가짜 — 실제 호출 없음). **운영 DB·운영 API에는 접근하지 않는다.**

```bash
# 1) 빈 로컬 DB를 head로 (DATABASE_URL은 로컬 주소만, Supabase면 Alembic이 거부)
cd backend && ENV_FILE= APP_ENV=test DATABASE_URL=postgresql://postgres@127.0.0.1:5432/artmate_e2e uv run alembic upgrade head
# 2) API 서버 (토큰 파일 생성, :8010)
uv run python ../e2e/local_v10_server.py "$(pwd)" ../e2e-out/tokens.json postgresql://postgres@127.0.0.1:5432/artmate_e2e
# 3) 프론트 빌드·실행 (:4175)
cd ../frontend && VITE_SUPABASE_URL=https://e2e-project.supabase.co VITE_SUPABASE_ANON_KEY=e2e \
  VITE_API_BASE_URL=http://127.0.0.1:8010 npx vite build --outDir ../e2e-out/dist && npx vite preview --outDir ../e2e-out/dist --port 4175
# 4) 흐름 실행 (가입 → 학원 등록·승인 → 소속·반 배정 → 학원 작품·첨삭 → AI 정리 → 강사 승인 → 학생 확인 → 권한 차단 → 모바일)
cd ../backend && python -X utf8 ../e2e/local_v10_flow.py ../e2e-out/tokens.json postgresql://postgres@127.0.0.1:5432/artmate_e2e ../e2e-out "$(pwd)"
```

같은 DB로 다시 돌리려면 DB를 새로 만들고 서버를 재시작한다 (토큰·계정이 새로 생김).
