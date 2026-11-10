# 프론트엔드 연동 가이드 (v0.5.1 기획 변경 반영)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.5.1
> 선행 문서: [frontend-integration.md](frontend-integration.md) (인증·`api()`·오류 형식), [v0.4](frontend-integration-v0.4.md) (작품·사진 업로드), [v0.5](frontend-integration-v0.5.md) (피드백 녹음)
> 변경 배경: [v0.5.1-planning-changes.md](v0.5.1-planning-changes.md) · API 문서: http://127.0.0.1:8000/docs (최종 기준은 OpenAPI)

v0.5.1은 새 AI 기능 없이 **기획 변경에 맞춰 API를 정리·보완**한 버전입니다. 기존 응답 필드는 그대로이고 **필드가 추가**만 되었습니다 (호환).

## 1. 제거된 API (호출 시 404)

| 기능 | 경로 |
| --- | --- |
| 출석 | `/academies/{id}/attendance/**` |
| 오늘 할 일 | `/personal-todos/**`, `/users/me/today` |
| 강사 대시보드 | `/academies/{id}/dashboard` |
| 질문 콜·대기열 | `/academies/{id}/help-requests/**`, `/academies/{id}/classes/{cid}/help-queue/**` |
| 시험 타이머 | `/academies/{id}/exam-templates/**`, `/academies/{id}/exam-sessions/**` |

반·일정·수업 주제·과제, 학원·멤버, 작품·사진, 녹음·동의 API는 그대로입니다.

## 2. 선택지 API · 프로필 실기 유형

### 2.1 선택지 목록 (인증 불필요)

```http
GET /api/v1/meta/options
```

```json
{
  "practical_types": [
    { "code": "BASIC_DESIGN", "label": "기초디자인" },
    { "code": "THINKING_SHIFT", "label": "사고의 전환" },
    { "code": "IDEA_EXPRESSION", "label": "발상과 표현" },
    { "code": "DRAWING", "label": "소묘" },
    { "code": "WATERCOLOR", "label": "수채화" },
    { "code": "OTHER", "label": "기타" }
  ],
  "work_categories": [
    { "code": "MOCK_EXAM", "label": "모의시험" },
    { "code": "PERSONAL_PRACTICE", "label": "개인 연습" },
    { "code": "CLASS_WORK", "label": "수업 작품" }
  ],
  "work_statuses": [
    { "code": "IN_PROGRESS", "label": "작업 중" },
    { "code": "COMPLETED", "label": "작품 완료" }
  ]
}
```

- API에는 항상 `code`를 보내고, 화면에는 `label`을 씁니다. 순서는 배열 순서.
- 유형이 추가되어도 프론트 수정 없이 반영되도록 **하드코딩 대신 이 API**를 쓰는 것을 권장합니다 (`Cache-Control: max-age=3600`). 오프라인 대비로 기본 목록을 두는 것은 괜찮습니다.
- 회원가입 화면(프로필 생성 전)에서도 호출할 수 있습니다. `api()`로 호출해도 되고 토큰 없이 `fetch`해도 됩니다.

### 2.2 프로필

```js
// 회원가입 직후 (선택 항목: 고르지 않았으면 생략하거나 null)
await api('/users/me', {
  method: 'POST',
  body: { display_name: '김학생', user_type: 'STUDENT', practical_type: 'BASIC_DESIGN' },
})

// 마이페이지에서 변경 / 선택 해제
await api('/users/me', { method: 'PATCH', body: { practical_type: 'DRAWING' } })
await api('/users/me', { method: 'PATCH', body: { practical_type: null } })
```

- `GET /users/me` 응답에 `practical_type`이 추가되었습니다. **기존 회원은 `null`** → "실기 유형을 선택해 주세요" 안내에 사용.
- 선택지 외 값(소문자, 한국어 라벨 등)은 422 `VALIDATION_ERROR`.
- `POST /users/me`는 멱등이라 프로필이 이미 있으면 값을 바꾸지 않습니다. 변경은 `PATCH`.
- `pendingProfile`(이메일 인증 대기 중 저장)에도 `practicalType`을 함께 저장해 두었다가 프로필 생성 때 보내면 됩니다.
- 강사도 설정할 수 있습니다 (주 지도 분야, 선택).

## 3. 작품 분류 · 아카이브 필터

### 3.1 저장

```js
await api('/artworks', {
  method: 'POST',
  body: {
    title: '정물 기초디자인 04',
    practical_type: 'BASIC_DESIGN',   // 선택 — 기본값으로 내 프로필 practical_type을 미리 채워 두면 편함
    work_category: 'MOCK_EXAM',       // 선택 — MOCK_EXAM | PERSONAL_PRACTICE | CLASS_WORK
  },
})
await api(`/artworks/${id}`, { method: 'PATCH', body: { work_category: 'PERSONAL_PRACTICE' } })
await api(`/artworks/${id}`, { method: 'PATCH', body: { practical_type: null } }) // 미분류로
```

- 두 값은 **독립**입니다: "기초디자인 + 모의시험" 작품이 가능합니다.
- 기존 작품은 둘 다 `null`(미분류).

### 3.2 목록 필터

```http
GET /api/v1/artworks?practical_type=BASIC_DESIGN
GET /api/v1/artworks?work_category=MOCK_EXAM
GET /api/v1/artworks?practical_type=BASIC_DESIGN&work_category=MOCK_EXAM     (AND)
GET /api/v1/artworks?practical_type=BASIC_DESIGN&practical_type=DRAWING      (같은 필드 여러 값 = OR)
GET /api/v1/artworks?work_status=COMPLETED
```

- 기존 `academy_id`, `work_date_from/to`, `limit/offset`와 함께 쓸 수 있고, 정렬(작업 날짜 최신순)·`total`은 필터 적용 후 기준입니다.
- 강사용 `GET /academies/{id}/artworks`도 같은 필터를 지원합니다.

**기존 필터 칩 디자인 유지 방법** — 칩 하나를 쿼리 하나에 매핑합니다:

```js
const ARCHIVE_FILTERS = [
  { label: '전체', query: {} },
  { label: '기초디자인', query: { practical_type: 'BASIC_DESIGN' } },
  { label: '모의시험', query: { work_category: 'MOCK_EXAM' } },
  { label: '개인 연습', query: { work_category: 'PERSONAL_PRACTICE' } },
]

export const listArtworks = ({ limit = 100, offset = 0, query = {} } = {}) => {
  const params = new URLSearchParams({ limit, offset, ...query })
  return api(`/artworks?${params}`)
}
```

나중에 "기초디자인 중 모의시험"처럼 두 줄 필터(유형 줄 × 목적 줄)로 바꾸려면 두 쿼리를 합치기만 하면 됩니다.

## 4. 작품 완료

### 4.1 상태 의미

| 필드 | 의미 |
| --- | --- |
| `progress` | 사진 단계 진행 (`NOT_STARTED`/`SKETCH`/`PROGRESS`/`FINAL`) — 기존과 같음 |
| `work_status` | **학생이 직접 정한 작업 상태** `IN_PROGRESS` / `COMPLETED` |
| `completed_at` | 완료 시각 (`COMPLETED`일 때만) |

FINAL 사진이 있다고 완료가 아닙니다. 현재 `stages.js`의 `isCompleted = progress === 'FINAL'`은 **`work_status === 'COMPLETED'`로 바꾸는 것을 권장**합니다 (아카이브 "완성 작품" 수, 카드 "완성/진행 중" 배지). 기존 작품은 모두 `IN_PROGRESS`입니다.

### 4.2 API

```http
POST /api/v1/artworks/{artwork_id}/complete    작품 완료하기  → ArtworkDetail
POST /api/v1/artworks/{artwork_id}/reopen      작업 재개      → ArtworkDetail
```

- 완료 조건: **FINAL 단계 사진이 1장 이상** 업로드 완료(ACTIVE) 상태. 없으면 409 `FINAL_PHOTO_REQUIRED` → "완성 사진을 먼저 올려 주세요".
- 두 API 모두 멱등입니다 (이미 완료/작업 중이면 200, 완료 시각 유지).
- 완료된 작품에서 **사진 업로드·교체·삭제·대표 변경**은 409 `ARTWORK_COMPLETED` → 사진 편집 UI를 숨기고 "작업 재개" 버튼 제공.
- 완료 후에도 가능: 제목·설명·분류 수정, **피드백 녹음 추가·삭제**, 작품 삭제, 사진 보기.
- 완료 시점에 올리던 사진(업로드 완료 처리 전)은 취소됩니다.
- 강사는 완료 상태를 조회만 합니다 (완료·재개 버튼 없음).

`GET /artworks/{id}/progress` 응답에도 `has_final_photo`, `work_status`가 추가되었습니다. "작품 완료하기" 버튼 활성화 조건 = `has_final_photo && work_status === 'IN_PROGRESS'`.

## 5. 녹음 수 (`recording_count`)

작품 목록·상세(학생·강사) 각 항목에 `recording_count`가 추가되었습니다.

```jsx
<Badge>피드백 {artwork.recording_count}</Badge>   // 0이면 숨김 처리 권장
```

- 재생 가능한(ACTIVE) 녹음만 셉니다. 삭제한 녹음, 업로드 완료 처리 전 녹음은 제외.
- 녹음을 추가·삭제한 뒤 목록 숫자를 갱신하려면 목록을 다시 불러오세요 (상세 화면의 녹음 목록은 기존 API).

## 6. 응답 예시 (작품 목록 항목)

```json
{
  "id": "a9d1…", "title": "정물 기초디자인 04", "description": null, "work_date": "2026-11-09",
  "academy_id": null, "student_membership_id": null, "class_id": null, "task_id": null,
  "practical_type": "BASIC_DESIGN",
  "work_category": "MOCK_EXAM",
  "work_status": "COMPLETED",
  "completed_at": "2026-11-09T09:12:44Z",
  "progress": "FINAL", "photo_count": 4,
  "recording_count": 3,
  "cover_photo_id": "p9…", "created_at": "…", "updated_at": "…",
  "stages": [ … ]
}
```

## 7. 새 오류 코드

| HTTP | code | 상황 | 프론트 처리 |
| --- | --- | --- | --- |
| 409 | `FINAL_PHOTO_REQUIRED` | FINAL 사진 없이 완료 | 완성 사진 업로드 유도 |
| 409 | `ARTWORK_COMPLETED` | 완료된 작품의 사진 변경 | 사진 편집 숨김, "작업 재개" 안내 |
| 422 | `VALIDATION_ERROR` | 선택지 외 `practical_type`·`work_category`·`work_status` | 선택지 새로고침 |

`errorMessages.js`에 위 두 코드를 추가하세요. 제거된 코드(`ALREADY_CHECKED_IN`, `EXAM_*`, `HELP_*` 등)는 더 이상 오지 않습니다.

## 8. 연동 문서 오류 수정

[v0.4 §3](frontend-integration-v0.4.md) 업로드 예시가 `body: JSON.stringify({...})`로 되어 있었습니다. `api()`가 `body`를 직접 `JSON.stringify` 하므로 문자열이 한 번 더 감싸져 서버에서 422가 납니다. **객체를 그대로 넘기도록** 문서를 고쳤습니다 (프론트 코드는 이미 수정됨). 다른 연동 문서(frontend-integration.md, v0.3, v0.5)에는 같은 오류가 없습니다.
