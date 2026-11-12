# STT·AI 요약 Worker — GitHub Actions 무료 운영 (v0.9.1)

> 작성: 2026-11-10 · 워크플로: [`.github/workflows/stt-worker.yml`](../.github/workflows/stt-worker.yml)
> 관련: [ai-feedback-v0.6.md](ai-feedback-v0.6.md) (작업 큐·STT·요약 설계), [frontend-integration-v0.9.md](frontend-integration-v0.9.md)

유료 서버 없이 **GitHub Actions가 주기적으로 잠깐 켜져** DB 작업 큐(`ai_processing_jobs`)를 처리한다.
API 서버(Render Free)는 작업을 큐에 넣기만 하고 STT 모델을 로드하지 않는다. DB 구조 변경 없음.

```text
학생 ─ 녹음 업로드 (기존 API, 학생 토큰 → Supabase Storage 비공개 버킷)
     ─ POST …/transcription {auto_summarize}  → Render API: 학생 토큰으로 음성 Signed URL 발급 → TRANSCRIBE 작업 QUEUED
GitHub Actions (15분마다 예약 + 수동 실행)
     ─ python -m app.worker --pending   : 대기 작업 수 확인 (전사 작업이 없으면 STT 설치·모델 복원 생략)
     ─ python -m app.worker --once      : 작업 선점(FOR UPDATE SKIP LOCKED) → Signed URL로 음성 다운로드
                                          → faster-whisper small/CPU/INT8/ko → 전사 저장 → (요청 시) SUMMARIZE 작업 생성
                                          → Gemini 요약 (켜져 있을 때) → 근거 대조 → 초안 저장
학생 ─ GET …/transcription (상태) → GET/PUT …/transcript (확인·수정, 원본 보존)
     ─ POST …/summary (전사 확정 후 요약 요청) → GET …/summary → /feedbacks/{id} 검토·수정·확정 → 성장 분석
```

## 1. 동작 방식

| 항목 | 내용 |
| --- | --- |
| 실행 | `schedule: */15 * * * *` + `workflow_dispatch`(쓰기 권한자만). 포크 저장소에서는 실행 안 함 (`if: github.repository == …`). PR·push로는 실행되지 않음 |
| 중복 실행 | `concurrency: stt-worker`(동시에 1개, 다음 실행은 대기) + DB `FOR UPDATE SKIP LOCKED` + 진행 중 작업 부분 유니크 |
| 제한 | 한 번에 최대 10개·40분 동안만 새 작업을 잡음 (`max_jobs`, `max_minutes` 입력으로 조정), 작업 타임아웃 60분, 전사 1건 최대 20분 (`STT_TIMEOUT_SECONDS=1200`) |
| 처리 종류 | 켜진 기능만 가져감: STT는 항상, Gemini는 `AI_SUMMARY_ENABLED=true` + `GEMINI_API_KEY`일 때만. 꺼져 있으면 요약 작업은 실패시키지 않고 큐에 남김 |
| 실패·재시도 | 기존 로직: 재시도 가능한 오류(저장소·Gemini 429/5xx/타임아웃)는 지수 백오프 후 다음 실행에서 재시도, 최대 3회. 재시도 불가(음성 없음·너무 긺·URL 만료)는 FAILED → 학생이 재시도 API |
| 중단 복구 | Actions가 강제 종료돼도 lease(5분) 만료 후 다음 실행이 이어받음 (시도 1회 소모) |
| 모델 캐시 | `actions/cache` 키 `whisper-small-ct2-v1` (약 0.5GB). 첫 실행·캐시 만료(7일 미사용) 때만 Hugging Face에서 다운로드 |
| 정기 작업 | 실행마다 음성 보관 기간 표시·미완료 과제·목표 알림 (v0.9 maintenance) |
| 보안 | 워크플로 권한 `contents: read`. 필요한 비밀값은 DB 연결 문자열과 Gemini 키뿐 — **service_role 키 불필요** (음성은 학생 토큰으로 발급된 Signed URL로만 받음). 로그에는 작업 ID·종류·개수·오류 코드만 (음성·전사·토큰·URL 없음) |

## 2. 설정

### 2.1 GitHub → Settings → Secrets and variables → Actions

| 이름 | 종류 | 값 |
| --- | --- | --- |
| `WORKER_DATABASE_URL` | Secret (필수) | Supabase **Session pooler** 연결 문자열 (Project Settings → Database → Connection string → Session pooler, `postgresql://postgres.<ref>:<password>@aws-…pooler.supabase.com:5432/postgres`). 직접 연결 주소는 IPv6라 Actions에서 접속 불가 |
| `GEMINI_API_KEY` | Secret (요약을 켤 때) | Google AI Studio API 키 |
| `AI_SUMMARY_ENABLED` | Variable | `true`로 바꾸면 Actions가 요약 작업 처리 (기본 꺼짐 — **Gemini 사용 승인 후**) |
| `GROWTH_AI_ENABLED` | Variable (선택) | `true`면 성장 리포트 설명문·AI 추천도 처리 |
| `AI_CONSENT_VERSION`, `AI_GROWTH_CONSENT_VERSION` | Variable (선택) | Render에서 기본값을 바꿨을 때만 같은 값으로 |

Secret이 없으면 워크플로는 아무것도 하지 않고 성공으로 끝난다.

### 2.2 Render (API 서버) 환경 변수

| 이름 | 값 | 이유 |
| --- | --- | --- |
| `STT_ENABLED` | `true` | 전사 요청 API를 연다 (API는 모델을 로드하지 않음, 이미지에 faster-whisper 미설치 그대로) |
| `AI_SUMMARY_ENABLED` | `true` (Gemini 승인 후) | 요약 요청 API를 연다. **Render에는 `GEMINI_API_KEY`를 넣지 않는다** (호출은 Actions에서만) |
| `STT_SOURCE_URL_SECONDS` | `86400` | 음성 Signed URL 유효 시간. 예약 실행이 늦어져도 24시간 안에만 처리되면 된다 (기본 6시간) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | (기존) | Signed URL 발급에 필요 |

Render에서 기존 상시 Worker 서비스는 만들지 않는다 (유료).

### 2.3 Worker 즉시 실행 (v0.9.3, 선택 — 강력 권장)

예약 실행(`*/15`)은 실제로 크게 밀린다. 2026-11-10 07:26 UTC 병합 후 첫 예약 실행이 **약 29시간 뒤**(11-11 12:51)였고,
이후 49시간 동안 실행은 **4회**(간격 5.8~7.1시간)뿐이었다. 그 사이 서버 전사 2건이 `SOURCE_URL_EXPIRED`로 실패했다.

API가 작업을 큐에 넣을 때 워크플로를 바로 실행 요청(`workflow_dispatch`)하면 이 지연을 없앨 수 있다 (GitHub가 실행을 보장하지는 않으므로 예약 실행은 그대로 둔다).

| 위치 | 이름 | 값 |
| --- | --- | --- |
| Render | `WORKER_DISPATCH_TOKEN` | **fine-grained PAT**: Repository access = 이 저장소만, Permissions = **Actions: Read and write** (그 밖의 권한 없음). 만료일을 정하고 갱신 일정 관리 |
| Render (선택) | `WORKER_DISPATCH_REPO` / `WORKER_DISPATCH_WORKFLOW` / `WORKER_DISPATCH_REF` | 기본 `seungjoo2002-art/art-mate` / `stt-worker.yml` / `main` |
| Render (선택) | `WORKER_DISPATCH_MIN_INTERVAL_SECONDS` | 기본 30. 이 간격 안의 요청은 한 번으로 합침 |

- 요청 본문은 `{"ref": "main"}`뿐 (작업·사용자 정보 없음). Worker는 기존처럼 DB 큐에서 가져간다.
- 토큰이 없거나 GitHub가 거절하면 경고 로그(`worker dispatch rejected`, 상태 코드만)를 남기고 예약 실행에 맡긴다. 요청 API 응답에는 영향 없음 (응답 후 백그라운드).
- 기기 변환 중 만드는 **백업 전사 작업**(`defer_seconds`, 기본 15분 뒤)은 바로 실행 요청하지 않는다. 기기 변환이 실패하면 프론트가 같은 요청을 `defer_seconds` 없이 보내 백업을 앞당기고, 그때 실행을 요청한다.
- 공개 저장소의 표준 러너는 사용 시간 과금이 없다. 실행 1회당 준비(설치·캐시 복원) 약 20~60초.

### 2.3.1 장시간 방치 방지 (v0.9.6 보강)

| 장치 | 동작 |
| --- | --- |
| 오래 대기한 작업 재요청 | 실행 시각이 `WORKER_STALE_AFTER_SECONDS`(기본 120초) 넘게 지난 작업이 있으면 Worker 실행을 다시 요청한다. 학생 화면이 전사·요약 상태를 확인할 때(응답 뒤)와 API 서버 주기 점검(`WORKER_SWEEP_INTERVAL_SECONDS`, 기본 300초)에서 확인하고, 프로세스당 `WORKER_REDISPATCH_INTERVAL_SECONDS`(기본 600초)에 한 번만 보낸다. 처음 요청이 실패했거나, 토큰을 나중에 넣었거나, 미뤄 둔 백업 작업이 실행 시각이 된 경우를 모두 처리한다 |
| 연속 실행 | 한 번 실행에서 처리 한도(`max_jobs`)까지 처리했으면 워크플로가 `GITHUB_TOKEN`으로 다음 실행을 바로 요청한다 (권한 `actions: write`). 한도만큼 처리했을 때만 요청하므로 처리할 수 없는 작업 때문에 반복되지 않는다 |
| 상태 확인 | `GET /api/v1/meta/worker-status` (인증 불필요): `dispatch_configured`(토큰 설정 여부), `due_jobs`, `oldest_due_minutes`, `last_dispatch`(마지막 요청 결과·GitHub 응답 코드). 토큰 값·작업 내용 없음 |

**Render Free 주의**: 15분 동안 요청이 없으면 서버가 잠들어 주기 점검도 멈춘다. 학생이 앱을 열면 서버가 깨어나 상태 확인과 함께 재요청이 동작한다. 아무도 앱을 열지 않는 동안에는 GitHub 예약 실행만 남는다.

### 2.4 Supabase

- 마이그레이션 `0009`까지 적용 (완료했다고 전달받음 — `backend/scripts/verify_dev_environment.py`로 확인 가능).
- Storage `feedback-audio` 버킷·정책 (`backend/supabase/storage-setup.sql` v0.5 블록)이 있어야 학생 토큰으로 Signed URL이 발급된다.
- DB 비밀번호는 Actions Secret에만. 연결 문자열에 쓰는 계정은 기존 API와 같은 계정 (작업 큐·전사 테이블 쓰기 필요).

## 3. 실행 방법

- 자동: 기본 브랜치(main)에 워크플로 파일이 있으면 15분마다 실행. **예약 실행은 기본 브랜치의 파일만 동작**한다.
- 수동: GitHub → Actions → `stt-worker` → Run workflow (max_jobs, max_minutes 입력). 또는 `gh workflow run stt-worker.yml -f max_jobs=5`.
- 로컬: `cd backend && uv sync --extra stt && uv run python -m app.worker --once --max-jobs 3 --max-seconds 600` (`DATABASE_URL` 필요).
- 대기 작업 수만: `uv run python -m app.worker --pending` → `{"transcribe": 1, "llm": 0, "total": 1}`.

## 4. 처리 시간·한계 (무료 운영)

| 항목 | 값 |
| --- | --- |
| 대기 시간 | 예약 15분 간격이지만 **실측 5.8~7.1시간 간격**(2026-11-11~12, 첫 실행은 병합 29시간 뒤) → **실시간 아님**. §2.3 즉시 실행을 켜면 작업 생성 직후 실행 요청 (GitHub 사정으로 늦어질 수 있음) |
| 실행 준비 | 의존성 설치 약 1분(uv 캐시), 모델 캐시 복원 수십 초, 모델 로드 수십 초. 전사 작업이 없으면 STT 설치·모델 생략 |
| 전사 속도 | 로컬 측정(아래 §5): 16초 음성 → 7.1초 (모델 로드 후). Actions 러너(4 vCPU)에서는 미측정 — 20분 녹음은 수 분~10분 내외 예상 |
| 사용량 | 공개 저장소의 표준 러너는 분 단위 과금 없음. 캐시 0.5GB (저장소 한도 10GB) |
| 예약 비활성화 | 공개 저장소에 60일간 활동이 없으면 GitHub가 예약 실행을 끈다 → 다시 켜야 함 |
| 동시 처리 | 실행 1개씩 → 녹음이 많이 몰리면 대기 증가 (한 실행 최대 10건) |
| Signed URL 만료 | 기본 24시간(v0.9.3, 이전 기본 6시간) 안에 처리 못 하면 `SOURCE_URL_EXPIRED` → 학생이 재시도 (새 URL 발급) |

## 5. 검증 결과

| 항목 | 결과 |
| --- | --- |
| 워크플로 YAML | actionlint 통과 (shellcheck 미설치로 셸 검사는 생략), 구조 테스트 `tests/test_stt_worker_cli.py` |
| Whisper 모델 로드·실행 | **로컬** Windows CPU에서 실제 `small`/INT8/ko 실행: 한국어 합성 음성 16.4초 → 4구간, 7.1초 (첫 로드·다운로드 48초). "명암"을 "명함"으로 인식한 오류 1건 → 전사 수정 기능으로 고치는 흐름 |
| 큐 처리·중복 방지·재시도·종류 선택·시간/개수 제한 | DB 테스트 `tests/db/test_worker_batch.py` (가짜 STT·Gemini) |
| 전사 수정·원본 보존, 요약 검토·확정, 성장 분석 연결 | 기존 v0.9 테스트 + 위 테스트 |
| CLI (`--pending`, `--once`) | 로컬 PostgreSQL에서 실행 확인 |
| **실제 GitHub Actions 실행** | **미검증** (워크플로가 기본 브랜치에 없고 Secret 미설정) |
| **Supabase Storage 실제 다운로드** | **미검증** |
| **Gemini 실제 호출** | **미검증** (승인 전) |

## 6. 주의 (개인정보)

- Gemini API **무료 등급**은 Google이 입력·출력을 서비스 개선에 사용할 수 있다는 약관이다. 학생(미성년자 포함) 첨삭 원문을 보내므로, 결제를 연결한 유료 등급(데이터 미사용)이 아니면 **동의서 문구와 법적 검토**가 필요하다. 월 0원을 유지하려면 무료 등급을 쓰게 되므로 이 점을 먼저 결정해야 한다.
- 음성 원본은 Actions 러너 메모리에서만 처리하고 디스크·로그·아티팩트에 남기지 않는다.
