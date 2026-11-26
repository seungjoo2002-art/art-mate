# 운영 사이트 실사용 점검 (`prod_smoke.py`)

실제 브라우저(Playwright Chromium)로 운영 사이트에 로그인하고, **그 브라우저 세션 토큰으로 운영 API·Storage를 그대로 호출**한다. Mock이 없으므로 PASS는 운영에서 실제로 동작했다는 뜻이다.

```bash
pip install playwright && python -m playwright install chromium   # 처음 한 번

# PowerShell
$env:ARTMATE_STUDENT_EMAIL="..."; $env:ARTMATE_STUDENT_PASSWORD="..."

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
- ART MATE는 학생 전용 앱이다 (강사·학원 계정 없음).
- 결과: 콘솔 `[PASS]/[FAIL]/[SKIP]`, `--out` 폴더에 스크린샷과 `results.json`.

## 로컬 전체 스택 E2E — v1.0 개인 성장 분석

실제 API(로컬) + 로컬 PostgreSQL + 실제 브라우저. 외부 서비스만 대체: Supabase 인증(테스트 서명 키), Storage(메모리), AI(원문 문장을 그대로 쓰는 가짜 — 실제 호출 없음). **운영 DB·운영 API에 접근하지 않는다.**

```bash
cd backend
ENV_FILE= APP_ENV=test DATABASE_URL=postgresql://postgres@127.0.0.1:5432/artmate_e2e uv run alembic upgrade head
uv run python ../e2e/local_server.py "$(pwd)" ../e2e-out/tokens.json postgresql://postgres@127.0.0.1:5432/artmate_e2e   # :8010
cd ../frontend && VITE_SUPABASE_URL=https://e2e-project.supabase.co VITE_SUPABASE_ANON_KEY=e2e \
  VITE_API_BASE_URL=http://127.0.0.1:8010 npx vite build --outDir ../e2e-out/dist && npx vite preview --outDir ../e2e-out/dist --port 4175
python -X utf8 ../e2e/local_growth_flow.py ../e2e-out/tokens.json ../e2e-out
```

검증: 학생 가입 → 데이터 부족 상태 → 첨삭 4건 확정 → 9개 태그 반복 실수·최근/이전 비교·첨삭 분량 주의·항목별 막대·기간별 첨삭 수 → 연습 과제 담기·완료 → 다른 학생 격리 → 기존 화면 회귀 → 모바일·데스크톱. 다시 돌릴 때는 DB를 새로 만들고 서버를 재시작한다.

## 로컬 전체 스택 E2E — v1.1 원본 제시물·표현 의도

위와 같은 서버(`local_server.py`)와 빌드를 쓴다. 브라우저가 Supabase Signed upload URL로 올리는 파일은 Playwright가 가로채서 테스트 전용 `/__e2e/storage/put`(메모리 Storage)으로 넘긴다. 실제 Supabase나 운영에는 접근하지 않는다.

```bash
python -X utf8 ../e2e/local_reference_flow.py ../e2e-out/tokens.json ../e2e-out
```

모바일(390px)과 데스크톱(1280px)에서 아래 흐름을 확인한다.

- 등록 흐름: 주제 → 원본 사진 → 시험 조건 → 표현 의도 → 생성 후 업로드
- 잘못된 형식의 파일 안내
- 상세 화면: 원본과 작품을 나란히 보기, 가로 스크롤 없음
- 수정 화면: 교체, 삭제, 추가(WebP), 의도 해제
- 업로드 실패: 입력이 유지되고, 재시도해도 작품이 중복 생성되지 않음
- 기존 작품 호환
- 다른 학생의 접근 404

메모리 Storage의 미리보기 URL은 브라우저에서 열리지 않으므로 스크린샷의 이미지는 빈 칸으로 보인다. 레이아웃 확인용이다.

## 로컬 전체 스택 E2E — v1.3 AI 수정본

같은 서버(`local_server.py`, 가짜 이미지 편집기 포함 — 실제 OpenAI 호출 없음)와 빌드를 쓴다. 메모리 Storage의
가짜 Signed URL(`https://storage.test/...`)은 Playwright가 `/__e2e/storage/get` 응답으로 채워 이미지가 실제로 보인다.
다시 돌릴 때는 DB를 새로 만들고 서버를 재시작한다 (학생별 하루 생성 한도 3).

```bash
python -X utf8 ../e2e/local_ai_revision_flow.py ../e2e-out/tokens.json ../e2e-out
```

모바일(390px, 터치)·데스크톱(1280px): 아카이브 'AI 수정본 보기 (N개)' 위치·폭, 피드백 화면 개선사항(사진별 분리·
기본 전체 선택), 동의 화면, 생성 대기·화면 이동·새로고침 후 복원(재호출 없음), 비교 슬라이더(비율·contain·터치/마우스/
키보드, 사진 슬라이드와 충돌 없음, 세로 스크롤 유지), 원본·AI 수정작 모드, 수정 이력·삭제, 사진 교체 후 이력 분리,
대표·사진 수 미포함, 다른 학생 404.

## 실제 OpenAI 이미지 수정 점검 (유료, 승인된 소량만)

```bash
cd backend
uv run python ../e2e/real_image_edit_check.py --image sketch.jpg --stage SKETCH --subject "..." --type "소묘" \
  --improvement "FORM|WEAKNESS|유리병 입구의 타원이 지나치게 납작하다." --out ../e2e-out/real        # 요청 내용만 (무료)
uv run python ../e2e/real_image_edit_check.py ... --yes                                            # 실제 호출 1건
```

## 휴대폰 실기기 검수 환경 — v1.3 AI 수정본 (`mobile_test_server.py`)

운영 API·DB·Supabase·OpenAI를 쓰지 않고 이 PC 한 대로 띄운다. 추가 서버·유료 서비스 없음.

- 실제 API(이 브랜치) + 테스트 전용 PostgreSQL(0017) + Supabase 대체(`/__sb`: Storage 디스크 저장·Auth 빈 응답)
  + 같은 커밋 프론트 빌드 + 백그라운드 Worker(가짜 AI 첨삭 정리, **모의 이미지 수정**: 8초 뒤 원본에 'MOCK EDIT'과
  주황 원을 그린 이미지) — 상태 변화·Storage 저장·비교·이력이 실제 서비스와 같은 코드로 동작
- 테스트 계정 로그인 링크(비밀번호 없음), 모의 실패 다음 1회 지정, 생성 시간 조절: `<주소>/__test/`
- 백엔드는 실제 `SupabaseStorage` 클라이언트로 대체 서버를 부르므로 업로드·Signed URL·학생 토큰 저장 흐름이 운영과 같다.
  Storage RLS 자체는 여기서 검사하지 않는다 (DB 테스트에서 검증).

```powershell
powershell -ExecutionPolicy Bypass -File e2e\mobile_test_env.ps1 -Reset     # Wi-Fi 주소로 실행
# 휴대폰(같은 Wi-Fi)에서 http://<PC Wi-Fi IP>:8020/__test/
```

Wi-Fi가 '공용' 네트워크면 Windows 방화벽이 휴대폰 접속을 막는다. 검수하는 동안만 관리자 PowerShell에서:

```powershell
New-NetFirewallRule -DisplayName "ARTMATE mobile test 8020" -Direction Inbound -Protocol TCP -LocalPort 8020 -RemoteAddress LocalSubnet -Action Allow
Remove-NetFirewallRule -DisplayName "ARTMATE mobile test 8020"     # 검수 후 삭제
```

학교·공용 Wi-Fi처럼 기기끼리 통신이 막힌 망이면 HTTPS 터널(예: Cloudflare Quick Tunnel, 무료·계정 불필요)의 주소를
`-Origin`으로 넘긴다 (테스트 데이터만 터널을 거친다).
