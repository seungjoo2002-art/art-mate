# 프론트엔드 연동 가이드 (v0.9 기능명세서 V2 1~2단계)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.9 (Alembic `0009`)
> 선행 문서: [frontend-integration.md](frontend-integration.md) (인증·`api()`·오류 형식), [v0.6](frontend-integration-v0.6.md) (녹음 전사·AI 요약·검토), [v0.7](frontend-integration-v0.7.md) (성장 분석·추천), [v0.8](frontend-integration-v0.8.md) (공유·커뮤니티)
> 설계: [v2-backend-completion-v0.9.md](v2-backend-completion-v0.9.md) · API 문서: http://127.0.0.1:8000/docs

모든 API는 `Authorization: Bearer <Supabase access token>`이 필요합니다 (`/meta/options` 제외). 오류 형식은 기존과 같습니다:
`{"error": {"code": "...", "message": "...", "details": ...}}`. 표의 **권한** 열: STUDENT = 학생 계정, 로그인 = 프로필이 있는 모든 사용자.

## 0. 학생 단독 학습 사이클 (학원·강사 계정 없이)

```text
회원가입 POST /users/me
 → 학습 목표 PATCH /users/me {grade, practical_type, learning_goal} · 지망 대학 POST /users/me/target-universities
 → 작품 등록 POST /artworks {topic, work_method, work_category, time_limit_minutes}
     → 단계별 사진 POST /artworks/{id}/photos → Storage PUT → POST …/photos/{pid}/complete   (기존)
     → 타이머 POST /artworks/{id}/timer/events {START|PAUSE|RESUME|STOP}  (또는 actual_minutes 직접 입력)
 → 첨삭 입력
     A. 텍스트: POST /artworks/{id}/feedback-notes {source, body, request_summary:true}
     B. 음성:   POST /artworks/{id}/recordings … → POST …/transcription {auto_summarize:true}  (기존)
               → (선택) 전사 수정 PUT …/recordings/{rid}/transcript
 → AI 요약 완료 확인 (폴링) GET /feedback-notes/{id} 의 feedback_status / GET …/recordings/{rid}/summary
 → 본인 검토·수정·확정 GET/PATCH /feedbacks/{fid} → POST /feedbacks/{fid}/approve
 → 성장 아카이브 GET /growth/me/timeline · 약점별 과거 첨삭 · 작품 비교
 → 성장 리포트 POST /growth/me/reports
 → 맞춤 과제 POST /growth/me/recommendations {scope:"PERSONAL"} → adopt → start
 → 과제 수행 작품 POST /artworks {recommendation_id} → 첨삭 → 후속 분석 GET …/follow-up
 → 알림 GET /notifications
```

- AI 요약(Gemini 외부 전송)에는 **AI 전송 동의**가 필요합니다: `POST /ai-processing-consents {policy_version, agreed:true}` (v0.6). 동의 없이도 텍스트 첨삭 저장·수정·삭제는 됩니다.
- **개인 작품**(학원 미연결)과 **자기 메모·다른 학생 의견**은 학생이 직접 확정합니다. 학원 작품에 적은 **강사 첨삭**은 기존처럼 담당 강사가 확정합니다.

## 1. 프로필·학습 목표 (F-1)

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| PATCH | `/api/v1/users/me` | 기존 + `grade`, `learning_goal` | 로그인 |
| GET | `/api/v1/users/me/learning-context` | 실기 유형·학년·목표·지망 대학 한 번에 | STUDENT |
| GET | `/api/v1/users/me/target-universities` | 지망 대학 (1지망부터) | STUDENT |
| POST | `/api/v1/users/me/target-universities` | 추가 (최대 10) | STUDENT |
| PATCH | `/api/v1/users/me/target-universities/{id}` | 이름·학과·메모 수정, `priority`로 순위 이동 | STUDENT |
| PUT | `/api/v1/users/me/target-universities/order` | 전체 순서 변경 | STUDENT |
| DELETE | `/api/v1/users/me/target-universities/{id}` | 삭제 (뒤 순위 당겨짐) | STUDENT |

```json
// PATCH /users/me
{ "grade": "HIGH_2", "practical_type": "BASIC_DESIGN", "learning_goal": "명암 단계 익히기" }
// → MeRead (+ "grade", "learning_goal", "learning_goal_updated_at")
// learning_goal이 실제로 바뀔 때만 learning_goal_updated_at(목표 수정일)이 갱신된다. null이면 삭제.

// POST /users/me/target-universities  → 201
{ "university_name": "홍익대학교", "department": "시각디자인", "admission_note": "수시 실기", "priority": 1 }
// priority 생략 = 맨 뒤. 지정하면 그 자리에 넣고 뒤로 민다.
{ "id": "u1…", "university_name": "홍익대학교", "department": "시각디자인", "admission_note": "수시 실기",
  "priority": 1, "created_at": "…", "updated_at": "…" }

// PUT /users/me/target-universities/order  (내 지망 대학 전체를 빠짐없이)
{ "ids": ["u3…", "u1…", "u2…"] }   // → 200 [TargetUniversityRead…]
```

- 학년 선택지: `GET /meta/options`의 `grades` (MIDDLE_SCHOOL, HIGH_1~3, GRADUATE, OTHER).
- 대학 정보는 직접 입력이며 입시 정보·합격 예측은 제공하지 않습니다.
- 오류: 11개째 409 `TARGET_UNIVERSITY_LIMIT`, order에 일부만 보냄 422, 다른 사람 대학 id 404, 강사 계정 403.

## 2. 작품 정보·시간 기록 (F-2)

`POST /artworks`, `PATCH /artworks/{id}`에 필드 추가 (모두 선택):

| 필드 | 설명 |
| --- | --- |
| `topic` | 실기 주제 (200자) |
| `work_method` | 작업 방식 (재료·기법, 100자) |
| `work_category` | (기존) `MOCK_EXAM` 모의 실기시험 / `PERSONAL_PRACTICE` / `CLASS_WORK` |
| `actual_minutes` | 실제 소요 시간(분, 1~1440). 직접 입력하면 `time_source=MANUAL`, `null`이면 삭제 |
| `time_limit_minutes` | 제한 시간(분, 1~1440) |
| `recommendation_id` | (생성 시만) 개인 맞춤 과제의 수행 작품으로 연결 (§7) |

응답(ArtworkRead/Detail)에 `topic, work_method, actual_minutes, time_limit_minutes, time_source, over_time_limit`가 추가됩니다. `over_time_limit`은 두 시간이 모두 있을 때만 true/false (초과 기록도 저장은 됩니다). 0·음수·1440 초과는 422.

사진 단계(스케치·진행·완성)는 기존 그대로 일부만 올려도 저장됩니다.

### 2.1 타이머 (서버는 기록·계산만)

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/v1/artworks/{id}/timer` | 현재 상태 복원 (새로고침·앱 재시작 후) |
| POST | `/api/v1/artworks/{id}/timer/events` | `START` / `PAUSE` / `RESUME` / `STOP` / `RESET` |

```json
// POST /artworks/{id}/timer/events
{ "event": "PAUSE", "occurred_at": "2026-11-10T09:30:00+09:00" }   // occurred_at 생략 = 서버 시각
// → 200 TimerRead
{
  "artwork_id": "a1…", "state": "PAUSED",          // IDLE | RUNNING | PAUSED | STOPPED
  "elapsed_seconds": 1800,                          // 현재 세션 누적 (RUNNING이면 지금까지)
  "running_since": null,                            // RUNNING이면 마지막 시작·재개 시각
  "session_started_at": "…",
  "time_limit_minutes": 240, "remaining_seconds": 12600, "over_time_limit": false,
  "actual_minutes": null, "time_source": null,
  "server_time": "…",
  "events": [ { "id": "…", "event": "START", "occurred_at": "…", "elapsed_seconds": 0 },
              { "id": "…", "event": "PAUSE", "occurred_at": "…", "elapsed_seconds": 1800 } ]
}
```

- 화면 표시: `RUNNING`이면 `elapsed_seconds + (지금 − server_time)`으로 클라이언트가 초를 셉니다. 서버는 타이머를 돌리지 않습니다.
- `STOP` → 누적 시간을 분 단위로 올림해 작품의 `actual_minutes`(`time_source=TIMER`)로 저장합니다. 다시 `START`하면 새 세션(0초부터)이고, 다음 `STOP`이 값을 덮어씁니다.
- 오프라인: 이벤트를 모아 두었다가 `occurred_at`을 붙여 순서대로 보냅니다 (직전 이벤트보다 이르거나, 미래이거나, 24시간보다 오래되면 422 `TIMER_INVALID_TIME`).
- 오류: 허용되지 않는 전이 409 `TIMER_INVALID_TRANSITION` (`details.allowed`), 24시간 초과 422 `TIMER_TOO_LONG` (RESET 후 직접 입력).

## 3. 텍스트 첨삭 (F-3)

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| POST | `/api/v1/artworks/{artwork_id}/feedback-notes` | 첨삭 입력 (작품당 여러 개, 최대 50) | STUDENT (작품 소유자) |
| GET | `/api/v1/artworks/{artwork_id}/feedback-notes` | 작품의 첨삭 목록 | 〃 |
| GET | `/api/v1/feedback-notes/{note_id}` | 원문·요약 상태 | 〃 |
| PATCH | `/api/v1/feedback-notes/{note_id}` | 원문·출처·날짜 수정 (version 필수) | 〃 |
| DELETE | `/api/v1/feedback-notes/{note_id}` | 삭제 (요약·이력 함께, 성장 분석에서 제외) | 〃 |
| POST | `/api/v1/feedback-notes/{note_id}/summary` | AI 요약·분류 요청 (202/200) | 〃 |

```json
// POST /artworks/{id}/feedback-notes  → 201
{ "source": "INSTRUCTOR",            // INSTRUCTOR 강사 첨삭을 받아 적음 / SELF_NOTE 자기 메모 / PEER 다른 학생 의견
  "body": "구도는 안정적이다. 오른쪽 컵의 명암이 약하다.\n시간 안에 배경을 끝내지 못했다.",
  "feedback_date": "2026-11-10",     // 생략 = 오늘
  "request_summary": true }          // AI 동의가 있으면 바로 요약 요청 (없으면 저장만, summary_job=null)

// → FeedbackNoteRead
{
  "id": "n1…", "artwork_id": "a1…", "source": "INSTRUCTOR", "body": "…",
  "segments": [ {"index": 0, "text": "구도는 안정적이다."}, {"index": 1, "text": "오른쪽 컵의 명암이 약하다."},
                {"index": 2, "text": "시간 안에 배경을 끝내지 못했다."} ],
  "feedback_date": "2026-11-10", "version": 1, "community_comment_id": null,
  "feedback_id": null, "feedback_status": null,      // 요약이 생기면 id·상태 (DRAFT/IN_REVIEW/APPROVED)
  "review_mode": "SELF",                             // SELF 내가 확정 / INSTRUCTOR 학원 강사가 확정
  "summary_job": { "id": "j1…", "job_type": "SUMMARIZE", "status": "QUEUED", "attempts": 0, … },
  "created_at": "…", "updated_at": "…"
}

// PATCH /feedback-notes/{id}
{ "version": 1, "body": "고친 원문" }   // source, feedback_date도 가능
```

- 원문은 문장 단위(`segments`)로 나뉘고, AI 요약 항목의 **근거 번호**가 이 index를 가리킵니다.
- 원문·출처를 바꾸면 초안·검토 중 요약은 대체되고 진행 중 작업은 취소됩니다(`summary_job.status=CANCELLED`, `error_code=NOTE_EDITED`) → 다시 요약을 요청하세요. **확정된 요약이 있으면** 409 `FEEDBACK_NOTE_LOCKED` → 먼저 `POST /feedbacks/{fid}/reopen`.
- 오류: 버전 불일치 409 `FEEDBACK_VERSION_CONFLICT`, 50개 초과 409 `FEEDBACK_NOTE_LIMIT`, 요약 요청 시 동의 없음 409 `AI_CONSENT_REQUIRED`, 초안이 이미 있음 409 `FEEDBACK_INVALID_STATE`(→ `{"regenerate": true}`), 확정됨 409 `FEEDBACK_ALREADY_APPROVED`, AI 꺼짐 503 `AI_NOT_CONFIGURED`.

### 3.1 AI 요약 상태 폴링

```text
POST /feedback-notes/{id}/summary  → 202 JobRead (진행 중이면 200 같은 작업)
반복: GET /feedback-notes/{id}
  summary_job.status: QUEUED → RUNNING → SUCCEEDED (feedback_id 생김) | FAILED(retryable) | CANCELLED
  FAILED면 같은 POST로 다시 요청 (error_code: LLM_INVALID_OUTPUT, LLM_RATE_LIMITED, LLM_TIMEOUT …)
```

### 3.2 녹음 → 전사 → 요약 처리 상태 (v0.9.1, GitHub Actions 처리)

> **v0.9.2**: 녹음 직후 학생 기기에서 먼저 전사하고(`POST …/transcript/browser`, [browser-stt-v0.9.2.md](browser-stt-v0.9.2.md)), 실패·미지원일 때만 아래 서버 처리로 넘어갑니다. 전사 응답의 `origin`(SERVER/BROWSER/EDITED)으로 출처를 구분합니다.

전사·요약은 서버가 즉시 처리하지 않고 **GitHub Actions가 약 15분마다(지연 가능)** 처리합니다 ([stt-worker-github-actions.md](stt-worker-github-actions.md)). 새 API는 없고 기존 API로 상태를 보여 주세요.

| 단계 | API | 표시 |
| --- | --- | --- |
| 전사 요청 | `POST /artworks/{aid}/recordings/{rid}/transcription` `{auto_summarize}` → 202 | "변환 대기 중 (보통 15~60분)" |
| 상태 조회 | `GET …/transcription` → `transcription_status` PENDING / PROCESSING / COMPLETED / FAILED, `job.status` QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELLED, `job.error_code` | 대기 / 처리 중 / 완료 / 실패(재시도 버튼) |
| 실패 재시도 | `POST …/transcription/retry` (FAILED·CANCELLED일 때) | `SOURCE_URL_EXPIRED`는 오래 대기해 링크가 만료된 경우 → 재시도하면 됨 |
| 전사 확인·수정 | `GET …/transcript`, `PUT …/transcript` | 원본 보존, 수정본이 현재 전사 |
| 요약 요청 (전사 확정) | `POST …/summary` (auto_summarize면 생략) | "AI 요약 대기 중" |
| 요약 상태 | `GET …/summary` → `job.status`, `feedback_id`, `feedback_status` | 완료되면 `/feedbacks/{feedback_id}`로 검토·확정 |

- 목록에서는 `GET /artworks/{aid}/recordings`의 `transcription_status`로 배지를 표시하세요. 폴링은 화면을 열었을 때·1~2분 간격이면 충분합니다.
- auto_summarize=true면 학생이 전사를 보기 전에 요약이 만들어질 수 있습니다. "전사 확인 후 요약"을 원하면 false로 요청하고 확인·수정 후 `POST …/summary`를 호출하세요.
- 요약 기능이 꺼져 있으면(`AI_SUMMARY_ENABLED=false`) 요약 요청은 503 `AI_NOT_CONFIGURED`, 서버만 켜고 처리기가 꺼져 있으면 `job.status=QUEUED`로 대기합니다.

### 3.3 녹음 첨삭 보완 (v0.6 API에 추가)

| Method | Path | 설명 |
| --- | --- | --- |
| PUT | `/api/v1/artworks/{aid}/recordings/{rid}/transcript` | STT 결과 수정 (학생 본인) |

```json
// PUT …/transcript  — 바꾼 구간의 문장만 (구간 번호·시각은 그대로)
{ "base_transcript_id": "t1…", "segments": [ { "index": 1, "text": "오른쪽 사과의 명암이 약하다." } ] }
// → 200 TranscriptRead (+ "edited": true, "edited_from_id": "t1…")
```

- 원본 전사는 보존되고 새 버전이 현재 전사가 됩니다. 초안 요약은 대체되므로 `POST …/summary`로 다시 요청하세요.
- 오류: 최신이 아닌 base 409 `FEEDBACK_VERSION_CONFLICT`, 확정된 첨삭 있음 409 `TRANSCRIPT_LOCKED`, 없는 구간 번호 422.
- 녹음 업로드 요청(`POST …/recordings`)에 `speaker_consent_status` 추가: `NOTICE_GIVEN`(기본, 녹음 사실을 알림) / `CONSENT_REPORTED`(강사가 동의했다고 기록). 응답의 `speaker_consent_verified`는 **항상 false** — 학생의 기록일 뿐 강사의 동의를 서비스가 확인한 것이 아닙니다. 화면에 "녹음 전 강사에게 알리고 동의를 받으세요" 안내를 띄우세요.
- **보관 기간**: 업로드 후 180일(`/meta/options`의 `data_policy.recording_audio_retention_days`)이 지나면 음성 파일만 삭제됩니다. 응답의 `audio_available=false`, `audio_deleted_at`. 재생 URL 409 `RECORDING_AUDIO_EXPIRED`, 전사 요청도 같은 오류. 전사·첨삭은 남습니다.

## 4. AI 요약·분류 결과 검토 (F-4)

기존 `/feedbacks/{id}` API를 그대로 씁니다. 응답 변경 (추가·완화만):

```json
{
  "id": "f1…",
  "recording_id": null,                 // 녹음 첨삭이면 id, 텍스트 첨삭이면 null
  "note_id": "n1…",                     // v0.9 텍스트 첨삭이면 id
  "source": "INSTRUCTOR",               // v0.9 INSTRUCTOR / SELF_NOTE / PEER
  "review_mode": "SELF",
  "summary": "…",
  "strengths":  [ { "id": "…", "kind": "STRENGTH", "content": "…", "category": "COMPOSITION",
                    "evidence": [ { "index": 0, "start_ms": null, "end_ms": null, "text": "구도는 안정적이다." } ],
                    "origin": "AI" } ],
  "weaknesses": [ … ], "fixes": [ … ], "next_tips": [ … ],
  "categories": ["VALUE", "TIME_MANAGEMENT"],
  "ai_draft": { … },                    // AI 원본 (변경 안 됨)
  "dropped_item_count": 1,              // 근거가 없거나 원문과 겹치지 않아 버린 AI 항목 수
  …
}
```

| 화면 항목 | 필드 |
| --- | --- |
| 핵심 요약 | `summary` |
| 잘한 점 | `strengths[]` |
| 개선할 점 / 세부 약점 | `weaknesses[]` (항목별 `category`), `categories` |
| 구체적 수정 방향 | `fixes[]`, `next_tips[]` |
| 원문 근거 | 각 항목의 `evidence[]` (`text` = 원문 문장, 녹음이면 `start_ms`로 재생 위치) |

- 카테고리 선택지에 **`TIME_MANAGEMENT`(시간 관리)** 추가 (`/meta/options`의 `weakness_categories`).
- 근거 `evidence`에 원문 문장 `text`가 추가되었습니다 (녹음·텍스트 공통). 텍스트 첨삭은 `start_ms`/`end_ms`가 null입니다.
- 수정·확정·반려·재검토·이력은 v0.6과 같습니다: `PATCH /feedbacks/{id}` (항목 전체 교체), `POST …/approve|reject|reopen`, `GET …/history`.
- 확정 권한: 개인 작품의 모든 첨삭 + 학원 작품의 자기 메모·다른 학생 의견 = 학생 본인. 학원 작품의 강사 첨삭 = 담당 강사 (학생은 승인된 것만 조회, 확정 전 403 `FEEDBACK_NOT_APPROVED`).
- AI는 사진을 평가하지 않고 입력된 원문만 정리합니다. 원문과 표현이 거의 겹치지 않는 항목은 서버가 버립니다.

## 5. 성장 아카이브 (F-5)

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/v1/growth/me/timeline` | (기존) 작품 날짜순·실기 유형 필터 + v0.9 필드 |
| GET | `/api/v1/growth/me/weaknesses/{category}/feedbacks` | 특정 약점의 과거 첨삭 (최근순, 페이지) |
| GET | `/api/v1/growth/me/compare?current_artwork_id=&previous_artwork_id=` | 이전·현재 작품 비교 |

- timeline 항목 추가 필드: `topic, work_method, actual_minutes, time_limit_minutes, recommendations[{id,title,weakness_category,status}]`, `feedbacks[].note_id/source` (`recording_id`는 텍스트 첨삭이면 null). 단계 사진은 기존 `stages[].representative_photo_id` → `GET /artworks/{id}/photos/{pid}/url`.
- 약점별 과거 첨삭: 기본은 강사 첨삭만, `include_unverified=true`면 자기 메모·다른 학생 의견 포함 (`evidence.source`로 구분).

```json
// GET /growth/me/weaknesses/VALUE/feedbacks?limit=20
{ "items": [ { "evidence": { "item_id": "…", "feedback_id": "…", "recording_id": null, "note_id": "n1…",
                            "source": "INSTRUCTOR", "artwork_id": "…", "artwork_title": "정물 소묘",
                            "work_date": "2026-10-08", "kind": "WEAKNESS", "category": "VALUE",
                            "content": "오른쪽 컵의 명암이 약하다.", "start_ms": null,
                            "source_text": ["오른쪽 컵의 명암이 너무 약해서 형태가 떠 보인다."] },
               "feedback_summary": "…", "approved_at": "…" } ],
  "total": 5, "limit": 20, "offset": 0 }

// GET /growth/me/compare?current_artwork_id=a2   (previous 생략 = 같은 실기 유형의 직전 작품)
{ "previous": { "artwork_id": "a1", "title": "…", "work_date": "…", "practical_type": "DRAWING", "topic": "…",
                "actual_minutes": 200, "time_limit_minutes": 240,
                "photos": [ { "stage": "FINAL", "photo_id": "…", "url": "https://…", "url_expires_at": "…" } ],
                "feedback_count": 1, "categories": ["VALUE"], "strengths": ["…"], "weaknesses": ["…"] },
  "current":  { … },
  "still_mentioned": ["VALUE"], "not_mentioned_now": [], "newly_mentioned": ["TIME_MANAGEMENT"],
  "notes": ["강사 첨삭에서 지적된 항목만 비교합니다 (AI가 사진을 평가하지 않습니다).", "…"] }
```

- 비교할 이전 작품이 없으면 409 `ARTWORK_NOT_COMPARABLE`. 두 이미지를 나란히 보여 주세요. `not_mentioned_now`를 "개선됨"으로 표시하지 마세요.

## 6. 성장 리포트 (F-7)

기존 `GET /growth/me/weaknesses`, `POST /growth/me/reports`, `GET /growth/me/reports/{id}`의 `statistics`에 추가 (리포트 `analysis_version = "growth-v2"`):

```json
"time_stats": { "recorded_artwork_count": 2, "unrecorded_artwork_count": 1, "total_minutes": 460,
                "average_minutes": 230.0,
                "mock_exam": { "artwork_count": 3, "timed_count": 2, "over_limit_count": 1, "average_time_ratio": 0.958 } },
"activity": [ { "bucket_start": "2026-10-01", "artwork_count": 3, "timed_artwork_count": 2,
                "study_minutes": 460, "mock_exam_count": 3 } ],          // 기간별 작품 수·학습 시간
"source_breakdown": { "INSTRUCTOR": 3, "SELF_NOTE": 1, "PEER": 0 },    // 출처별 확정 첨삭 수
"unverified_mentions": [ { "category": "PROPORTION", "label": "비례", "mention_count": 1,
                           "by_source": { "SELF_NOTE": 1 } } ],         // 참고용 (반복 약점에 미반영)
"guidance": [ "강사 첨삭을 기록하고 확정한 작품이 3개 이상이면 반복 약점을 분석합니다 (현재 2개)." ]
```

| 명세 항목 | 필드 |
| --- | --- |
| 기간별 작품 수·학습 시간 | `activity[]`, `time_stats` |
| 실기 유형별 기록 | `practical_type_distribution` (+ `practical_type` 필터) |
| 가장 자주 지적된 항목 / 반복 세부 문제 | `weaknesses[]`, `top_weaknesses` |
| 과거·최근 언급 변화 | `weaknesses[].recent/previous/trend`, `timeline` |
| 긍정적으로 언급된 항목 | `strengths[]` |
| 다음 연습 집중 항목 | `next_goals[]` |
| 실제 첨삭 근거 | 각 `evidence[]` (`source_text` 원문, `note_id`/`recording_id`) |

- **반복 약점·추세는 강사 첨삭(INSTRUCTOR)만** 집계합니다. 자기 메모·다른 학생 의견은 `unverified_mentions`로 따로 보여 주세요.
- 데이터 부족: `status=INSUFFICIENT_DATA` + `message` + `guidance`. `notes` 문구(완료 ≠ 향상, 언급 감소 ≠ 향상)를 화면에 함께 표시하세요.
- AI 설명문 실패해도 `statistics`는 그대로 제공됩니다 (`ai_narrative.status=FAILED`).
- 이전 버전 리포트(`growth-v1`)에는 새 필드가 기본값(빈 값)으로 옵니다 → `is_stale`이면 재생성 권장.

## 7. 맞춤 연습 과제 수행 (F-8)

| Method | Path | 설명 |
| --- | --- | --- |
| POST | `/api/v1/growth/me/recommendations/{id}/start` | 시작 기록 `{version}` (채택 후) |
| GET | `/api/v1/growth/me/recommendations/{id}/artworks` | 연결된 수행 작품 + 후속 첨삭 여부 |
| POST | `/api/v1/growth/me/recommendations/{id}/artworks` | 기존 작품 연결 `{artwork_id}` (201, 멱등) |
| DELETE | `/api/v1/growth/me/recommendations/{id}/artworks/{artwork_id}` | 연결 해제 |
| GET | `/api/v1/growth/me/recommendations/{id}/follow-up` | 후속 분석: 약점 재등장 여부 |
| PUT | `/api/v1/growth/me/recommendations/{id}/completion` | (기존) + `artwork_id` 선택 |
| POST | `/api/v1/artworks` | (기존) + `recommendation_id` → 새 작품을 수행 작품으로 연결 |

RecommendationRead 추가 필드: `learning_goal`(학습 목표), `started_at`, `linked_artwork_ids` (개인 과제). 기존: `title, weakness_category, method_steps, estimated_minutes, status, completed_at`.

```text
생성 POST /growth/me/recommendations {"scope":"PERSONAL"} → DRAFT
→ (수정 PATCH) → 채택 POST …/adopt {version} → ADOPTED
→ 시작 POST …/start {version} → started_at
→ 수행 작품: POST /artworks {title, recommendation_id} 또는 POST …/artworks {artwork_id}
→ 그 작품에 첨삭 입력·확정 (§3·§4)
→ 후속 분석 GET …/follow-up
→ 완료 PUT …/completion {version, completed:true, artwork_id?}
```

```json
// GET …/follow-up
{ "recommendation_id": "r1", "weakness_category": "PROPORTION",
  "completed": false,                         // 과제 완료 여부 (실력 향상과 별개)
  "status": "REAPPEARED",                     // NO_LINKED_ARTWORK | NO_FOLLOW_UP_FEEDBACK | REAPPEARED | NOT_MENTIONED
  "linked_artworks": [ { "artwork_id": "a5", "title": "비례 연습 1", "work_date": "…", "linked_at": "…",
                         "feedback_count": 1, "weakness_mentioned": true } ],   // 첨삭 없으면 null
  "reappeared_count": 1, "analyzed_count": 1,
  "evidence": [ { …Evidence… } ],             // 후속 첨삭에서 이 약점을 지적한 항목
  "notes": [ "과제를 완료했다는 것과 실력이 향상되었다는 것은 같은 뜻이 아닙니다.", "…" ] }
```

- `NOT_MENTIONED`를 "개선됨"으로 표시하지 마세요 ("후속 첨삭에서 언급되지 않음").
- 학원에서 배포된 과제는 기존처럼 v0.3 과제(`/academies/{id}/tasks`)와 `artworks.task_id`로 연결합니다.
- 오류: 채택 전 시작·연결 409 `RECOMMENDATION_INVALID_STATE`, 다른 사람 작품·과제 404, 과제당 20개 초과 409 `RECOMMENDATION_ARTWORK_INVALID`, `completed:false`와 함께 `artwork_id` 422.

## 8. 커뮤니티 피드백 (F-6)

| Method | Path | 변경 |
| --- | --- | --- |
| POST/PATCH | `/api/v1/community/posts` | `question` (작품 질문, 1000자) 추가 |
| POST | `/api/v1/community/posts/{id}/comments` | `comment_type`, `categories` 추가 |
| PATCH | `/api/v1/community/comments/{id}` | `body` 필수, `comment_type`·`categories` 선택 |
| POST | `/api/v1/community/comments/{id}/adopt` | 작품 피드백 채택 → 내 첨삭 기록 (게시물 작성자) |

```json
// POST /community/posts/{id}/comments
{ "body": "오른쪽 컵의 명암 대비가 약해 보여요.", "comment_type": "FEEDBACK", "categories": ["VALUE", "COMPOSITION"] }
// GENERAL(기본) 댓글에는 categories를 보낼 수 없음 (422)

// CommentRead (추가 필드)
{ …, "comment_type": "FEEDBACK", "categories": ["VALUE", "COMPOSITION"],
  "adopted": false }        // 게시물 작성자·댓글 작성자에게만 true/false, 나머지는 null

// POST /community/comments/{id}/adopt   {"request_summary": false}  → 201 FeedbackNoteRead (source: PEER)
```

- 채택 전에는 성장 분석에 반영되지 않습니다. 채택하면 내 작품의 텍스트 첨삭(출처 `PEER`)으로 저장되고, AI 요약·확정을 거쳐도 반복 약점 통계에는 들어가지 않습니다 (리포트의 `unverified_mentions` 참고용).
- 원문 사본을 저장하므로 댓글·게시물이 나중에 삭제돼도 내 기록은 남습니다.
- 오류: 게시물 작성자가 아님 403, 일반 댓글 409 `COMMENT_NOT_FEEDBACK`, 이미 채택 409 `COMMENT_ALREADY_ADOPTED`, 내 댓글 422.

## 9. 앱 내부 알림 (F-9)

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/v1/notifications?unread_only=false&limit=20&offset=0` | 목록 (최신순) + `unread_count` |
| POST | `/api/v1/notifications/{id}/read` | 읽음 |
| POST | `/api/v1/notifications/read-all` | 모두 읽음 → `{"updated": n}` |
| DELETE | `/api/v1/notifications/{id}` | 삭제(숨김) 204 |
| GET | `/api/v1/notifications/preferences` | 설정 |
| PATCH | `/api/v1/notifications/preferences` | 유형별 끄기·미완료 안내 일수 |

```json
// GET /notifications
{ "items": [ { "id": "…", "type": "TASK_REMINDER", "title": "아직 완료하지 않은 연습 과제가 있어요",
               "body": "기준선 비율 비교 스케치", "report_id": null, "recommendation_id": "r1…",
               "is_read": false, "read_at": null, "created_at": "…" } ],
  "total": 4, "limit": 20, "offset": 0, "unread_count": 3 }

// PATCH /notifications/preferences
{ "report_ready": true, "task_recommended": true, "task_reminder": true, "goal_check": false,
  "reminder_after_days": 3 }
```

| type | 언제 | 이동 |
| --- | --- | --- |
| `REPORT_READY` | 성장 리포트 생성 (본인·담당 강사) — 리포트당 1번 | `GET /growth/me/reports/{report_id}` |
| `TASK_RECOMMENDED` | 개인 추천 묶음 생성(규칙·AI) / 학원 과제 배포 | `GET /growth/me/recommendations/{recommendation_id}` |
| `TASK_REMINDER` | 채택 후 N일(기본 3) 미완료 — 과제당 주 1회, 최대 3회 | 〃 |
| `GOAL_CHECK` | 학습 목표 30일 이상 미수정·없음 (가입 7일 후) — 월 1회 | 프로필 학습 목표 화면 |

- 푸시·이메일은 없습니다. 배지는 `unread_count`, 주기적으로(예: 화면 진입 시) 목록을 다시 불러오세요. 목록 조회 때 미완료·목표 안내를 다시 계산합니다(중복 없음).
- 다른 사용자의 알림 id는 404. 삭제한 알림은 같은 이벤트로 다시 생기지 않습니다.

## 10. 선택지 (`GET /api/v1/meta/options`, 인증 불필요)

추가: `grades`, `feedback_sources`, `weakness_categories`에 `TIME_MANAGEMENT`, `data_policy`:

```json
"data_policy": { "recording_audio_retention_days": 180,
                 "model_training_data_collection": false,
                 "speaker_consent_verified_by_service": false }
```

## 11. 오류 코드 (v0.9 추가)

| 코드 | HTTP | 상황 |
| --- | --- | --- |
| `TARGET_UNIVERSITY_LIMIT` | 409 | 지망 대학 10개 초과 |
| `TIMER_INVALID_TRANSITION` | 409 | 현재 상태에서 불가능한 타이머 이벤트 |
| `TIMER_INVALID_TIME` | 422 | occurred_at 범위 오류 |
| `TIMER_TOO_LONG` | 422 | 누적 24시간 초과 |
| `FEEDBACK_NOTE_LOCKED` | 409 | 확정된 요약이 있는 원문 수정 |
| `FEEDBACK_NOTE_LIMIT` | 409 | 작품당 텍스트 첨삭 50개 초과 |
| `TRANSCRIPT_LOCKED` | 409 | 확정된 첨삭이 있는 전사 수정 |
| `RECORDING_AUDIO_EXPIRED` | 409 | 보관 기간이 지나 음성 삭제됨 |
| `COMMENT_NOT_FEEDBACK` | 409 | 일반 댓글 채택 |
| `COMMENT_ALREADY_ADOPTED` | 409 | 이미 채택한 댓글 |
| `ARTWORK_NOT_COMPARABLE` | 409 | 비교할 이전 작품 없음 |
| `RECOMMENDATION_ARTWORK_INVALID` | 409 | 과제당 연결 작품 수 초과 |

## 12. 화면 체크리스트 (프론트 구현 필요)

1. 온보딩/프로필: 학년·실기 유형·학습 목표, 지망 대학 목록(추가·순서 드래그·삭제)
2. 작품 등록: 주제·작업 방식·작업 목적(모의시험)·제한 시간, 단계별 사진(기존)
3. 타이머 화면: 시작/일시정지/재개/종료, 새로고침 복원, 남은 시간·초과 표시, 오프라인 이벤트 큐
4. 첨삭 입력: 텍스트(출처 선택) / 녹음(강사 고지·동의 안내, 기존) → AI 요약 진행 상태 → 결과 검토·수정·확정 (원문 근거 하이라이트)
5. 전사 수정 화면 (구간별 문장 편집)
6. 성장 아카이브: 날짜순 타임라인·실기 유형 필터, 작품 비교(두 이미지 나란히), 약점별 과거 첨삭
7. 성장 리포트: 학습 시간·모의시험 통계, 출처 구분(강사 / 참고), 데이터 부족 안내
8. 맞춤 과제: 채택·시작·완료, 수행 작품 연결·등록, 후속 분석 (완료와 향상 구분 문구)
9. 커뮤니티: 게시물 질문, 일반/작품 피드백 댓글(항목 선택), 피드백 채택 버튼
10. 알림: 배지(unread_count), 목록·읽음·삭제, 알림 설정
