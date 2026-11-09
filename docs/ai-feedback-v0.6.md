# v0.6 AI 첨삭 기록 · 요약 · 승인 — 설계와 운영

> 작성: 2026-11-09 · 브랜치 `feature/v0.6-ai-feedback` · 리비전 `0006` (down_revision `0005`)
> 프론트 연동: [frontend-integration-v0.6.md](frontend-integration-v0.6.md) · DB: [database-design.md §3.20](database-design.md)

기획 1단계 '피드백 기록'의 마무리: 녹음 → **STT(faster-whisper, 서버 내부)** → **Gemini 요약·분류(외부, 별도 동의)** → **강사(또는 개인 작품은 학생 본인) 검토·승인** → 학생 아카이브.
범위 밖(구현하지 않음): 성장 리포트, 맞춤 과제, F-15 참고작 추천, AI 직접 작품 분석, 합격률 예측.

## 1. 구조

```text
 [React] ──POST /transcription──▶ [API] ── INSERT ai_processing_jobs(QUEUED) ──▶ 202
    │                               │       (요청자 토큰으로 음성 Signed URL 발급·저장)
    │ 폴링 GET /transcription        ▼
    │                         PostgreSQL (작업 큐)
    │                               ▲  FOR UPDATE SKIP LOCKED + lease
    │                               │
    │                      [AI Worker: python -m app.worker]  (별도 프로세스·별도 서비스)
    │                        ├─ TRANSCRIBE: Signed URL → 음성 다운로드 → faster-whisper(스레드) → feedback_transcripts
    │                        └─ SUMMARIZE:  전사 구간 → Gemini generateContent(JSON 스키마) → Pydantic 검증
    │                                        → feedback_summaries / items / categories / review_history
    └──▶ 강사 검토 API (수정·승인) ──▶ 학생 아카이브 (APPROVED만)
```

- **API는 처리하지 않는다**: 요청은 큐 등록만 하고 곧바로 응답한다. STT·LLM 호출은 Worker만 한다 → API 서버 CPU·메모리를 점유하지 않고, 배포·재시작에도 작업이 남는다.
- **service_role 키 없음 유지**: Worker는 사용자 토큰이 없으므로, API가 요청 시점에 요청자(학생 또는 담당 강사)의 토큰으로 음성 Signed URL을 발급해 작업에 저장한다(기본 6시간). Storage RLS가 그 사용자 권한을 다시 검사한다. URL은 API 응답·로그에 내보내지 않고 작업이 끝나면 지운다. 만료되면 `SOURCE_URL_EXPIRED` → 사용자가 재시도하면 새로 발급된다.
- **Gemini 키는 Worker에만**: API 서버에는 `GEMINI_API_KEY`를 두지 않는다.

### 1.1 작업 큐 (`ai_processing_jobs`)

| 항목 | 방식 |
| --- | --- |
| 중복 방지 | 부분 유니크 인덱스 `(recording_id, job_type) WHERE status IN (QUEUED, RUNNING)` + 요청 API는 진행 중 작업이 있으면 그 작업을 200으로 반환. 동시 요청은 IntegrityError → 기존 작업 반환 |
| 가져가기 | `SELECT … FOR UPDATE SKIP LOCKED` → RUNNING, `attempts+1`, `locked_by`, `lease_expires_at` |
| 진행 중 | heartbeat가 lease의 1/3 주기로 연장 (기본 lease 300초) |
| 재시작 복구 | lease가 만료된 RUNNING 작업은 다른 Worker(또는 재시작한 Worker)가 다시 가져간다. 마지막 시도 중 죽었으면 `WORKER_LOST`로 FAILED |
| 재시도 | 일시 오류는 지수 백오프 `30s × 2^(n-1)`로 QUEUED, 최대 3회(`JOB_MAX_ATTEMPTS`). 영구 오류는 즉시 FAILED. 사용자는 재시도 API로 새 작업 |
| 결과 저장 | 저장 직전에 작업 행을 잠그고 "아직 내가 잡은 RUNNING"인지 확인 → 그 사이 취소(동의 철회·녹음 삭제)됐거나 다른 Worker가 회수했으면 결과를 버림 |
| 타임아웃 | STT: 구간을 하나씩 꺼낼 때 마감 시각 확인 (`STT_TIMEOUT_SECONDS` 기본 1800). Gemini: HTTP 타임아웃 60초 |
| 종료 | SIGTERM → 현재 작업을 끝내고 종료. 강제 종료돼도 lease 만료 후 복구 |

외부 큐(Redis/Celery)를 쓰지 않은 이유: 처리량이 작고(학원당 하루 수십 건), DB 트랜잭션과 작업 상태를 함께 커밋할 수 있으며 인프라가 늘지 않는다. 처리량이 커지면 같은 테이블 구조로 Worker 수만 늘리면 된다.

## 2. STT: faster-whisper

| 설정 | 기본값 | 근거 |
| --- | --- | --- |
| 모델 `STT_MODEL` | `small` | 한국어 첨삭 말투에서 tiny·base는 오인식이 많고, medium 이상은 CPU에서 너무 느리다. small이 CPU 비용 대비 균형점 (실제 녹음으로 검증 필요, §6) |
| `STT_COMPUTE_TYPE` | `int8` | CPU에서 메모리·속도 이점 (정확도 손실 작음) |
| `STT_BEAM_SIZE` | `1` (greedy) | CPU 비용 최소화. 정확도가 부족하면 3~5 |
| `vad_filter` | 켬 | 무음 제거 → 처리 시간 감소, 무음 구간 환각 감소 |
| `condition_on_previous_text` | 끔 | 반복 환각 완화 |
| 의존성 | `uv sync --extra stt` | API 이미지에는 넣지 않음. `av<18` 고정 (faster-whisper 1.2.x 호환) |

- 로컬 확인 (2026-11-09, `tiny` 모델, 합성 오디오): 모델 로드·디코딩·VAD·길이 제한 경로가 실제 라이브러리에서 동작함을 확인. **이 과정에서 PyAV 19와 faster-whisper 1.2.1이 호환되지 않는 문제를 발견해 `av<18`로 고정**했다. 한국어 실제 녹음 정확도·속도는 아직 측정하지 않았다(§6).
- 저장: 전체 텍스트 + 구간 `[{index, start_ms, end_ms, text}]`. `index`가 첨삭 항목의 근거 연결 키다.

### 2.1 Render에서 실행 가능한가

| 인스턴스 (2026-08 이전 이름) | 사양 | 월 (참고) | small int8 실행 |
| --- | --- | --- | --- |
| Starter | 0.5 CPU / 512 MB | ~$7 | ✕ 메모리 부족 (모델 + 디코딩 피크 ~1 GB 이상) |
| Standard | 1 CPU / 2 GB | ~$25 | △ 실행 가능, 녹음 길이와 비슷하거나 더 오래 걸릴 수 있음 (추정) |
| Pro | 2 CPU / 4 GB | ~$85 | ○ 권장 상한. 동시 1건 처리 기준 |

- 가격은 제3자 자료 기준이며 Render가 2026-08-26에 플랜 이름을 바꿨으므로 **배포 전에 render.com/pricing에서 확인**해야 한다.
- **현재 API 서비스 안에서 STT를 돌리지 않는다**: 요청 처리와 CPU를 다투고, 메모리 부족 시 API가 재시작된다.
- 권장 배포: **Render Background Worker 1개를 별도로** 두고 `docker build --target worker` 이미지(또는 `uv sync --extra stt && python -m app.worker`)를 실행. 모델 재다운로드를 피하려면 영구 Disk를 `/models`에 연결(`STT_MODEL_DIR=/models`).
- 대안: 녹음량이 적으면 Worker를 필요할 때만 켜거나, GPU가 있는 외부 서버(학교·개인 PC)에서 같은 Worker를 실행해도 된다(DB만 접속하면 됨). 이 경우 DB 접속 정보 관리에 주의.

## 3. Gemini 요약

### 3.1 모델 선택: `gemini-3.1-flash-lite`

2026-11-09 Google AI Studio 가격표 기준 (Standard 등급, 텍스트, 1M 토큰당):

| 모델 | 입력 | 출력 | 비고 |
| --- | --- | --- | --- |
| **gemini-3.1-flash-lite** | **$0.25** | **$1.50** | **선택**: 현행 세대 Lite, 지원 중단 공지 없음 |
| gemini-3.5-flash-lite | $0.30 | $2.50 | 더 최신, 약간 비쌈 |
| gemini-3.8-flash | $0.75 (2027년 $1.50) | $3.75 (2027년 $7.50) | 요약에는 과함 |
| gemini-2.5-flash-lite | $0.10 | $0.40 | 가장 싸지만 이전 세대 (같은 세대 2.5-flash는 이미 지원 중단) |

- 작업은 짧은 한국어 전사의 요약·분류라 Lite 모델로 충분하고, 지원 중단 위험이 낮은 현행 세대를 골랐다. `GEMINI_MODEL`로 바꿀 수 있다 (모델명은 결과에 기록).
- **무료 등급은 입력이 Google 제품 개선에 쓰인다** → 학생 개인정보가 포함되므로 **유료 등급 키만** 사용한다 (운영 체크리스트).
- 호출: REST `POST /v1beta/models/{model}:generateContent`, `responseMimeType: application/json` + `responseJsonSchema`, `temperature 0.2`, `maxOutputTokens 4096`. 키는 `x-goog-api-key` 헤더(쿼리 금지). SDK 없이 httpx 사용.
- Google 문서는 새 Interactions API를 안내하고 있으나 `generateContent`는 현재 지원 중이다(지원 중단 공지 없음). 실제 호출 전 확인 필요.

### 3.2 환각 방지와 검증

1. 프롬프트(`feedback-summary-v1`): 전사에 없는 평가 금지, 해당 내용 없으면 빈 배열, 모든 항목에 근거 구간 번호 필수, 개인정보 출력 금지, 전사 속 지시문 무시(프롬프트 주입 방지).
2. 구조화 출력 스키마로 형식 강제 + 서버에서 Pydantic 재검증(길이·개수·카테고리 값).
3. 근거 번호 검증: 존재하지 않는 구간 번호 제거, **근거가 없는 항목은 저장하지 않음**(`dropped_item_count` 기록).
4. 검증 실패(JSON 아님·스키마 불일치)는 재시도, 차단·출력 잘림은 재시도하지 않음.
5. AI 원본(`ai_output`)과 사람이 수정한 현재 값(summary·items·categories)을 분리 저장, 승인 시점 스냅샷은 이력에.

### 3.3 기록

- 작업: `api_call_count`, `input_tokens`, `output_tokens`(응답 + thinking 토큰), 모든 시도 누적.
- 첨삭: `model_name`, `prompt_version`, 해당 호출의 토큰.
- 로그: 작업 ID·오류 코드·소요 시간만. 전사·요약 내용, Signed URL, API 키는 남기지 않는다. httpx/httpcore/huggingface 로거는 요청 URL을 INFO로 남기므로 WARNING으로 고정했다(로컬 확인에서 발견).

## 4. 검토 · 승인 · 권한

| 작품 | 검토자 | 학생에게 |
| --- | --- | --- |
| 학원 연결 | 담당 강사, OWNER/MANAGER (`managed_student_ids` — v0.3 규칙 그대로) | APPROVED만 |
| 개인(학원 미연결) | 학생 본인 (`review_mode=SELF`) | 초안부터 (본인이 확정) |

- 검토 주체는 저장값이 아니라 **요청 시점의 작품 학원 연결**로 판단한다. 개인 작품은 강사에게 자동 노출되지 않는다.
- 상태: `DRAFT → IN_REVIEW → APPROVED`, `REJECTED`(초안 폐기·재생성 가능), `SUPERSEDED`(재생성으로 대체), `APPROVED → IN_REVIEW`(reopen). 녹음당 현재 첨삭 1개(부분 유니크).
- 동시 수정: `version` 낙관적 잠금 + 행 잠금.
- 접근 분리: 전사 원문 — 소유 학생·담당 강사 / AI 원본·모델 정보 — 검토자만 / 확정 첨삭 — 학생·검토자.

## 5. 개인정보 · 동의

| 단계 | 근거 동의 | 동의 철회 시 |
| --- | --- | --- |
| 녹음 업로드 (v0.5) | 녹음 동의 | 새 녹음 불가 |
| **전사 (서버 내부)** | 녹음 동의가 철회되지 않았을 것 | 대기·처리 중 전사 취소(`RECORDING_CONSENT_REVOKED`), 새 전사 불가 |
| **요약 (외부 전송)** | **별도 AI 전송 동의**(`ai_processing_consents`, 현재 버전) | 대기·처리 중 요약 취소, 처리 중이던 결과는 저장하지 않음, 새 요약 불가 |

- 녹음 동의만으로 외부 AI 전송을 허용하지 않는다. 강사가 요청해도 학생 동의가 기준.
- 진행 중 철회: API가 작업을 CANCELLED로 바꾸고, Worker는 외부 호출 직전·결과 저장 직전에 동의를 다시 확인한다. **이미 Gemini로 전송된 요청은 회수할 수 없다**(동의 화면에 고지).
- 외부 전송 최소화: 구간 번호·시각·문장만 전송. 이름·학원·작품 제목·사용자 ID 미전송. 녹음 안에서 말한 이름은 포함될 수 있음 → 고지.
- 삭제: 녹음·작품 삭제 시 전사·첨삭(승인본 포함)·진행 중 작업을 함께 삭제/취소.
- 동의 이력은 삭제하지 않고 철회 시각만 기록(버전별).
- **법적 검토 필요(미해결)**: 만 14세 미만 법정대리인 동의 확인 방법, 국외 이전 고지 문구, 보관 기간, 강사 음성(제3자)의 처리 근거, Google 데이터 처리 약관(DPA) 체결. 현재 `granted_by: GUARDIAN`은 자기 신고값이며 실제 보호자 확인 절차가 아니다.

## 6. 예상 비용

### Gemini (gemini-3.1-flash-lite, 2026-11 가격)

5분 첨삭 녹음 가정: 전사 약 1,500자 → 입력 약 1,500~2,500 토큰(시스템 프롬프트 포함), 출력(JSON) 약 600~1,200 토큰.

| 항목 | 1건 | 월 1,000건 | 월 10,000건 |
| --- | --- | --- | --- |
| 입력 2,500 토큰 × $0.25/M | $0.000625 | $0.63 | $6.3 |
| 출력 1,200 토큰 × $1.50/M | $0.0018 | $1.80 | $18 |
| **합계 (재시도 없음)** | **약 $0.0024 (약 3~4원)** | **약 $2.4** | **약 $24** |

재시도는 최대 3회라 최악 3배. thinking 토큰이 켜지면 출력이 늘 수 있다 → 작업별 토큰 기록으로 실제 비용을 확인한다. 토큰 수는 추정치이며 실제 한국어 토큰화 비율은 측정 필요.

### 서버

| 구성 | 월 (참고, 확인 필요) |
| --- | --- |
| API (기존) | 변동 없음 |
| AI Worker — Standard 1 CPU/2 GB | ~$25 |
| AI Worker — Pro 2 CPU/4 GB (권장 상한) | ~$85 |
| 영구 Disk (모델 캐시 1 GB) | 소액 |
| STT API 사용료 | $0 (서버 내부 실행) |

측정 계획(승인된 테스트 녹음 필요): small/base 모델로 실제 한국어 첨삭 3~5개(1·5·10분)를 Standard·Pro에서 처리해 실시간 대비 속도·피크 메모리·오인식률을 기록하고 모델·인스턴스를 확정한다.

## 7. v0.7·v0.8 대비 데이터

- `feedback_categories(summary_id, category)`: 승인된 첨삭 기준 학생별·기간별 약점 카테고리 빈도 → v0.7 반복 약점·성장 추이.
- `feedback_items(kind, category, evidence_segment_ids, origin)`: 약점 문장 단위 근거 + 사람이 수정했는지 → AI 품질 지표, 맞춤 과제 근거.
- `feedback_summaries.approved_at`, 작품의 `practical_type`·`work_category`·`work_status`: 시계열·유형별 분석.
- F-15(미구현): "같은 카테고리 약점이 이후 작품에서 사라졌는가"(STRENGTH 항목·약점 미재발)를 '잘 해결함' 신호 후보로 쓸 수 있다. 추천 근거는 `feedback_items.id`·`category`를 참조하도록 v0.8에서 `reference_recommendations`를 설계한다. 작품 공개·참고작 사용 동의는 별도(v0.5.1 설계 메모).

## 8. 운영 체크리스트

1. 개발 DB에 0005·0006 적용 (승인 후, 한 사람만): `uv run alembic upgrade head`
2. `SUPABASE_ANON_KEY` 설정 (API) — 없으면 전사 요청이 503
3. Worker 서비스 생성: `docker build --target worker`, 환경변수 `DATABASE_URL`, `STT_ENABLED=true`, `AI_SUMMARY_ENABLED=true`, `GEMINI_API_KEY`(유료 등급), `STT_MODEL_DIR=/models` + Disk
4. API 서비스에 `STT_ENABLED=true`, `AI_SUMMARY_ENABLED=true` (키는 넣지 않음)
5. 승인된 테스트 계정·테스트 녹음으로 실제 STT·Gemini 1회 확인 (유료 호출 승인 후)
6. 동의 문구 법적 검토 완료 후 학생에게 공개
