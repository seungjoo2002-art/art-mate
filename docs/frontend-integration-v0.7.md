# 프론트엔드 연동 가이드 (v0.7 AI 개인 맞춤형 성장 코치)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.7
> 선행 문서: [frontend-integration.md](frontend-integration.md) (인증·`api()`·오류 형식), [v0.6](frontend-integration-v0.6.md) (첨삭·AI 동의·작업 상태), [v0.3](frontend-integration-v0.3.md) (과제 API)
> 설계 배경: [growth-coach-v0.7.md](growth-coach-v0.7.md) · API 문서: http://127.0.0.1:8000/docs (최종 기준은 OpenAPI)

## 0. 한눈에

| 기능 | 계산 방식 | 외부 AI | 동의 |
| --- | --- | --- | --- |
| 통합 이력 (작품 + 승인 첨삭 + 과제) | DB 조회 | ✕ | — |
| 반복 약점 분석·기간별 추이 | **규칙 기반 통계** (즉시) | ✕ | — |
| 성장 리포트 – 통계 | 규칙 기반 (즉시 저장) | ✕ | — |
| 성장 리포트 – 설명문 | Gemini (비동기, 선택) | ○ | **GROWTH_COACHING** |
| 맞춤 연습 과제 – 규칙 | 템플릿 + 실제 첨삭 근거 (즉시) | ✕ | — |
| 맞춤 연습 과제 – AI | Gemini (비동기, 선택) | ○ | **GROWTH_COACHING** |

- 분석에는 **승인된(APPROVED) 첨삭만** 씁니다. 초안·반려된 첨삭, 삭제된 작품·녹음은 포함되지 않습니다.
- 통계와 AI 설명은 응답에서 분리되어 옵니다 (`statistics` vs `ai_narrative`). 화면에서도 구분해 표시하세요 (예: AI 설명에 "AI가 정리한 설명" 라벨).
- 모든 분석 응답의 `notes`를 함께 보여 주세요 (AI 채점이 아님, 언급되지 않은 것 ≠ 개선, 강사별 첨삭 방식 차이).

## 1. 범위(scope)와 권한

| scope | 대상 작품 | 누가 | 추천 과제 흐름 |
| --- | --- | --- | --- |
| `ALL` | 학생의 모든 작품 | 학생 | (추천 불가) |
| `PERSONAL` | 학원 미연결 개인 작품 | 학생 | 학생 본인이 채택·완료 |
| `ACADEMY` + `academy_id` | 그 학원에 연결된 작품 | 학생, 담당 강사 | 강사 검토·승인 → 기존 과제로 배포 |

- 학생 API: `/api/v1/growth/me/...` (기본 `scope=ALL`).
- 강사 API: `/api/v1/academies/{academy_id}/growth/...` — 항상 그 학원 연결 작품만, 담당 학생만 (비담당 403, 다른 학원 404). 학생의 개인 작품은 강사에게 보이지 않습니다.

## 2. 학생 화면 API

```http
GET  /api/v1/growth/me/summary?scope=ALL                       나의 성장 요약 (대시보드)
GET  /api/v1/growth/me/timeline?from&to&practical_type&work_category&limit&offset   최근 작품·첨삭
GET  /api/v1/growth/me/weaknesses?from&to&practical_type&work_category&recent_window=5&bucket=month
POST /api/v1/growth/me/reports                                 성장 리포트 생성
GET  /api/v1/growth/me/reports?scope=                          리포트 목록
GET  /api/v1/growth/me/reports/{report_id}
POST /api/v1/growth/me/reports/{report_id}/regenerate          { "include_ai_narrative": false }
POST /api/v1/growth/me/recommendations                         추천 과제 생성
GET  /api/v1/growth/me/recommendations?status=&scope=
GET  /api/v1/growth/me/recommendations/{id}
PATCH /api/v1/growth/me/recommendations/{id}                   (개인 추천) 수정
POST /api/v1/growth/me/recommendations/{id}/adopt              (개인 추천) 채택
POST /api/v1/growth/me/recommendations/{id}/reject             (개인 추천) 거절
PUT  /api/v1/growth/me/recommendations/{id}/completion         (개인 추천) 완료 기록 { version, completed }
GET  /api/v1/growth/me/recommendations/{id}/history            (개인 추천) 이력
GET  /api/v1/growth/me/jobs/{job_id}                           AI 생성 작업 상태
# 학원에서 배포된 과제 완료: 기존 v0.3 API
PUT  /api/v1/academies/{academy_id}/tasks/{task_id}/completion  { "completed": true }
```

### 2.1 나의 성장 요약 `GET /growth/me/summary`

```json
{
  "scope": { "scope": "ALL", "academy_id": null, "student_membership_id": null },
  "student": null,
  "totals": { "artwork_count": 12, "completed_artwork_count": 7, "approved_feedback_count": 10, "analyzed_artwork_count": 9 },
  "confidence": "HIGH",
  "status": "READY",
  "message": null,
  "top_weaknesses": [ { …WeaknessStat (아래 §2.2) … } ],
  "recent_feedbacks": [
    { "id": "f1…", "artwork_id": "a1…", "artwork_title": "정물 기초디자인 04",
      "summary": "구도는 좋고, 오른쪽 사과 명암을 보강해야 한다.",
      "categories": ["VALUE"], "approved_at": "2026-11-08T09:12:00Z" }
  ],
  "latest_report": { "id": "r1…", "period_type": "MONTH", "period_start": "2026-10-11", "period_end": "2026-11-09",
                     "status": "READY", "narrative_status": "READY", "created_at": "…" },
  "open_recommendation_count": 2,
  "notes": ["이 통계는 강사가 승인한 첨삭 기록을 집계한 것이며, AI가 실기 능력을 채점한 결과가 아닙니다.", "…"]
}
```

### 2.2 반복 약점 분석 `GET /growth/me/weaknesses`

```json
{
  "scope": { "scope": "ALL", "academy_id": null, "student_membership_id": null },
  "period_start": null, "period_end": null,
  "status": "READY",                     // INSUFFICIENT_DATA면 message 표시, 차트 대신 안내
  "message": null,
  "required_artwork_count": 3,
  "confidence": "MEDIUM",                // LOW(<3) · MEDIUM(<8) · HIGH(≥8) 분석 작품 수 기준
  "recent_window": 5,
  "totals": { "artwork_count": 4, "completed_artwork_count": 2, "approved_feedback_count": 4, "analyzed_artwork_count": 4 },
  "practical_type_distribution": [ { "practical_type": "DRAWING", "artwork_count": 4 } ],
  "work_category_distribution":  [ { "work_category": "MOCK_EXAM", "artwork_count": 4 } ],
  "top_weaknesses": ["PROPORTION", "VALUE"],
  "weaknesses": [
    {
      "category": "PROPORTION", "label": "비례",
      "mention_count": 4,                // 이 카테고리가 붙은 승인 첨삭 수
      "artwork_count": 4,                // 지적된 작품 수 (작품당 1번)
      "artwork_ratio": 1.0,              // 분석 작품 중 비율 (0~1) — 화면에 % 표시 가능 (통계값)
      "recent":   { "analyzed_artwork_count": 2, "artwork_count": 2, "ratio": 1.0 },
      "previous": { "analyzed_artwork_count": 2, "artwork_count": 2, "ratio": 1.0 },   // 비교 불가면 null
      "trend": "SIMILAR",                // MORE_FREQUENT · LESS_FREQUENT · SIMILAR · INSUFFICIENT_DATA
      "repeated": true,
      "last_seen_work_date": "2026-10-04",
      "evidence": [
        { "item_id": "i1…", "feedback_id": "f1…", "recording_id": "rec1…", "artwork_id": "a4…",
          "artwork_title": "작품 4", "work_date": "2026-10-04", "kind": "WEAKNESS", "category": "PROPORTION",
          "content": "오른쪽 병의 높이가 실제보다 낮다.", "start_ms": 15200 }
      ]
    }
  ],
  "strengths": [ { "category": "COMPOSITION", "label": "구도", "artwork_count": 3, "evidence": [ … ] } ],
  "timeline_bucket": "month",
  "timeline": [ { "bucket_start": "2026-10-01", "analyzed_artwork_count": 4, "categories": { "PROPORTION": 4, "VALUE": 2 } } ],
  "next_goals": [ { "category": "PROPORTION", "goal": "다음 작품에서 '비례'을(를) 스케치 단계부터 의식적으로 점검하기",
                    "based_on": { …Evidence (최근 수정 지시) … } } ],
  "notes": [ "…", "…", "…" ]
}
```

화면 가이드
- **반복 약점 TOP 3**: `top_weaknesses` 순서대로 `weaknesses`에서 찾아 칩 + "N개 작품에서 지적" 표시.
- **약점 변화 추이**: `timeline`을 막대/선 그래프로 (x=bucket_start, y=categories[c] / analyzed_artwork_count). `bucket=week`로 주간 보기.
- **trend 문구**: MORE_FREQUENT "최근 첨삭에서 더 자주 언급됨", LESS_FREQUENT "최근 첨삭에서 덜 언급됨"(❗ "개선됨"이라고 쓰지 마세요), SIMILAR "비슷함", INSUFFICIENT_DATA "비교할 기록이 부족해요".
- **근거 보기**: `evidence[].content` + "녹음 듣기"(작품 상세 → 녹음 `start_ms`부터 재생).
- `confidence: LOW`면 "기록이 적어 참고용이에요" 배지.

### 2.3 최근 작품·첨삭 `GET /growth/me/timeline`

```json
{ "items": [ {
    "artwork_id": "a1…", "title": "정물 기초디자인 04", "work_date": "2026-11-08", "created_at": "…",
    "academy_id": "ac…", "practical_type": "BASIC_DESIGN", "work_category": "MOCK_EXAM",
    "work_status": "COMPLETED", "completed_at": "…", "progress": "FINAL", "cover_photo_id": "p9…",
    "stages": [ { "stage": "SKETCH", "photo_count": 1, "representative_photo_id": "p1…" }, … ],
    "feedbacks": [ { "id": "f1…", "recording_id": "rec1…", "summary": "…", "categories": ["VALUE"],
                     "strengths": ["…"], "weaknesses": ["…"], "fixes": ["…"], "approved_at": "…" } ],
    "task": { "task_id": "t1…", "title": "명암 5단계", "completed": true }
  } ], "total": 12, "limit": 20, "offset": 0 }
```

사진 URL은 기존 작품 API(`GET /artworks/{id}?include_urls=true`, `…/photos/{id}/url`)를 사용합니다.

## 3. 성장 리포트

### 3.1 생성

```json
// POST /growth/me/reports
{ "period": "MONTH",                 // WEEK(최근 7일) · MONTH(최근 30일) · ALL · CUSTOM
  "from": null, "to": null,           // CUSTOM일 때만 (최대 2년)
  "scope": "ALL", "academy_id": null,
  "include_ai_narrative": true }      // AI 설명문 요청 (선택)
```

- **201**: 새 리포트. **200**: 같은 범위·기간·같은 데이터로 이미 만든 리포트(같은 `id`).
- 통계는 응답 시점에 완성되어 있습니다. AI 설명문은 `ai_narrative.status`로 확인하세요.

### 3.2 응답

```json
{
  "id": "r1…",
  "scope": { "scope": "ALL", "academy_id": null, "student_membership_id": null },
  "period_type": "MONTH", "period_start": "2026-10-11", "period_end": "2026-11-09",
  "status": "READY",                   // INSUFFICIENT_DATA → message: "분석에 필요한 기록이 부족합니다."
  "message": null,
  "statistics": { …§2.2 WeaknessAnalysis와 같은 형태 (데이터 기반)… },
  "ai_narrative": {
    "status": "READY",                 // NOT_REQUESTED · PENDING · READY · FAILED · SKIPPED · INVALIDATED
    "generated_by": "AI",
    "content": {
      "overview": "최근 첨삭에서 비례가 반복적으로 언급되었다.",
      "strengths_comment": "구도는 강사가 긍정적으로 언급했다.",
      "improvement_comment": "기준선을 먼저 잡으라는 지적이 이어졌다.",
      "next_goals": [ { "goal": "스케치 단계에서 기준선 먼저 긋기", "evidence": [ …Evidence… ] } ]
    },
    "error_code": null,
    "model_name": "gemini-3.1-flash-lite", "prompt_version": "growth-narrative-v1"
  },
  "is_stale": false,                   // true: 생성 후 첨삭·작품이 바뀜 → "최신 기록으로 다시 만들기" 버튼
  "analysis_version": "growth-v1",
  "source_feedback_count": 9,
  "generated_by_name": "김학생",
  "created_at": "…"
}
```

리포트 항목 ↔ 필드: 분석 기간(`period_*`), 총 작품 수(`statistics.totals.artwork_count`), 완료 작품 수(`completed_artwork_count`), 승인 첨삭 수(`approved_feedback_count`), 실기 유형별 분포(`practical_type_distribution`), 자주 지적된 약점(`weaknesses`/`top_weaknesses`), 최근 빈도 변화(`weaknesses[].trend`, `timeline`), 강사가 긍정적으로 평가한 부분(`strengths`), 개선이 필요한 부분(`weaknesses[].evidence`), 다음 학습 목표(`next_goals`, AI 설명문의 `next_goals`).

### 3.3 AI 설명문 상태 처리

| `ai_narrative.status` | 화면 | 처리 |
| --- | --- | --- |
| `NOT_REQUESTED` | 통계만 | "AI 설명 받기" 버튼 → `regenerate { include_ai_narrative: true }` |
| `PENDING` | "AI가 설명을 정리하는 중…" | 5초 간격으로 리포트 다시 조회 |
| `READY` | 설명 카드 ("AI가 정리한 설명" 라벨) | — |
| `FAILED` | "AI 설명을 만들지 못했어요" + 다시 시도 | `regenerate { include_ai_narrative: true }` |
| `SKIPPED` + `error_code` | 사유 안내 | `AI_CONSENT_REQUIRED` → 동의 화면, `INSUFFICIENT_DATA` → 기록 부족, `GROWTH_AI_NOT_CONFIGURED` → 숨김, `AI_CONSENT_REVOKED` → 동의 철회됨 |
| `INVALIDATED` | "근거 첨삭이 삭제되어 설명을 지웠어요" | 다시 만들기 |

AI 설명문은 숫자·백분율·합격 예측을 쓰지 않도록 서버에서 검증합니다 (위반 시 재시도 후 FAILED).

## 4. 맞춤 연습 과제 추천

### 4.1 생성

```json
// POST /growth/me/recommendations
{ "scope": "PERSONAL", "academy_id": null, "use_ai": false }
```

| 응답 | 의미 |
| --- | --- |
| 201 `status: CREATED` | 규칙 기반 추천 생성 (반복 약점 카테고리마다 1개, 최대 3개) |
| 200 `status: EXISTING` | 같은 데이터로 이미 만든 추천 (중복 생성 방지) |
| 202 `status: QUEUED` + `job` | AI 생성 시작 → `GET /growth/me/jobs/{job.id}` 폴링 → SUCCEEDED 후 목록 조회 |
| 409 `INSUFFICIENT_DATA` | `details.reason`: `NOT_ENOUGH_ARTWORKS`(승인 첨삭 작품 부족) / `NO_REPEATED_WEAKNESS`(2개 이상 작품에서 반복된 약점 없음) |
| 409 `AI_CONSENT_REQUIRED` | `use_ai=true`인데 GROWTH_COACHING 동의 없음 (`details.purpose`, `required_version`) |
| 503 `GROWTH_AI_NOT_CONFIGURED` | 서버에서 AI 기능 꺼짐 → 규칙 기반만 사용 |

- 새 데이터로 다시 만들면, 같은 범위의 **검토 전(DRAFT/IN_REVIEW)** 추천은 `SUPERSEDED`로 대체되어 목록에서 빠집니다.
- `scope=ACADEMY`로 학생이 생성하면 담당 강사의 검토 대기로 들어가고, 배포 전까지 학생에게 보이지 않습니다.

### 4.2 추천 JSON

```json
{
  "id": "pr1…",
  "scope": { "scope": "PERSONAL", "academy_id": null, "student_membership_id": null },
  "review_mode": "SELF",               // SELF(본인 채택) · INSTRUCTOR(강사 승인)
  "source": "RULE",                    // RULE · AI
  "status": "DRAFT",
  "version": 1,
  "weakness_category": "PROPORTION",
  "practical_type": "DRAWING",
  "title": "기준선 비율 비교 스케치",
  "description": "정물 2개를 배치하고 기준 길이를 정해 상대적 크기 비율을 관찰하며 스케치한다.",
  "method_steps": ["정물 2개를 배치한다", "가장 큰 대상의 높이를 기준 길이 1로 정한다", "…"],
  "estimated_minutes": 40,
  "difficulty": "EASY",                // EASY 쉬움 · NORMAL 보통 · HARD 어려움
  "reason": "승인된 첨삭이 있는 작품 4개 중 4개에서 '비례'이(가) 지적되었습니다.",
  "evidence": [ …Evidence (근거 첨삭, 삭제되면 빠짐)… ],
  "analysis": { "analysis_version": "growth-v1", "period": "ALL", "analyzed_artwork_count": 4,
                "artwork_count": 4, "recent": { … }, "trend": "SIMILAR",
                "practical_types": ["DRAWING"], "work_categories": ["MOCK_EXAM"], "recent_artwork_ids": ["…"] },
  "task": null,                        // 학원 배포 후: { task_id, title, due_at, completed, completed_at }
  "completed_at": null,                // 개인 추천 완료 시각
  "approved_at": null, "approved_by_name": null, "rejected_reason": null,
  "created_at": "…", "updated_at": "…",
  // ↓ 검토자 화면(강사, 개인 추천의 학생)만
  "origin": { "source": "RULE", "template_version": "practice-template-v1", "title": "…", … },
  "model_name": null, "prompt_version": "practice-template-v1",
  "student": null                      // 강사 화면: 학생 정보
}
```

### 4.3 상태 전이

```text
개인(SELF):     DRAFT ─수정→ IN_REVIEW ─채택→ ADOPTED ─완료→ COMPLETED (완료 해제 → ADOPTED)
                  └──────────── 거절 → REJECTED
학원(INSTRUCTOR): DRAFT ─수정→ IN_REVIEW ─승인→ APPROVED ─배포→ DISTRIBUTED (= v0.3 과제 생성)
                  └──────────── 반려(APPROVED 포함) → REJECTED
공통: 새 데이터로 다시 생성 → 검토 전 추천은 SUPERSEDED
```

- 모든 변경 요청에 조회한 `version`을 보냅니다. 다르면 409 `RECOMMENDATION_VERSION_CONFLICT`(`details.current_version`).
- 허용되지 않는 상태면 409 `RECOMMENDATION_INVALID_STATE`(`details.status`).

```json
// PATCH (수정: 보낸 필드만 변경, null 불가 — practical_type만 null 허용)
{ "version": 1, "title": "비율 관찰 스케치", "method_steps": ["기준선 긋기", "비율 비교", "형태 구성"],
  "estimated_minutes": 30, "difficulty": "NORMAL", "note": "시간 줄임" }

// POST …/adopt, …/approve           { "version": 2, "note": null }
// POST …/reject                     { "version": 2, "reason": "이번 주는 다른 과제가 있음" }
// PUT  …/completion (개인)          { "version": 3, "completed": true }
```

## 5. 강사 화면 API

```http
GET   /api/v1/academies/{academy_id}/growth/students                              담당 학생 성장 현황
GET   /api/v1/academies/{academy_id}/growth/students/{membership_id}/summary
GET   /api/v1/academies/{academy_id}/growth/students/{membership_id}/timeline      학생별 학습 이력
GET   /api/v1/academies/{academy_id}/growth/students/{membership_id}/weaknesses    주요 약점
POST  /api/v1/academies/{academy_id}/growth/students/{membership_id}/reports       { "period": "MONTH" }
GET   /api/v1/academies/{academy_id}/growth/students/{membership_id}/reports
GET   /api/v1/academies/{academy_id}/growth/reports/{report_id}
POST  /api/v1/academies/{academy_id}/growth/reports/{report_id}/regenerate
POST  /api/v1/academies/{academy_id}/growth/students/{membership_id}/recommendations   { "use_ai": false }
GET   /api/v1/academies/{academy_id}/growth/recommendations?status=DRAFT&status=IN_REVIEW&student_membership_id=   검토 대기
GET   /api/v1/academies/{academy_id}/growth/recommendations/{id}
PATCH /api/v1/academies/{academy_id}/growth/recommendations/{id}
POST  /api/v1/academies/{academy_id}/growth/recommendations/{id}/approve      { "version": 2 }
POST  /api/v1/academies/{academy_id}/growth/recommendations/{id}/reject       { "version": 2, "reason": "…" }
POST  /api/v1/academies/{academy_id}/growth/recommendations/{id}/distribute   { "version": 3, "class_id": null, "due_at": "2026-11-16T23:59:00+09:00" }
GET   /api/v1/academies/{academy_id}/growth/recommendations/{id}/history
GET   /api/v1/academies/{academy_id}/growth/jobs/{job_id}
```

```json
// GET /academies/{id}/growth/students
{ "items": [ { "student": { "membership_id": "m1…", "user_id": "u1…", "display_name": "김학생", "avatar_path": null },
               "analyzed_artwork_count": 9, "top_weaknesses": ["PROPORTION", "VALUE"],
               "last_feedback_at": "2026-11-08T09:12:00Z", "pending_recommendation_count": 2 } ],
  "total": 14, "limit": 20, "offset": 0 }
```

### 배포 (기존 과제 시스템 재사용)

- `distribute`는 v0.3 과제(`tasks`)를 **그 학생 1명 대상**(`target_type: STUDENTS`)으로 만듭니다. 별도 과제 시스템이 없습니다.
- 과제 설명에는 추천 설명 + 연습 방법 + 예상 시간·난이도가 들어갑니다. 과제 목록·취소·완료 현황은 기존 `/academies/{id}/tasks` API 그대로입니다.
- `class_id`를 생략하면 학생이 (강사가 관리하는) 반 1개에만 있을 때 자동 선택, 아니면 422 `CLASS_REQUIRED` + `details.class_ids` → 반 선택 UI.
- 학생은 기존 "받은 과제"(`GET /academies/{id}/tasks/me`)와 성장 화면(`GET /growth/me/recommendations`, `status: DISTRIBUTED`, `task.completed`) 양쪽에서 보고, 완료는 `PUT /academies/{id}/tasks/{task_id}/completion`.

## 6. AI 생성 중 상태 (작업)

`GET /growth/me/jobs/{job_id}` (강사: `/academies/{id}/growth/jobs/{job_id}`)는 v0.6 `JobRead`와 같습니다.

| `status` | 화면 |
| --- | --- |
| `QUEUED` / `RUNNING` | "AI가 연습 과제를 만드는 중…" (5초 폴링). `attempts>0`이면 "다시 시도하는 중" |
| `SUCCEEDED` | 추천 목록 다시 조회 |
| `FAILED` | `error_code` 안내 + "규칙 기반 추천 받기"(`use_ai: false`) 대안 제시 |
| `CANCELLED` | `AI_CONSENT_REVOKED` → 동의 화면 |

주요 `error_code`: `LLM_INVALID_OUTPUT`(검증 실패), `LLM_RATE_LIMITED`·`LLM_UNAVAILABLE`·`LLM_TIMEOUT`(일시 오류), `INSUFFICIENT_DATA`, `AI_NOT_CONFIGURED`, `AI_CONSENT_REVOKED`.

## 7. 동의 (GROWTH_COACHING)

v0.6 동의 API에 **목적(purpose)** 이 추가되었습니다. 기존 호출(목적 생략)은 첨삭 요약(`FEEDBACK_SUMMARY`) 그대로입니다.

```http
GET    /api/v1/ai-processing-consents/me?purpose=GROWTH_COACHING
POST   /api/v1/ai-processing-consents   { "purpose": "GROWTH_COACHING", "policy_version": "2026-11-growth-v1", "agreed": true, "granted_by": "SELF" }
DELETE /api/v1/ai-processing-consents/me?purpose=GROWTH_COACHING
```

동의 화면에 보여 줄 내용 (법적 검토 전 초안):
- 목적: 승인된 첨삭 기록을 바탕으로 성장 리포트 설명과 맞춤 연습 과제 초안을 만들기
- 전송 항목: 약점 카테고리별 통계(작품 수 등)와 **승인된 첨삭 문장** (작품 제목·이름·학원·계정 정보 미전송)
- 제공받는 자: Google LLC (Gemini API, 국외 이전) — 유료 등급(모델 학습 미사용)
- 거부해도 통계·규칙 기반 추천은 그대로 사용 가능
- 철회 시 진행 중인 AI 생성 취소, 이미 만든 결과는 유지(근거 첨삭 삭제 시 설명문 삭제)
- 만 14세 미만: 법정대리인 동의 (`granted_by: GUARDIAN`)

> 첨삭 요약 동의(FEEDBACK_SUMMARY)와 별개입니다. 한쪽만 동의할 수 있습니다.

## 8. 오류 코드

| HTTP | code | 상황 | 처리 |
| --- | --- | --- | --- |
| 409 | `INSUFFICIENT_DATA` | 추천에 필요한 기록 부족 (`details.reason`) | "기록이 더 쌓이면 추천해 드릴게요" |
| 409 | `AI_CONSENT_REQUIRED` | GROWTH_COACHING 동의 없음 (`details.purpose`) | 동의 화면 |
| 409 | `RECOMMENDATION_INVALID_STATE` | 상태상 불가 (`details.status`) | 새로고침 |
| 409 | `RECOMMENDATION_VERSION_CONFLICT` | 동시 수정 | 다시 불러오기 |
| 422 | `CLASS_REQUIRED` | 배포할 반 선택 필요 (`details.class_ids`) | 반 선택 |
| 422 | `VALIDATION_ERROR` | 잘못된 기간(from>to, CUSTOM 2년 초과), scope·academy_id 조합 | 입력 수정 |
| 503 | `GROWTH_AI_NOT_CONFIGURED` | AI 기능 꺼짐 | AI 버튼 숨김 |
| 403 | `FORBIDDEN` | 비담당 학생, 학생이 학원 추천 수정·승인 | 숨김 |
| 404 | `NOT_FOUND` | 다른 학원·다른 학생·배포 전 학원 추천(학생) | "찾을 수 없음" |

## 9. 데이터 부족 상태

- 분석 대상(승인 첨삭이 있는) 작품이 `required_artwork_count`(기본 3) 미만이면 `status: "INSUFFICIENT_DATA"`, `message: "분석에 필요한 기록이 부족합니다."`.
- 이때도 `totals`는 내려 옵니다 → "현재 3개 중 1개 작품에 확정된 첨삭이 있어요" 같은 진행 표시 가능.
- 리포트도 INSUFFICIENT_DATA로 저장되며 AI 설명문은 만들지 않습니다(`SKIPPED`, `INSUFFICIENT_DATA`).
- 추천 과제는 409 `INSUFFICIENT_DATA`.

`api()`는 `body` 객체를 그대로 넘깁니다 (직접 `JSON.stringify` 하지 않음).
