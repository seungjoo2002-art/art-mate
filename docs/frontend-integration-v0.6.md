# 프론트엔드 연동 가이드 (v0.6 AI 첨삭 기록 · 요약 · 검토)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.6
> 선행 문서: [frontend-integration.md](frontend-integration.md) (인증·`api()`·오류 형식), [v0.5](frontend-integration-v0.5.md) (녹음 업로드·녹음 동의), [v0.5.1](frontend-integration-v0.5.1.md) (작품 분류·완료)
> 설계 배경: [ai-feedback-v0.6.md](ai-feedback-v0.6.md) · API 문서: http://127.0.0.1:8000/docs (최종 기준은 OpenAPI)

## 0. 흐름 한눈에

```text
학생 녹음 업로드 (v0.5)
  └─▶ ① 전사 요청 POST …/transcription         (서버 내부 STT, 외부 전송 없음)
        └─ 폴링 GET …/transcription            QUEUED → RUNNING → SUCCEEDED / FAILED
  └─▶ ② AI 요약 요청 POST …/summary            (Gemini 외부 전송 → 학생의 AI 전송 동의 필요)
        └─ 폴링 GET …/summary                  → feedback_id, feedback_status = DRAFT
  └─▶ ③ 검토·수정·승인
        학원 연결 작품: 담당 강사 (/academies/{id}/feedbacks/…)
        개인 작품:     학생 본인 (/feedbacks/…)
  └─▶ ④ 학생 아카이브 GET /artworks/{id}/feedbacks   (APPROVED만)
```

- ①에 `auto_summarize: true`를 주면 전사가 끝난 뒤 ②가 자동으로 큐에 들어갑니다 (그 시점에 학생의 AI 전송 동의가 있을 때만).
- 처리는 **비동기**입니다. 요청 API는 작업을 큐에 넣고 곧바로 응답합니다(202). 결과는 상태 API를 폴링해서 확인합니다.
- 서버 설정으로 기능이 꺼져 있으면 요청 API가 503(`STT_NOT_CONFIGURED`, `AI_NOT_CONFIGURED`)입니다. 이때는 버튼을 숨기거나 "준비 중"으로 표시하세요.

## 1. 동의 (두 가지는 서로 다릅니다)

| 동의 | API | 필요한 기능 | 비고 |
| --- | --- | --- | --- |
| 녹음 동의 (v0.5) | `/recording-consents` | 녹음 업로드, **전사** | 철회하면 대기 중 전사 취소, 새 전사 불가 |
| **AI 전송 동의 (v0.6)** | `/ai-processing-consents` | **AI 요약** | 녹음 동의로 대체되지 않음. 철회하면 대기·처리 중 요약 취소 |

```http
GET    /api/v1/ai-processing-consents/me
POST   /api/v1/ai-processing-consents        { "policy_version": "2026-11-ai-v1", "agreed": true, "granted_by": "SELF" }
DELETE /api/v1/ai-processing-consents/me     → 204
```

```json
// GET /ai-processing-consents/me
{ "provider": "GOOGLE_GEMINI", "required_version": "2026-11-ai-v1", "is_valid": false, "consent": null }
```

- 학생 계정만 사용합니다 (강사는 403). 강사가 요약을 요청해도 **학생의 동의**가 기준이며, 강사가 대신 동의할 수 없습니다.
- `is_valid: false`면 요약 버튼 대신 동의 화면을 보여 주세요. 버전이 바뀌면(`required_version` ≠ `consent.policy_version`) 다시 동의해야 합니다.

### AI 전송 동의 화면 요구사항

화면에 아래 내용을 **모두** 보여 주고, 체크박스(기본 해제)로 명시적 동의를 받은 뒤 `agreed: true`를 보냅니다.

| 항목 | 내용 |
| --- | --- |
| 목적 | 강사 첨삭 녹음의 전사문을 요약·분류해 학습 기록으로 정리 |
| 제공받는 자 | Google LLC (Gemini API) — **국외 이전** (미국 등) |
| 전송 항목 | 첨삭 녹음의 **전사문(문장과 시각)** 만. 이름·학교·작품 제목·계정 정보는 보내지 않음. 단, 녹음 안에서 말한 이름 등은 전사문에 포함될 수 있음 |
| 보관 | ART MATE: 전사·요약은 녹음을 삭제할 때까지. Google: 유료 API 약관에 따른 처리 (모델 학습에 사용하지 않는 유료 등급 사용) |
| 거부 권리 | 동의하지 않아도 녹음·전사는 사용할 수 있고, AI 요약만 쓰지 못함 |
| 철회 | 마이페이지에서 언제든 철회. 진행 중인 요약은 취소되고 이미 만든 요약은 남음(녹음 삭제 시 함께 삭제) |
| 만 14세 미만 | 법정대리인 동의가 필요 → 보호자 확인 후 `granted_by: "GUARDIAN"` |

> ⚠️ 위 문구·보관 기간·국외 이전 고지 항목과 미성년자·법정대리인 동의 절차는 **법적 검토 전 초안**입니다. 실제 서비스 전에 확정 문구로 교체합니다.

## 2. 전사 (STT)

```http
POST /api/v1/artworks/{artwork_id}/recordings/{recording_id}/transcription        { "auto_summarize": false }
POST /api/v1/artworks/{artwork_id}/recordings/{recording_id}/transcription/retry
GET  /api/v1/artworks/{artwork_id}/recordings/{recording_id}/transcription        상태
GET  /api/v1/artworks/{artwork_id}/recordings/{recording_id}/transcript           원문 (학생 본인)
# 담당 강사: 같은 경로 앞에 /academies/{academy_id}
```

```json
// POST …/transcription → 202 (새 작업) / 200 (이미 진행 중인 같은 작업)
{
  "id": "j1…", "job_type": "TRANSCRIBE", "status": "QUEUED", "attempts": 0, "max_attempts": 3,
  "next_attempt_at": "2026-11-09T11:02:00Z", "error_code": null, "retryable": false,
  "created_at": "…", "started_at": null, "finished_at": null
}

// GET …/transcription
{
  "recording_id": "r1…",
  "transcription_status": "COMPLETED",          // NOT_REQUESTED | PENDING | PROCESSING | COMPLETED | FAILED
  "job": { …JobRead… },
  "transcript": { "id": "t1…", "language": "ko", "duration_ms": 95400, "segment_count": 23,
                  "engine": "faster-whisper", "model_name": "small", "created_at": "…" }
}

// GET …/transcript
{
  "id": "t1…", "recording_id": "r1…", "language": "ko", "duration_ms": 95400, "segment_count": 23, …,
  "text": "전체적으로 구도는 안정적으로 잘 잡았어. 근데 오른쪽 사과의 …",
  "segments": [
    { "index": 0, "start_ms": 0,    "end_ms": 3500, "text": "전체적으로 구도는 안정적으로 잘 잡았어." },
    { "index": 1, "start_ms": 4000, "end_ms": 7500, "text": "근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보여." }
  ]
}
```

- 녹음 목록(`GET …/recordings`)의 `transcription_status`로 카드에 상태 배지를 표시할 수 있습니다.
- `segments[].start_ms`로 "이 부분 재생"(오디오 `currentTime = start_ms / 1000`)을 구현할 수 있습니다.

## 3. AI 요약

```http
POST /api/v1/artworks/{artwork_id}/recordings/{recording_id}/summary              요약 요청
POST /api/v1/artworks/{artwork_id}/recordings/{recording_id}/summary/regenerate   재생성
GET  /api/v1/artworks/{artwork_id}/recordings/{recording_id}/summary              상태
# 담당 강사: /academies/{academy_id}/artworks/…/summary[...]
```

```json
// GET …/summary
{
  "recording_id": "r1…",
  "job": { "job_type": "SUMMARIZE", "status": "SUCCEEDED", … },
  "feedback_id": "f1…",
  "feedback_status": "DRAFT",       // DRAFT | IN_REVIEW | APPROVED | null(아직 없음)
  "review_mode": "INSTRUCTOR"       // INSTRUCTOR: 담당 강사가 확정 / SELF: 학생 본인이 확정(개인 작품)
}
```

- 재생성: 승인 전 초안(DRAFT/IN_REVIEW/REJECTED)을 새 AI 초안으로 바꿉니다. 기존 초안은 `SUPERSEDED`로 남고 화면에서 사라집니다. 승인된 첨삭은 먼저 승인 취소(reopen)해야 합니다.

### 첨삭(요약) JSON

```json
// 강사 GET /academies/{id}/feedbacks/{feedback_id}  (학생 본인의 개인 작품 GET /feedbacks/{id}도 같은 형태)
{
  "id": "f1…", "recording_id": "r1…", "artwork_id": "a1…",
  "status": "DRAFT", "review_mode": "INSTRUCTOR", "version": 1,
  "summary": "구도는 안정적이나 오른쪽 사과의 명암이 약해 형태가 떠 보인다.",
  "strengths": [
    { "id": "i1…", "kind": "STRENGTH", "position": 0, "content": "구도를 안정적으로 잡았다.",
      "category": "COMPOSITION", "origin": "AI",
      "evidence": [ { "index": 0, "start_ms": 0, "end_ms": 3500 } ] }
  ],
  "weaknesses": [ { …"kind": "WEAKNESS", "category": "VALUE", "evidence": [{ "index": 1, … }] } ],
  "fixes":      [ { …"kind": "FIX" } ],
  "next_tips":  [ { …"kind": "NEXT_TIP" } ],
  "categories": ["FORM", "VALUE"],
  "approved_at": null, "approved_by_name": null,
  "created_at": "…", "updated_at": "…",
  // ↓ 검토자 화면에만
  "ai_draft": { "summary": "…", "strengths": [ { "text": "…", "category": "COMPOSITION", "evidence": [0] } ], … },
  "model_name": "gemini-3.1-flash-lite", "prompt_version": "feedback-summary-v1",
  "dropped_item_count": 0,            // 근거 구간이 없어 버린 AI 항목 수
  "rejected_reason": null,
  "artwork_title": "정물 기초디자인 04",
  "student": { "membership_id": "…", "user_id": "…", "display_name": "김학생", "avatar_path": null }  // 강사 화면만
}
```

| 필드 | 화면 |
| --- | --- |
| `strengths` / `weaknesses` / `fixes` / `next_tips` | 잘한 점 / 부족한 점 / 구체적인 수정 방법 / 다음 작품에서 주의할 점 |
| `categories` | 약점 카테고리 칩 (라벨: `GET /meta/options`의 `weakness_categories`) |
| `item.evidence` | "근거 듣기" 버튼 → 녹음의 `start_ms` 위치부터 재생 |
| `item.origin` | `AI` 그대로 / `EDITED` 사람이 수정 / `ADDED` 사람이 추가 (검토 화면에서 표시 권장) |
| `ai_draft` | AI 원본 (비교 보기). 수정해도 바뀌지 않음 |

약점 카테고리 코드: `COMPOSITION` 구도 · `FORM` 형태 · `PROPORTION` 비례 · `PERSPECTIVE` 투시 · `VALUE` 명암 · `COLOR` 색채 · `TEXTURE` 질감 · `RENDERING` 묘사 · `FINISH` 완성도 · `OTHER` 기타.

## 4. 검토 · 수정 · 승인

### 4.1 누가 검토하나

| 작품 | 검토자 | API 접두사 | 학생에게 보이는 것 |
| --- | --- | --- | --- |
| 학원 연결 작품 | 담당 강사, 학원 OWNER/MANAGER | `/api/v1/academies/{academy_id}/feedbacks` | **APPROVED만**. 그 전에는 `GET /feedbacks/{id}` → 403 `FEEDBACK_NOT_APPROVED` |
| 개인 작품 (학원 미연결) | **학생 본인** | `/api/v1/feedbacks` | 초안부터 전체 (본인이 확정) |

- 개인 작품은 강사에게 보이지 않습니다 (강사 경로 404). 학원 작품은 학생이 수정·승인할 수 없습니다 (403).
- 비담당 강사 403, 다른 학원 404, 다른 학생의 첨삭 404.

### 4.2 API

```http
# 강사
GET   /api/v1/academies/{academy_id}/feedbacks?status=DRAFT&status=IN_REVIEW&student_membership_id=…   검토 대기 (기본: DRAFT+IN_REVIEW, 오래된 순)
GET   /api/v1/academies/{academy_id}/feedbacks/{feedback_id}
PATCH /api/v1/academies/{academy_id}/feedbacks/{feedback_id}            수정
POST  /api/v1/academies/{academy_id}/feedbacks/{feedback_id}/approve    { "version": 2, "note": null }
POST  /api/v1/academies/{academy_id}/feedbacks/{feedback_id}/reject     { "version": 2, "reason": "다른 작품 첨삭이 섞임" }
POST  /api/v1/academies/{academy_id}/feedbacks/{feedback_id}/reopen     { "version": 3 }   승인 취소
GET   /api/v1/academies/{academy_id}/feedbacks/{feedback_id}/history
GET   /api/v1/academies/{academy_id}/artworks/{artwork_id}/recordings/{recording_id}/transcript   전사 원문

# 학생 (개인 작품) — 같은 동작을 /api/v1/feedbacks/{feedback_id}[/approve|/reject|/reopen|/history]
```

### 4.3 수정 요청 (전체 교체)

보낸 목록이 최종 상태입니다. 기존 항목은 `id`를 함께 보내고, 새 항목은 `id` 없이 보냅니다. 빠진 기존 항목은 삭제됩니다.

```json
// PATCH …/feedbacks/{feedback_id}
{
  "version": 1,
  "summary": "구도는 좋고, 오른쪽 사과 명암을 보강해야 한다.",
  "items": [
    { "id": "i1…", "kind": "STRENGTH", "content": "구도를 안정적으로 잡았다.", "category": "COMPOSITION" },
    { "id": "i2…", "kind": "WEAKNESS", "content": "오른쪽 사과 암부가 약하다.", "category": "VALUE" },
    { "kind": "FIX", "content": "암부를 4B로 한 톤 더 누른다.", "category": "VALUE", "evidence_segment_ids": [2] }
  ],
  "categories": ["VALUE", "PROPORTION"],
  "note": "표현 다듬음"
}
// → 200 ReviewerFeedbackRead (status: IN_REVIEW, version: 2)
```

- `evidence_segment_ids`를 생략하면 기존 항목의 근거가 유지되고, 새 항목은 근거 없이 저장됩니다. 범위 밖 번호는 422.
- 항목 수정 시 `origin`이 `AI` → `EDITED`로 바뀌고, AI 원본(`ai_draft`)은 그대로입니다.

### 4.4 상태 전이

```text
          (AI 생성)
              │
              ▼
           DRAFT ──수정──▶ IN_REVIEW ──수정──▶ IN_REVIEW
             │ │                 │ │
       승인 ─┘ └─ 반려      승인 ─┘ └─ 반려
             ▼      ▼            ▼      ▼
        APPROVED  REJECTED   APPROVED  REJECTED
             │                    (재생성 → 새 DRAFT, 기존은 SUPERSEDED)
        reopen
             ▼
        IN_REVIEW
```

| 동작 | 허용 상태 | 결과 | 오류 |
| --- | --- | --- | --- |
| 수정 PATCH | DRAFT, IN_REVIEW | IN_REVIEW, version+1 | APPROVED → 409 `FEEDBACK_ALREADY_APPROVED`, REJECTED → 409 `FEEDBACK_INVALID_STATE` |
| 승인 approve | DRAFT, IN_REVIEW | APPROVED, 승인자·시각 기록 | 〃 |
| 반려 reject | DRAFT, IN_REVIEW | REJECTED (재생성 가능) | 〃 |
| 승인 취소 reopen | APPROVED | IN_REVIEW, 학생 아카이브에서 빠짐 | APPROVED 아님 → 409 |
| 재생성 | 첨삭 없음, DRAFT, IN_REVIEW, REJECTED | 새 DRAFT | APPROVED → 409 |

- 모든 쓰기 요청에 조회한 `version`을 보냅니다. 다른 사람이 먼저 바꿨으면 409 `FEEDBACK_VERSION_CONFLICT`(`details.current_version`) → 다시 불러와 사용자에게 알립니다.
- 이력(`/history`): `CREATED`(AI, `actor_name: null`) · `EDITED`(변경 전후 `changes.before/after`) · `APPROVED`(승인 시점 스냅샷) · `REJECTED` · `REOPENED` · `SUPERSEDED`.

## 5. 학생 첨삭 아카이브

```http
GET /api/v1/artworks/{artwork_id}/feedbacks          확정 첨삭 목록 (최근 승인순)
GET /api/v1/feedbacks/{feedback_id}                  상세
```

- 목록 항목은 §3의 JSON에서 검토자 전용 필드(`ai_draft`, `model_name` 등)를 뺀 형태입니다.
- 승인 대기 중인지 보여 주려면 녹음별 `GET …/summary`의 `feedback_status`를 사용하세요 (`DRAFT`/`IN_REVIEW` → "선생님 확인 중").
- 약점 카테고리 라벨은 `GET /meta/options`의 `weakness_categories`, 항목 종류 라벨은 `feedback_item_kinds`.

## 6. 로딩 · 실패 · 재시도 UI

### 작업 상태(`job.status`)별 화면

| status | 표시 | 폴링 |
| --- | --- | --- |
| `QUEUED` (attempts=0) | "대기 중" | 5초 |
| `QUEUED` (attempts>0, `error_code` 있음) | "다시 시도하는 중 (n/3)" — `next_attempt_at`까지 대기 | 10초 |
| `RUNNING` | "변환 중…" / "AI가 정리하는 중…" (전사는 녹음 길이에 따라 수 분 걸릴 수 있음) | 5초 |
| `SUCCEEDED` | 결과 표시 | 중지 |
| `FAILED` | 오류 문구 + "다시 시도" 버튼 (`retryable: true`) | 중지 |
| `CANCELLED` | 사유별 안내 (아래) | 중지 |

- 폴링은 화면이 보일 때만, 최대 30분 정도에서 멈추고 "새로고침" 버튼을 보여 주세요.
- 다시 시도: 전사 → `POST …/transcription/retry`, 요약 → `POST …/summary/regenerate`(초안이 없으면 `POST …/summary`).

### 작업 오류 코드(`job.error_code`)

| code | 의미 | 안내 | 재시도 |
| --- | --- | --- | --- |
| `STT_TIMEOUT`, `STORAGE_UNAVAILABLE`, `LLM_TIMEOUT`, `LLM_RATE_LIMITED`, `LLM_UNAVAILABLE`, `LLM_INVALID_OUTPUT`, `LLM_EMPTY_RESPONSE`, `INTERNAL_ERROR`, `WORKER_LOST` | 일시적 오류 (자동 재시도 후에도 실패하면 FAILED) | "잠시 후 다시 시도해 주세요" | O |
| `SOURCE_URL_EXPIRED` | 오래 대기해 음성 접근 권한이 만료 | "다시 시도해 주세요" | O |
| `EMPTY_TRANSCRIPT` | 말소리를 인식하지 못함 | "녹음에서 말소리를 찾지 못했어요" | 같은 파일이면 의미 없음 |
| `AUDIO_DECODE_FAILED`, `AUDIO_NOT_FOUND`, `AUDIO_TOO_LARGE`, `AUDIO_TOO_LONG` | 파일 문제 | "이 녹음은 변환할 수 없어요" | X |
| `TRANSCRIPT_TOO_LONG`, `LLM_OUTPUT_TRUNCATED`, `LLM_BLOCKED` | 요약 불가 | "AI가 정리할 수 없는 녹음이에요. 직접 작성해 주세요" | X |
| `LLM_AUTH_FAILED`, `LLM_BAD_REQUEST`, `STT_NOT_CONFIGURED`, `AI_NOT_CONFIGURED` | 서버 설정 문제 | "잠시 후 이용해 주세요" + 운영자 문의 | X |
| `RECORDING_CONSENT_REVOKED`, `AI_CONSENT_REVOKED` (CANCELLED) | 동의 철회로 취소 | 동의 화면 링크 | 동의 후 O |
| `RECORDING_DELETED`, `FEEDBACK_ALREADY_APPROVED` (CANCELLED) | 대상 없음·이미 승인 | 목록 새로고침 | X |

## 7. API 오류 코드 (요청 응답)

| HTTP | code | 상황 | 처리 |
| --- | --- | --- | --- |
| 409 | `RECORDING_CONSENT_REQUIRED` | 학생의 녹음 동의가 철회됨 | 학생: 녹음 동의 화면 / 강사: "학생 동의 필요" |
| 409 | `AI_CONSENT_REQUIRED` | 학생의 AI 전송 동의 없음·구버전 (`details.required_version`) | 학생: §1 동의 화면 / 강사: "학생이 AI 정리에 동의해야 해요" |
| 409 | `TRANSCRIPTION_ALREADY_DONE` | 이미 전사됨 | 원문 보기로 이동 |
| 409 | `TRANSCRIPT_NOT_READY` | 전사 전 요약 요청·원문 조회 | 전사 먼저 |
| 409 | `JOB_NOT_RETRYABLE` | 실패·취소가 아닌데 재시도 | 상태 새로고침 |
| 409 | `FEEDBACK_INVALID_STATE` | 초안이 있는데 요약 요청(`details.feedback_id`), 반려된 첨삭 수정 | 재생성 또는 기존 초안 열기 |
| 409 | `FEEDBACK_ALREADY_APPROVED` | 승인된 첨삭 수정·재생성 | 승인 취소 후 |
| 409 | `FEEDBACK_VERSION_CONFLICT` | 동시 수정 | 다시 불러오기 |
| 403 | `FEEDBACK_NOT_APPROVED` | 학생이 승인 전 학원 작품 첨삭 조회 | "선생님 확인 중" |
| 422 | `RECORDING_TOO_LONG` | 전사 길이 상한 초과 (`details.max_seconds`) | 안내 |
| 503 | `STT_NOT_CONFIGURED` / `AI_NOT_CONFIGURED` | 서버에서 기능 꺼짐 | 버튼 숨김 |
| 503 | `STORAGE_NOT_CONFIGURED` / `STORAGE_UNAVAILABLE` | Storage 설정·장애 | 잠시 후 |

## 8. 화면별 API

| 화면 | 사용자 | API |
| --- | --- | --- |
| 녹음 카드 상태 배지 | 학생·강사 | 녹음 목록 `transcription_status`, 필요 시 `GET …/summary` |
| "AI로 피드백 정리하기" 버튼 (FeedbackRecordPage의 TODO) | 학생 | 동의 확인 `GET /ai-processing-consents/me` → `POST …/transcription { auto_summarize: true }` → 폴링 |
| AI 전송 동의 | 학생 | `GET/POST/DELETE /ai-processing-consents` |
| 강사 검토 대기함 | 강사 | `GET /academies/{id}/feedbacks` |
| 강사 검토 화면 (원문 + 초안 편집) | 강사 | `GET …/feedbacks/{id}`, `GET …/transcript`, `PATCH`, `approve`/`reject` |
| 개인 작품 AI 정리 확인 | 학생 | `GET /feedbacks/{id}`, `PATCH`, `approve` |
| 작품 상세 "첨삭" 탭 | 학생 | `GET /artworks/{id}/feedbacks` |
| 수정 이력 | 강사(학원) / 학생(개인) | `GET …/feedbacks/{id}/history` |

`api()`는 `body` 객체를 직접 `JSON.stringify` 하므로 **객체를 그대로** 넘깁니다 (v0.5.1 §8).
