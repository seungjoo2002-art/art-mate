# 프론트엔드 연동 — VER.2 (P0·P1)

> 기준: Alembic `0010`(P0, PR #47) + `0011`(P1). 선행: [frontend-integration-v0.9.md](frontend-integration-v0.9.md)
> 모든 API는 `Authorization: Bearer <Supabase access token>` 필요. 오류 형식은 기존과 같다: `{"error": {"code", "message", "details"}}`.
> 기존 요청 형식은 그대로 동작한다 (필드 추가만).

## 1. 커뮤니티 (P0)

### 1.1 카테고리

| code | 화면 | 작품(사진) |
| --- | --- | --- |
| `PRACTICE_QUESTION` | 실기 질문 | 선택 |
| `FEEDBACK_REQUEST` | 피드백 요청 | 선택 |
| `ARTWORK_SHARE` | 작품 공유 | **필수** |
| `FREE` | 자유게시판 | 선택 |

- 기존 게시물은 `question`이 있으면 `FEEDBACK_REQUEST`, 없으면 `ARTWORK_SHARE`로 옮겨 두었다 → `frontend/src/features/community/labels.js`의 `postCategory()`·`matchesCategory()`(question 기반 추정)를 **응답의 `category`로 교체**하고 필터는 서버로 넘긴다.

```http
GET /api/v1/community/posts?category=PRACTICE_QUESTION&category=FREE&q=명암&limit=20&offset=0
```

| 쿼리 | 설명 |
| --- | --- |
| `category` | 여러 번 주면 OR. 잘못된 값 422 |
| `q` (P1) | 제목·본문·질문 부분 일치, 대소문자 무시, 2~50자 (밖이면 422). `%`·`_`도 글자 그대로 찾음 |
| `practical_type`, `work_category`, `academy_id` | 기존 그대로 |

### 1.2 게시물 작성

```jsonc
// 사진 없는 글 (공유 동의 불필요)
POST /api/v1/community/posts
{ "title": "명암 단계 질문", "body": "몇 단계로 나눠요?", "category": "PRACTICE_QUESTION",
  "practical_type": "DRAWING", "author_display": "ANONYMOUS" }   // author_display 기본 NAME

// 작품 게시물 (기존 + 사진 선택)
{ "artwork_id": "a1…", "title": "스케치 과정", "category": "ARTWORK_SHARE",
  "photo_id": "p1…",            // 작품의 스케치·중간·완성 사진 중 1장. 생략 = 완성 대표 사진
  "question": null }
```

| 규칙 | 오류 |
| --- | --- |
| 사진 없는 글: `body` 필수, `ARTWORK_SHARE` 불가, `photo_id` 불가 | 422 |
| 작품 게시물: 작품의 커뮤니티 공유 동의 필요 | 409 `SHARING_CONSENT_REQUIRED` |
| 작품당 게시물 1개 | 409 `POST_ALREADY_EXISTS` |
| 완성 사진이 없는데 `photo_id` 생략 | 409 `PHOTO_SELECTION_REQUIRED` |
| 다른 작품·다른 사람의 사진 | 404 |
| 작품 게시물에 `author_display` (작성자 표시는 공유 동의 설정을 따름) | 422 |

응답 `PostRead` 추가 필드: `category`, `has_artwork`(false = 사진 없는 글, `image`는 null), `photo_id`(본인 게시물만).

### 1.3 수정·삭제

```jsonc
PATCH /api/v1/community/posts/{id}
{ "category": "FEEDBACK_REQUEST" }        // 사진 없는 글을 ARTWORK_SHARE로는 못 바꿈 (422)
{ "photo_id": "p2…" }                     // 공유 사진 변경 (작품 게시물). null = 완성 대표 사진으로
{ "author_display": "ANONYMOUS" }         // 사진 없는 글만
DELETE /api/v1/community/posts/{id}       // 게시물 삭제 + 게시물용으로 고른 사진의 공유 이미지 삭제
```

### 1.4 작품 공유 동의 변경점

- **커뮤니티 동의**는 완성 사진 없이도 가능 (사진 1장 이상). 이 경우 게시할 때 `photo_id`가 필요하다.
- **참고작 동의**는 기존처럼 완성(FINAL) 대표 사진 필수 (409 `FINAL_PHOTO_REQUIRED`).
- 원본 사진을 삭제·교체하면 그 사진으로 만든 게시물 이미지는 내려가고 게시물은 남는다 (`image: null`) → 다른 사진을 다시 고르도록 안내.

### 1.5 익명 댓글 (P1)

```jsonc
POST /api/v1/community/posts/{id}/comments
{ "body": "구도 좋아요", "is_anonymous": true }
// → author: { "display_name": "익명 학생", "is_anonymous": true, "is_me": false }   (다른 사람에게)
//   본인에게는 is_me: true. 작성자 이름·ID는 응답에 없다
PATCH /api/v1/community/comments/{id}  { "body": "…", "is_anonymous": false }   // 본인만
```

관리자 신고 목록(`GET /api/v1/admin/community/reports`)에 `target_author_id`(익명 포함 실제 작성자)가 추가됐다.

## 2. 실기시험 단계 (P0)

단계 코드: `IDEA` 아이디어 · `SKETCH` 스케치 · `COLOR` 채색 · `FINISH` 마무리 (1~4개, 순서 = 배열 순서).

| Method | Path | 설명 |
| --- | --- | --- |
| PUT | `/api/v1/artworks/{id}/exam/plan` | 단계 계획 저장 → 목표 합계가 `time_limit_minutes` |
| GET | `/api/v1/artworks/{id}/exam` | 단계 상태 + 타이머 (다른 기기에서도 같은 값) |
| POST | `/api/v1/artworks/{id}/exam/next` | 다음 단계로 |
| POST | `/api/v1/artworks/{id}/timer/events` | (기존) START → 첫 단계 시작, STOP → 현재 단계 종료, RESET → 초기화 |

```jsonc
PUT /artworks/{id}/exam/plan
{ "stages": [ { "stage": "IDEA", "target_minutes": 40 }, { "stage": "SKETCH", "target_minutes": 80 },
              { "stage": "COLOR", "target_minutes": 180 } ] }

POST /artworks/{id}/exam/next
{ "current_stage": "IDEA" }       // 화면에 보이는 현재 단계

// → ArtworkExamRead (GET도 같은 모양)
{ "artwork_id": "a1…", "current_stage": "SKETCH", "total_target_minutes": 300,
  "stages": [ { "stage": "IDEA", "label": "아이디어", "position": 0, "target_minutes": 40,
                "status": "DONE", "elapsed_seconds": 2310, "over_target": false,
                "started_at": "…", "ended_at": "…" },
              { "stage": "SKETCH", "status": "ACTIVE", "elapsed_seconds": 12, … },
              { "stage": "COLOR", "status": "PENDING", "elapsed_seconds": 0, … } ],
  "timer": { …TimerRead… } }
```

- 단계 시간은 타이머 누적 시간(일시정지 제외). `ACTIVE` 단계는 조회 시점까지 계산되므로 화면에서는 `timer.running_since`부터 1초씩 더한다.
- 오류: 계획 없음 409 `EXAM_PLAN_REQUIRED`, 타이머가 RUNNING·PAUSED가 아님 409 `EXAM_NOT_RUNNING`, `current_stage`가 서버와 다름(두 번 누름·다른 기기에서 이미 넘김) 409 `EXAM_STAGE_CONFLICT`(`details.current_stage`로 화면 갱신), 마지막 단계 409 `EXAM_LAST_STAGE`(STOP으로 끝냄), 시작 후 단계 구성 변경 409 `EXAM_ALREADY_STARTED`(목표 시간만 변경 가능), 단계 전환보다 이른 시각의 타이머 이벤트 422 `TIMER_INVALID_TIME`.

프론트 수정: `frontend/src/features/artworks/exam.js`의 `loadExamSession`/`saveExamSession`/`stageSeconds`(이 기기 localStorage에 단계 시작 시점 저장)를 `GET /exam`·`POST /exam/next`로 교체. 시험 시작 시 `PUT /exam/plan` → 타이머 START.

## 3. 기본 시험 목표 시간 (P1)

```jsonc
GET /api/v1/users/me/exam-defaults
// → { "stages": [{ "stage": "IDEA", "target_minutes": 40 }, …], "source": "DEFAULT" | "ACCOUNT" }
PUT /api/v1/users/me/exam-defaults
{ "stages": [ { "stage": "IDEA", "target_minutes": 30 }, … ] }   // ArtworkExamPlan과 같은 규칙, 학생만
```

기존 localStorage 값 옮기기 (한 번):

```js
const LEGACY = 'artmate.examStageTargets'
export async function loadExamDefaults() {
  const server = await api('/users/me/exam-defaults')
  if (server.source === 'ACCOUNT') return server.stages
  try {
    const saved = JSON.parse(localStorage.getItem(LEGACY))   // [{ key: 'IDEA', minutes: 40 }, …]
    if (Array.isArray(saved) && saved.length) {
      const stages = saved.map(({ key, minutes }) => ({ stage: key, target_minutes: Number(minutes) }))
      const stored = await api('/users/me/exam-defaults', { method: 'PUT', body: { stages } })
      localStorage.removeItem(LEGACY)
      return stored.stages
    }
  } catch { /* 형식이 다르면 서버 기본값 사용 */ }
  return server.stages
}
```

## 4. 실명·닉네임 (P1)

- `POST /users/me` (회원가입 직후): `real_name` 선택 추가. `display_name`은 **공개 닉네임**.
- `PATCH /users/me`: `real_name` 변경, `null`이면 삭제. 1~50자.
- `real_name`은 `GET/POST/PATCH /users/me` 응답에만 있다. 커뮤니티·강사 화면·학원 멤버 목록 등에는 `display_name`만.
- 기존 회원의 `real_name`은 `null` (추정해 채우지 않음) → 마이페이지에서 입력 안내.

## 5. 프론트 수정 체크리스트

1. 커뮤니티 목록: 카테고리 탭 → `category` 쿼리, 검색창 → `q` (2자 이상일 때만 요청)
2. 글쓰기: 카테고리 선택, 작품 없이 작성, 작품 선택 시 사진(스케치·중간·완성) 선택 → `photo_id`
3. 게시물 카드: `has_artwork=false`면 이미지 영역 없음, `image=null`인 작품 게시물은 "사진이 내려갔어요"
4. 댓글: 익명 체크박스 → `is_anonymous`
5. 실기 탭: 단계 계획·다음 단계·진행 상태를 서버 API로 (기존 localStorage 제거), 기본 목표는 `/users/me/exam-defaults`
6. 회원가입·마이페이지: 실명 입력 (`real_name`), 닉네임 라벨 정리
7. `labels.js`의 question 기반 카테고리 추정 제거

## 6. 오류 코드 (추가)

| 코드 | HTTP | 상황 |
| --- | --- | --- |
| `PHOTO_SELECTION_REQUIRED` | 409 | 완성 대표 사진이 없는데 `photo_id` 없이 게시 |
| `EXAM_PLAN_REQUIRED` | 409 | 단계 계획 없이 다음 단계 |
| `EXAM_NOT_RUNNING` | 409 | 타이머가 시작 전·종료됨 |
| `EXAM_STAGE_CONFLICT` | 409 | 현재 단계 불일치 (중복 전환) |
| `EXAM_LAST_STAGE` | 409 | 마지막 단계에서 다음 단계 |
| `EXAM_ALREADY_STARTED` | 409 | 시작 후 단계 구성 변경 |
