# 프론트엔드 연동 가이드 (v0.3 학원 운영)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.3 · 선행 문서: [frontend-integration.md](frontend-integration.md) (v0.2 인증·학원 소속)
> API 문서(개발 서버): http://127.0.0.1:8000/docs. 요청·응답 스키마의 최종 기준은 OpenAPI입니다.

v0.3에서는 반·일정, 출석, 수업 주제·과제, 개인 할 일, 강사 대시보드를 제공합니다.
인증 방식, 오류 형식, 페이지네이션은 v0.2와 같습니다 (`Authorization: Bearer <access_token>`, `{items, total, limit, offset}`).

## 1. 먼저 알아둘 것

### 1.1 ID 세 가지

| 이름 | 어디서 얻나 | 쓰는 곳 |
| --- | --- | --- |
| `user_id` | `GET /users/me` 의 `id` (= Supabase user id) | 표시용. v0.3 API 입력으로는 쓰지 않음 |
| **`membership_id`** | `GET /academies/{id}/members` 의 `id`, 학원 상세의 `my_membership.id` | **학원 안의 학생·강사를 가리킬 때** (반 배정, 출석, 과제 대상, 일정 필터) |
| `class_member_id` | `GET /classes/{id}/members` 의 `id` | 반 배정 해제 (`DELETE .../members/{class_member_id}`) |

학생 1명이 두 학원에 다니면 학원마다 `membership_id`가 다릅니다. 학원 데이터의 "학생"은 항상 `membership_id`입니다.

### 1.2 날짜·시간 규칙 (중요)

| 값 | 형식 | 예 | 기준 |
| --- | --- | --- | --- |
| 시각 (`*_at`) | ISO 8601 + 오프셋 | `2026-11-10T07:00:00Z`, `2026-11-10T16:00:00+09:00` | 절대 시각. 표시할 때 `Asia/Seoul`로 변환 |
| 날짜 (`*_date`, `date`, `from`, `to`) | `YYYY-MM-DD` | `2026-11-10` | **학원 현지(Asia/Seoul) 달력 날짜** |
| 정규 수업 시간 (`start_time`, `end_time`) | `HH:MM` 또는 `HH:MM:SS` | `16:00` | 학원 현지 벽시계 시간 (시간대 붙이지 말 것) |
| 요일 (`weekday`) | 정수 | `0`=월 … `6`=일 | JS `Date.getDay()`(0=일)와 다름! |

- "오늘"은 서버가 Asia/Seoul 기준으로 계산합니다. 출석 버튼을 누른 시각이 UTC로 전날이어도 서울 날짜로 저장됩니다.
- 응답 시각은 UTC(`Z`) 또는 `+09:00`로 올 수 있습니다. 문자열을 자르지 말고 `Date`/`dayjs`로 파싱하세요.
- 과제 마감 `due_at`을 보낼 때는 **반드시 오프셋을 포함**합니다 (`2026-11-12T23:59:00+09:00`). 오프셋 없는 값은 422.
- 일정 조회의 `starts_at`/`ends_at`은 `+09:00`로 옵니다. 바로 표시해도 됩니다.

```js
// 요일 변환: API weekday(0=월) ↔ JS getDay()(0=일)
const apiWeekday = (jsDay) => (jsDay + 6) % 7
const jsDay = (apiWeekday) => (apiWeekday + 1) % 7

// 서울 기준 오늘 날짜 (YYYY-MM-DD)
const seoulToday = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' }).format(new Date())

// 마감 입력값(datetime-local, 서울 기준) → API 값
const toDueAt = (localValue /* '2026-11-12T23:59' */) => `${localValue}:00+09:00`
```

### 1.3 부분 수정(PATCH) 규칙

- 보내지 않은 필드는 **그대로 유지**, `null`은 **값 지우기**입니다 (예: `{"due_at": null}` → 마감 없음).
- 제목·상태처럼 지울 수 없는 필드에 `null`을 보내면 422입니다.
- 정의되지 않은 필드를 보내면 422입니다 (오타 방지).

## 2. 권한 요약

`role`은 학원 역할(`my_role`, `my_membership.role`)입니다. **관리자 = OWNER/MANAGER**, **강사 = INSTRUCTOR 이상**.

| 기능 | 학생 | 강사 (담당 반) | 강사 (비담당) | 관리자 |
| --- | --- | --- | --- | --- |
| 반 생성·수정·보관 | ❌ | ❌ | ❌ | ✅ |
| 반 목록·상세 | 배정된 반만 | 전체 | 전체 | 전체 |
| 반 멤버 목록 | ❌ (403) | ✅ | ✅ | ✅ |
| 학생 배정·해제 | ❌ | ✅ | ❌ | ✅ |
| 담당 강사 지정·해제 | ❌ | ❌ | ❌ | ✅ |
| 정규 수업·휴강·변경·보강 등록 | ❌ | ✅ | ❌ | ✅ |
| 일정 조회 | 내 반 + 내 개인 보강 | 전체 / 담당 반 | 전체 | 전체 |
| 출석하기·내 출석 | ✅ | — | — | — |
| 출석 현황·기록·수정·이력 | ❌ | 담당 학생 | ❌ (빈 목록 / 403) | 모든 학생 |
| 수업 주제 조회 | 내 반 | ✅ | ✅ | ✅ |
| 수업 주제 등록·수정·삭제 | ❌ | ✅ | ❌ | ✅ |
| 과제 배포·수정·취소·완료 현황 | ❌ | ✅ | ❌ | ✅ |
| 받은 과제·완료 체크 | ✅ (본인) | — | — | — |
| 개인 할 일 | ✅ (본인만) | ❌ | ❌ | ❌ |
| 오늘 할 일 통합 | ✅ | ❌ | ❌ | ❌ |
| 대시보드 | ❌ | 담당 반 | 빈 화면 | 전체 (`scope=mine` 가능) |

- **담당 반**: 관리자가 그 반의 담당 강사로 지정한 반. **담당 학생**: 담당 반에 배정된 학생.
- 개인 할 일은 학생 본인 외 누구에게도(담당 강사·원장·시스템 관리자 포함) 노출되지 않습니다.
- 응답 규칙: 다른 학원이거나 학생에게 보이지 않는 리소스 → **404**, 같은 학원이지만 권한 부족 → **403**.

## 3. 화면별 필요한 API

| 화면 | 사용자 | API |
| --- | --- | --- |
| 학생 홈 (오늘 할 일) | 학생 | `GET /users/me/today`, `POST /academies/{id}/attendance/check-in`, `GET /academies/{id}/attendance/me/today` |
| 내 시간표 | 학생 | `GET /academies/{id}/schedules?from&to` |
| 받은 과제 | 학생 | `GET /academies/{id}/tasks/me`, `PUT /academies/{id}/tasks/{task_id}/completion` |
| 다음 수업 주제 | 학생 | `GET /academies/{id}/classes/{class_id}/lesson-topics` (`GET /academies/{id}/classes`로 반 목록) |
| 개인 할 일 | 학생 | `GET/POST /personal-todos`, `PATCH/DELETE /personal-todos/{id}` |
| 내 출석 기록 | 학생 | `GET /academies/{id}/attendance/me?from&to` |
| 강사 대시보드 | 강사 | `GET /academies/{id}/dashboard` |
| 반 관리 | 관리자·담당 강사 | `GET/POST /academies/{id}/classes`, `PATCH .../classes/{class_id}`, `GET/POST/DELETE .../classes/{class_id}/members` (+ v0.2 `GET /academies/{id}/members`로 후보 학생) |
| 시간표 관리 | 관리자·담당 강사 | `.../classes/{class_id}/schedules`, `.../classes/{class_id}/schedule-exceptions`, `GET /academies/{id}/schedules?mine=true` |
| 출석부 | 강사 | `GET /academies/{id}/attendance?date&class_id`, `POST /attendance/records`, `PATCH /attendance/records/{id}`, `GET .../history` |
| 수업 주제·과제 | 강사 | `.../classes/{class_id}/lesson-topics`, `GET/POST /academies/{id}/tasks`, `GET/PATCH/DELETE /tasks/{task_id}` |

경로 앞에는 모두 `/api/v1`이 붙습니다.

## 4. 반(Class) API

```http
POST  /academies/{academy_id}/classes                      관리자
GET   /academies/{academy_id}/classes?status=ACTIVE&mine=false
GET   /academies/{academy_id}/classes/{class_id}
PATCH /academies/{academy_id}/classes/{class_id}           관리자  {name?, description?, subject?, status?}
GET   /academies/{academy_id}/classes/{class_id}/members?role=STUDENT&status=ACTIVE   강사 이상
POST  /academies/{academy_id}/classes/{class_id}/members   {membership_id}
DELETE /academies/{academy_id}/classes/{class_id}/members/{class_member_id}
```

```json
// POST /classes  요청
{ "name": "예고 입시 A반", "subject": "소묘", "description": "화·목 16시" }

// 응답 201 (목록·상세도 같은 형태)
{
  "id": "6f0c…", "academy_id": "1b2e…", "name": "예고 입시 A반",
  "description": "화·목 16시", "subject": "소묘", "status": "ACTIVE",
  "student_count": 12,
  "instructors": [{ "membership_id": "a41d…", "display_name": "김강사" }],
  "my_role": "INSTRUCTOR",          // 요청자의 반 역할 (INSTRUCTOR | STUDENT | null)
  "created_at": "2026-11-04T05:00:00Z"
}

// POST /classes/{id}/members  요청 → 응답 201
{ "membership_id": "c9e1…" }
{
  "id": "0d7a…",                     // class_member_id (해제할 때 사용)
  "class_id": "6f0c…", "membership_id": "c9e1…", "user_id": "5a3f…",
  "display_name": "이학생", "avatar_path": null,
  "role": "STUDENT",                 // 학원 역할이 STUDENT면 STUDENT, 강사 이상이면 INSTRUCTOR(담당 강사)
  "status": "ACTIVE", "joined_at": "2026-11-04T05:01:00Z", "ended_at": null
}
```

- `status: "ARCHIVED"`로 반을 종료하면 목록 기본값(ACTIVE)에서 빠지고, 새 배정·일정·과제는 409 `CLASS_ARCHIVED`.
- 학생이 학원을 탈퇴하거나 제외되면 반 배정도 자동 해제됩니다.

## 5. 일정 API

### 5.1 정규 수업 (매주 반복)

```http
POST   /academies/{academy_id}/classes/{class_id}/schedules
GET    /academies/{academy_id}/classes/{class_id}/schedules?include_inactive=false
PATCH  /academies/{academy_id}/classes/{class_id}/schedules/{schedule_id}
DELETE /academies/{academy_id}/classes/{class_id}/schedules/{schedule_id}   (비활성화)
```

```json
// 요청: 매주 화요일 16:00~18:00, 11/9부터 (effective_from 생략 시 오늘)
{ "weekday": 1, "start_time": "16:00", "end_time": "18:00",
  "effective_from": "2026-11-09", "effective_until": null, "location": "2층 실기실" }

// 응답 201
{ "id": "e2b4…", "class_id": "6f0c…", "weekday": 1,
  "start_time": "16:00:00", "end_time": "18:00:00",
  "effective_from": "2026-11-09", "effective_until": null, "location": "2층 실기실",
  "is_active": true, "created_at": "…", "updated_at": "…" }
```

- 같은 반에서 요일·시간·기간이 겹치면 409 `SCHEDULE_OVERLAP` (끝 시각 = 다음 시작 시각은 허용).
- `PATCH`는 과거 회차를 포함한 모든 회차에 적용됩니다. "다음 달부터 시간 변경"은 기존 일정에 `effective_until`을 넣고 새 일정을 등록하세요.

### 5.2 휴강 · 1회 변경 · 보강

```http
POST   /academies/{academy_id}/classes/{class_id}/schedule-exceptions
GET    /academies/{academy_id}/classes/{class_id}/schedule-exceptions?from&to     강사 이상
PATCH  /academies/{academy_id}/classes/{class_id}/schedule-exceptions/{exception_id}
DELETE /academies/{academy_id}/classes/{class_id}/schedule-exceptions/{exception_id}
```

```json
// 휴강 (11/10 화요일 회차)
{ "kind": "CANCELLATION", "schedule_id": "e2b4…", "original_date": "2026-11-10", "reason": "학원 휴무" }

// 1회 변경 (11/17 회차 → 11/19 10:00~12:00)
{ "kind": "RESCHEDULE", "schedule_id": "e2b4…", "original_date": "2026-11-17",
  "session_date": "2026-11-19", "start_time": "10:00", "end_time": "12:00" }

// 보강 (반 전체). student_membership_id를 넣으면 그 학생 개인 보강
{ "kind": "MAKEUP", "session_date": "2026-11-14", "start_time": "13:00", "end_time": "15:00",
  "reason": "휴강 보강", "student_membership_id": null }
```

- `original_date`가 그 정규 수업의 실제 회차가 아니면 422 `INVALID_OCCURRENCE`. 같은 회차에 휴강·변경이 이미 있으면 409 `SCHEDULE_EXCEPTION_EXISTS`.
- `DELETE`: 휴강·변경은 원래 일정으로 **복구**, 보강은 **취소**(일정 조회에 `CANCELLED`로 표시).

### 5.3 일정 조회 (학생 시간표 / 강사 시간표)

```http
GET /academies/{academy_id}/schedules?from=2026-11-09&to=2026-11-15
      &class_id=…                    (선택) 한 반만
      &mine=true                     (강사) 담당 반만
      &instructor_membership_id=…    (강사 이상) 그 강사의 담당 반
      &student_membership_id=…       (강사 이상) 그 학생의 일정 — 담당 학생만
```

- 기본: 오늘부터 7일. 최대 62일 (초과 시 422 `INVALID_DATE_RANGE`). 시작 시각 순 정렬, `limit/offset` 지원.
- 학생은 필터 없이 호출하면 자기 시간표입니다.

```json
{
  "items": [
    { "class_id": "6f0c…", "class_name": "예고 입시 A반",
      "kind": "REGULAR", "status": "CANCELLED", "date": "2026-11-10",
      "starts_at": "2026-11-10T16:00:00+09:00", "ends_at": "2026-11-10T18:00:00+09:00",
      "original_date": null, "schedule_id": "e2b4…", "exception_id": "77aa…",
      "location": "2층 실기실", "reason": "학원 휴무", "student_membership_id": null },
    { "class_id": "6f0c…", "class_name": "예고 입시 A반",
      "kind": "MAKEUP", "status": "SCHEDULED", "date": "2026-11-14",
      "starts_at": "2026-11-14T13:00:00+09:00", "ends_at": "2026-11-14T15:00:00+09:00",
      "original_date": null, "schedule_id": null, "exception_id": "88bb…",
      "location": null, "reason": "휴강 보강", "student_membership_id": null }
  ],
  "total": 2, "limit": 20, "offset": 0
}
```

| kind | status | 화면 표시 예 |
| --- | --- | --- |
| `REGULAR` | `SCHEDULED` | 일반 수업 |
| `REGULAR` | `CANCELLED` | 취소선 + "휴강" + reason |
| `REGULAR` | `RESCHEDULED` | "변경됨 (원래 {original_date})" — 원래 날짜에는 표시되지 않음 |
| `MAKEUP` | `SCHEDULED` | "보강" 배지 (`student_membership_id`가 있으면 "개인 보강") |
| `MAKEUP` | `CANCELLED` | 취소선 + "보강 취소" |

## 6. 출석 API

### 6.1 학생

```http
POST /academies/{academy_id}/attendance/check-in        출석하기 (본문 없음)
GET  /academies/{academy_id}/attendance/me/today        오늘 출석 여부
GET  /academies/{academy_id}/attendance/me?from&to      내 기록 (기본 최근 30일, 최대 366일, 최신순)
```

```json
// POST /check-in → 201
{ "id": "3c1f…", "academy_id": "1b2e…", "student_membership_id": "c9e1…",
  "attendance_date": "2026-11-04", "status": "PRESENT", "source": "SELF_CHECK_IN",
  "checked_in_at": "2026-11-04T07:58:12.311Z", "note": null, "updated_by": null,
  "created_at": "…", "updated_at": "…" }

// 이미 출석함 → 409
{ "error": { "code": "ALREADY_CHECKED_IN", "message": "Already checked in today", … } }

// GET /me/today
{ "date": "2026-11-04", "checked_in": true, "record": { …위와 동일… } }
```

- 출석 버튼은 `checked_in=false`일 때만 활성화하세요. 연타·동시 요청은 서버가 1건만 저장하고 나머지는 409입니다.
- 학원 역할이 STUDENT인 ACTIVE 소속만 가능합니다 (강사 403, 비소속·탈퇴 404). 승인 전·정지 학원은 409 `ACADEMY_NOT_ACTIVE`.
- 강사가 상태를 `LATE` 등으로 바꾸면 학생 기록에도 반영됩니다.

### 6.2 강사

```http
GET   /academies/{academy_id}/attendance?date=2026-11-04&class_id=…   날짜별 출석부 (담당 학생 이름순)
GET   /academies/{academy_id}/attendance/records?from&to&student_membership_id=…
POST  /academies/{academy_id}/attendance/records                      기록 없는 날 직접 기록
PATCH /academies/{academy_id}/attendance/records/{record_id}           상태·메모 수정
GET   /academies/{academy_id}/attendance/records/{record_id}/history   수정 이력 (오래된 순)
```

```json
// GET /attendance?date=2026-11-04
{
  "date": "2026-11-04",
  "items": [
    { "student": { "membership_id": "c9e1…", "user_id": "5a3f…", "display_name": "이학생", "avatar_path": null },
      "record": { "id": "3c1f…", "status": "PRESENT", "source": "SELF_CHECK_IN", … } },
    { "student": { "membership_id": "d2f0…", "user_id": "…", "display_name": "최학생", "avatar_path": null },
      "record": null }                                   // 미출석 (기록 없음)
  ],
  "total": 2, "limit": 20, "offset": 0
}

// POST /attendance/records  (이미 있으면 409 ATTENDANCE_ALREADY_RECORDED → PATCH 사용)
{ "student_membership_id": "d2f0…", "attendance_date": "2026-11-04",
  "status": "EXCUSED", "note": "병결", "reason": "보호자 연락" }

// PATCH /attendance/records/{id}   (status·note 중 하나 이상 필수)
{ "status": "LATE", "reason": "20분 지각" }

// GET /attendance/records/{id}/history
{ "items": [
    { "id": "…", "attendance_record_id": "3c1f…", "action": "UPDATED",
      "changed_by": "a41d…", "changed_by_name": "김강사",
      "previous": { "status": "PRESENT", "note": null },
      "current":  { "status": "LATE", "note": null },
      "reason": "20분 지각", "created_at": "2026-11-04T08:30:00Z" } ],
  "total": 1, "limit": 20, "offset": 0 }
```

- 상태: `PRESENT`(출석) · `LATE`(지각) · `ABSENT`(결석) · `EXCUSED`(사유 결석). `source`: `SELF_CHECK_IN`(학생 버튼) · `INSTRUCTOR`(강사 기록).
- 학생 본인의 체크인은 이력에 남지 않고, 강사의 생성(`CREATED`)·수정(`UPDATED`)만 남습니다. 이력은 수정·삭제할 수 없습니다.

## 7. 수업 주제 · 과제 API

### 7.1 수업 주제 (반·날짜당 1건)

```http
POST   /academies/{academy_id}/classes/{class_id}/lesson-topics      { lesson_date, title, description? }
GET    /academies/{academy_id}/classes/{class_id}/lesson-topics?from&to   기본: 오늘 이후 (= 다음 수업 공지)
PATCH  /academies/{academy_id}/classes/{class_id}/lesson-topics/{topic_id}
DELETE /academies/{academy_id}/classes/{class_id}/lesson-topics/{topic_id}
```

```json
{ "lesson_date": "2026-11-06", "title": "정물 수채화", "description": "물통·팔레트 준비" }
// 응답
{ "id": "9d0e…", "academy_id": "1b2e…", "class_id": "6f0c…", "lesson_date": "2026-11-06",
  "title": "정물 수채화", "description": "물통·팔레트 준비", "created_by": "a41d…",
  "created_at": "…", "updated_at": "…" }
```

같은 반·날짜에 이미 있으면 409 `LESSON_TOPIC_EXISTS` (PATCH로 수정).

### 7.2 과제 (강사)

```http
POST   /academies/{academy_id}/tasks
GET    /academies/{academy_id}/tasks?class_id&status=ACTIVE&created_on=2026-11-04   (최신순)
GET    /academies/{academy_id}/tasks/{task_id}       상세 + 학생별 완료 현황
PATCH  /academies/{academy_id}/tasks/{task_id}       { title?, description?, due_at?, lesson_topic_id? }
DELETE /academies/{academy_id}/tasks/{task_id}       취소 (status=CANCELLED)
```

```json
// 반 전체 배포
{ "class_id": "6f0c…", "title": "석고 소묘 1장", "description": "4절, 2시간",
  "due_at": "2026-11-07T23:59:00+09:00", "lesson_topic_id": "9d0e…", "target_type": "CLASS" }

// 특정 학생 배포
{ "class_id": "6f0c…", "title": "명암 보충", "target_type": "STUDENTS",
  "student_membership_ids": ["c9e1…", "d2f0…"] }

// 응답 201 (GET /tasks/{id}도 같은 형태, 목록은 assignments 없이)
{
  "id": "41aa…", "academy_id": "1b2e…", "class_id": "6f0c…", "class_name": "예고 입시 A반",
  "lesson_topic_id": "9d0e…", "title": "석고 소묘 1장", "description": "4절, 2시간",
  "due_at": "2026-11-07T14:59:00Z", "target_type": "CLASS", "status": "ACTIVE",
  "cancelled_at": null, "created_by": "a41d…", "created_at": "…", "updated_at": "…",
  "assigned_count": 2, "completed_count": 0,
  "assignments": [
    { "assignment_id": "…", "student": { "membership_id": "c9e1…", "display_name": "이학생", … },
      "completed": false, "completed_at": null }
  ]
}
```

- 대상 학생은 **배포 시점**에 확정됩니다 (나중에 반에 들어온 학생은 받지 않음).
- `due_at`은 미래여야 합니다 (422 `INVALID_DATE_RANGE`). 반에 없는 학생 지정·학생 없는 반 → 422 `INVALID_TASK_TARGET`.
- 취소된 과제는 수정 불가(409 `TASK_CANCELLED`), 다시 DELETE해도 204.

### 7.3 과제 (학생)

```http
GET /academies/{academy_id}/tasks/me?completion=open|completed|all    (마감 임박 순)
PUT /academies/{academy_id}/tasks/{task_id}/completion                { "completed": true | false }
```

```json
// 항목 (MyTask)
{ "assignment_id": "…", "task_id": "41aa…", "academy_id": "1b2e…",
  "class_id": "6f0c…", "class_name": "예고 입시 A반", "lesson_topic_id": "9d0e…",
  "title": "석고 소묘 1장", "description": "4절, 2시간", "due_at": "2026-11-07T14:59:00Z",
  "completed": true, "completed_at": "2026-11-05T11:20:00Z",
  "is_overdue": false, "assigned_at": "2026-11-04T05:10:00Z" }
```

완료 체크는 여러 번 눌러도 처음 완료 시각이 유지됩니다. 취소된 과제 → 409 `TASK_CANCELLED`, 배정되지 않은 과제 → 404.

## 8. 개인 할 일 API (학생 전용, 본인만)

```http
POST   /personal-todos                 { title, note?, due_date? }
GET    /personal-todos?is_done=false&due_from&due_to    (날짜순, 날짜 없는 항목은 마지막)
PATCH  /personal-todos/{todo_id}       { title?, note?, due_date?, is_done? }
DELETE /personal-todos/{todo_id}       204
```

```json
{ "id": "7e2c…", "title": "크로키 10장", "note": "인체", "due_date": "2026-11-04",
  "is_done": false, "completed_at": null, "created_at": "…", "updated_at": "…" }
```

- 완료·미완료 전환은 `PATCH {"is_done": true}` / `{"is_done": false}`.
- 학원과 무관한 개인 데이터라 `academy_id`가 없습니다. 다른 사용자의 ID로 요청하면 404, 강사·관리자 계정은 403.

## 9. 오늘 할 일 통합 (학생 홈)

```http
GET /users/me/today?date=2026-11-04&academy_id=…   (둘 다 선택, 기본 오늘·전체 학원)
```

```json
{
  "date": "2026-11-04",
  "summary": { "academy_task_total": 2, "academy_task_done": 1,
               "personal_todo_total": 3, "personal_todo_done": 0 },
  "academy_tasks": [ { …MyTask… } ],
  "personal_todos": [ { …PersonalTodo… } ],
  "lesson_topics": [
    { "id": "9d0e…", "academy_id": "1b2e…", "class_id": "6f0c…", "class_name": "예고 입시 A반",
      "lesson_date": "2026-11-04", "title": "손 묘사", "description": null } ]
}
```

각 목록에 포함되는 항목 (미완료가 먼저):

| 목록 | 포함 조건 |
| --- | --- |
| `academy_tasks` | 그날 마감 · 마감 지난 미완료(`is_overdue=true`) · 마감 없는 미완료 · 그날 완료 |
| `personal_todos` | `due_date`가 그날 · 날짜 지난 미완료 · 날짜 없는 미완료 · 그날 완료 |
| `lesson_topics` | 내 반의 그날 수업 주제 |

- 학원 과제와 개인 할 일은 **목록이 분리**되어 옵니다. 한 리스트로 합쳐 보여주되, 개인 할 일은 "나만 보기" 표시를 권장합니다.
- 각 목록 최대 200건. 다음 주 마감 과제처럼 "오늘"이 아닌 항목은 `GET /tasks/me`로 보여주세요.
- 학생으로 ACTIVE 소속된 ACTIVE 학원의 과제만 포함됩니다.

## 10. 강사 대시보드

```http
GET /academies/{academy_id}/dashboard?date=2026-11-04&scope=all|mine
```

- 강사(INSTRUCTOR)는 항상 담당 반(`scope: "mine"`). 관리자는 기본 학원 전체(`all`), `scope=mine`이면 본인 담당 반.
- 집계 응답이라 페이지네이션이 없습니다.

```json
{
  "date": "2026-11-04",
  "scope": "mine",
  "totals": {
    "class_count": 1, "student_count": 2,
    "session_count": 2,                    // 오늘 수업 수 (휴강 제외)
    "open_assignment_count": 3,            // 진행 중 과제의 학생 미완료 건수
    "tasks_distributed_today": 2,
    "attendance": { "present": 1, "late": 0, "absent": 1, "excused": 0, "not_recorded": 0 }
  },
  "classes": [
    { "id": "6f0c…", "name": "예고 입시 A반", "subject": "소묘", "student_count": 2,
      "instructors": [{ "membership_id": "a41d…", "display_name": "김강사" }],
      "today_sessions": [ { …일정 항목(§5.3)… } ],
      "attendance": { "present": 1, "late": 0, "absent": 1, "excused": 0, "not_recorded": 0 },
      "open_assignment_count": 3 }
  ],
  "today_schedule": [ { …일정 항목, 시작 시각 순… } ],
  "students": [
    { "student": { "membership_id": "c9e1…", "display_name": "이학생", … },
      "class_ids": ["6f0c…"], "attendance_status": "PRESENT",      // null = 미출석
      "checked_in_at": "2026-11-04T07:58:12Z", "open_assignment_count": 1 }
  ],
  "tasks_distributed_today": [
    { "id": "41aa…", "class_id": "6f0c…", "class_name": "예고 입시 A반", "title": "과제2",
      "due_at": "…", "assigned_count": 2, "completed_count": 0, "created_at": "…" }
  ]
}
```

- 학생이 여러 반에 있어도 `students`와 `totals.student_count`에는 1번만 셉니다.
- 반을 떠난 학생의 미완료 과제는 집계에서 빠집니다. 취소된 과제도 제외됩니다.
- 작품 진행 단계·질문 콜·첨삭 대기열은 이후 버전에서 추가됩니다.

## 11. v0.3 오류 코드

공통 코드(401/403/404/422/503)는 [frontend-integration.md §8](frontend-integration.md#8-오류-응답과-처리)을 따릅니다.

| HTTP | code | 의미 | 프론트 처리 |
| --- | --- | --- | --- |
| 409 | `ALREADY_CHECKED_IN` | 오늘 이미 출석 | 출석 완료 상태로 전환 |
| 409 | `ATTENDANCE_ALREADY_RECORDED` | 그날 기록 있음 (강사 생성) | 기존 기록 PATCH로 전환 |
| 409 | `ACADEMY_NOT_ACTIVE` | 승인 전·정지 학원 | 출석 버튼 숨김 |
| 409 | `CLASS_ARCHIVED` | 종료된 반 | 편집 UI 비활성 |
| 409 | `ALREADY_IN_CLASS` | 이미 반에 배정됨 | 목록 새로고침 |
| 409 | `SCHEDULE_OVERLAP` | 같은 반 정규 수업과 시간 겹침 | 시간 입력에 표시 |
| 409 | `SCHEDULE_EXCEPTION_EXISTS` | 그 회차에 휴강·변경이 이미 있음 | 기존 예외 수정·취소 유도 |
| 409 | `LESSON_TOPIC_EXISTS` | 그 날짜에 주제가 이미 있음 | 기존 주제 수정 |
| 409 | `TASK_CANCELLED` | 취소된 과제 | 목록 새로고침 |
| 422 | `INVALID_CLASS_MEMBER` | 학원에 없는 멤버 / 반에 없는 학생(개인 보강) | 선택 목록 새로고침 |
| 422 | `INVALID_OCCURRENCE` | 정규 수업 회차가 아닌 날짜 | 달력에서 회차 선택 |
| 422 | `INVALID_DATE_RANGE` | 기간 역전·최대 기간 초과·지난 마감 | 입력 검증 |
| 422 | `INVALID_TASK_TARGET` | 반에 없는 학생 지정, 학생 없는 반, 다른 반의 주제 | 대상 다시 선택 |
| 422 | `VALIDATION_ERROR` | 형식 오류 (`details[].field`) | 입력 폼에 표시 |
| 403 | `FORBIDDEN` | 담당 반·담당 학생이 아님, 역할 부족 | 버튼 숨김 |
| 404 | `NOT_FOUND` | 다른 학원·보이지 않는 리소스 | "찾을 수 없음" |

## 12. 구현 팁

- 학원 선택 후 `GET /academies/{id}` 의 `my_membership.role`로 학생/강사 화면을 나누고, 반 화면은 `my_role`(반 역할)로 편집 버튼을 결정하세요. 최종 권한 판단은 서버가 합니다.
- 출석 버튼 → 성공(201) 또는 409 `ALREADY_CHECKED_IN` 모두 "출석 완료"로 처리하면 연타·재시도에 안전합니다.
- 일정 화면은 주 단위(`from`=월요일, `to`=일요일)로 요청하고, 강사 월간 보기는 최대 62일 범위로 요청하세요.
- 목록 API는 `limit` 최대 100입니다. 반 학생 수가 많으면 `offset`으로 이어 받으세요.
