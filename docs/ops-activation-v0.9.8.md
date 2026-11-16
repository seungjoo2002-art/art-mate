# v0.9.8 운영 설정 변경안 — STT 즉시 실행 · AI 첨삭 요약 활성화 (승인 대기)

> 작성: 2026-11-16 · 브랜치 `fix/v0.9.8-ops-ai-stt`
> 이 문서는 **변경안**이다. 아래 운영 설정은 아직 아무것도 바꾸지 않았다. 토큰·키 값은 적지 않는다.

## 1. 확인한 현재 상태 (2026-11-16)

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| 운영 API AI 기능 | `ai_summary: false`, `ai_summary_status: DISABLED`, 제공자 `openai`, 일일 한도 20 | `GET /api/v1/meta/ai-features` |
| Worker 즉시 실행 | `dispatch_configured: false` (Render에 `WORKER_DISPATCH_TOKEN` 없음) | `GET /api/v1/meta/worker-status` |
| GitHub Actions Secret | `OPENAI_API_KEY` 있음(2026-11-12), `WORKER_DATABASE_URL` 있음 | `gh secret list` (이름만) |
| GitHub Actions Variables | **하나도 없음** → AI 관련 값 모두 기본값 `false` | `gh variable list` |
| 예약 실행 실제 간격 | 15분 예약, 실제 3.6~9.4시간(중앙값 6.2시간), 최근 20회 모두 성공, 1회 약 25초 | `gh run list` |
| 저장소 공개 여부 | PUBLIC → 표준 러너 Actions 사용료 없음 | `gh repo view` |
| 운영 사용자 | 학생 4명, 강사·학원·학원 소속 0 | 운영 DB 집계(읽기 전용) |
| OpenAI 요약 동의 | 유효한 동의 2건, 둘 다 성인(ADULT) | 운영 DB 집계(읽기 전용) |

## 2. STT 지연 — 원인과 해결

**원인**: GitHub Actions `schedule`은 보장되지 않는 최선 노력 실행이다. 부하가 높으면 지연·누락되고, 이 저장소에서는 실제로 수 시간씩 밀렸다(코드 주석에도 2026-11-11 기록). 즉시 실행 기능(`app/services/worker_dispatch.py`)은 v0.9.6에 이미 구현돼 있지만 **토큰이 없어 꺼져 있다**.

**구현돼 있는 흐름** (코드 변경 불필요)

1. 학생이 서버 전사 요청 → `ai_processing_jobs`에 `TRANSCRIBE` 작업(QUEUED)
2. 응답 직후 API가 GitHub `workflow_dispatch`로 `stt-worker.yml` 실행 요청 (같은 프로세스에서 30초 안의 요청은 1번으로 합침)
3. 처음 요청이 실패해도: 대기 120초 넘은 작업이 있으면 상태 조회·5분 주기 점검 때 재요청(10분에 1번)
4. Worker: `concurrency: stt-worker`(동시에 1개) + `FOR UPDATE SKIP LOCKED` + lease 5분 → 중복 처리 없음. 재시도 가능 오류는 지수 백오프 최대 3회, 강제 종료 시 lease 만료 후 다음 실행이 이어받음
5. 토큰이 틀리거나 만료돼도 경고 로그만 남기고 예약 실행으로 돌아간다(요청 실패 아님)

**변경안 (승인 필요)**

| 위치 | 이름 | 값 |
| --- | --- | --- |
| GitHub → Settings → Developer settings → Fine-grained token | 새 토큰 | 저장소: `seungjoo2002-art/art-mate` **하나만**, 권한: **Actions: Read and write** (그 외 없음), 만료 90일 권장 |
| Render → art-mate API → Environment | `WORKER_DISPATCH_TOKEN` | 위 토큰 |

- 영향: Render가 환경변수 변경으로 재시작(수십 초). 코드·DB 변경 없음. 비용 없음(공개 저장소).
- 기대 처리 시간: 요청 → Actions 시작 10~60초 → 설치 약 1분(+ STT 패키지 설치) → 전사(Whisper small, CPU). **짧은 녹음은 대략 3~5분 안**에 끝날 것으로 예상(추정치 — 토큰 설정 후 `prod_smoke.py --stt`로 실측 필요).
- 위험: 토큰 유출 시 이 저장소 Actions 실행·취소·로그 열람 가능 → 저장소 1개·Actions 권한만, 만료 설정, Render에만 저장.
- 대안(추가 비용 없음): 브라우저 전사(`browser_transcription: true`)는 이미 켜져 있어 즉시 처리된다. 서버 STT는 정확도 보완용.

## 3. AI 첨삭 요약 — 꺼져 있는 이유와 활성화 조건

**사용 모델**: OpenAI Responses API, 기본 `gpt-6.1-terra`(저비용 `gpt-6-luna` 선택 가능), Structured Outputs, `store=false`, 추론 강도 low. 호출은 Worker(GitHub Actions)에서만, 키는 Actions Secret에만 있다.

**꺼져 있는 이유 (코드·문서에 기록됨)** — 기술 문제가 아니라 **운영자·법률 확인 대기**:
- `AI_PROVIDER_TERMS_CONFIRMED=false`이면 배포 환경에서는 `AI_SUMMARY_ENABLED=true`여도 외부 AI로 보내지 않는다 (`Settings.ai_summary_active`).
- [release-readiness-v0.9.6.md §6](release-readiness-v0.9.6.md)의 시작 조건: OpenAI 전용 프로젝트·월 예산 한도, 학습 사용 꺼짐 확인, 비즈니스 약관 원문 검토, 동의서·개인정보처리방침 확정(국외 이전 고지), 성인부터 시작, 유료 호출 승인.
- 미성년자: [minors-ai-policy-v0.9.6.md](minors-ai-policy-v0.9.6.md) — 만 14~17세 `AI_TEENS_ENABLED`, 만 14세 미만 `AI_UNDER14_ENABLED` + `AI_ZDR_APPROVED`. 모두 `false` 유지 권장.

**예상 비용 (공식 단가 기준 추정)**: terra 입력 $1 / 출력 $5 (100만 토큰). 10분 안팎 첨삭 전사(입력 약 4천 토큰) + 출력·추론 약 2~3천 토큰 → **1건 약 $0.02** (luna는 약 $0.002). 학생당 하루 20건 한도. 현재 성인 동의자 2명 기준 최악의 경우 월 약 $24, 실제 사용량 기준으로는 수십 센트 수준 예상. **OpenAI 프로젝트 월 예산 한도(예: $5)를 먼저 설정할 것.**
- 키에 잔액·결제 수단이 있는지는 확인할 수 없다(키 값 미열람). 잔액이 없으면 첫 호출이 429/insufficient_quota로 실패하고, 재시도 후 FAILED로 남는다.

**변경안 (승인 + 운영자 확인 필요)** — 같은 값을 Render와 GitHub Actions Variables 양쪽에:

| 이름 | 값 | 비고 |
| --- | --- | --- |
| `AI_SUMMARY_ENABLED` | `true` | |
| `AI_PROVIDER_TERMS_CONFIRMED` | `true` | **§6 조건을 운영자가 확인했다는 선언** |
| `AI_SUMMARY_DAILY_LIMIT` | `5` (시험 기간) | Render. 기본 20 |
| `OPENAI_MODEL` | 비우거나 `gpt-6-luna`(시험용 저비용) | Actions Variable |
| `AI_TEENS_ENABLED`, `AI_UNDER14_ENABLED`, `AI_ZDR_APPROVED` | `false` 유지 | 미성년자 차단 유지 |

- 영향: 성인 동의자만 요약 요청 가능. 미성년자는 기존처럼 409(차단), 전사문은 정상 저장.
- 끄는 방법: 두 곳의 `AI_SUMMARY_ENABLED`를 `false`로 → 대기 중 요약 작업은 실패 처리 없이 큐에 남는다.

## 4. 승인 후 검증 순서

1. `GET /api/v1/meta/worker-status` → `dispatch_configured: true`
2. `GET /api/v1/meta/ai-features` → `ai_summary_status`가 `DISABLED`가 아님
3. 테스트 계정으로 `python -X utf8 e2e/prod_smoke.py --write --stt --audio sample.wav` → STT 소요 시간 실측
4. 성인 테스트 계정(요약 동의 완료)으로 `--summary` 1회 → 실제 OpenAI 요약 1건, 사용 토큰 확인
