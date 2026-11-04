# 프론트엔드 연동 가이드 (v0.4 작품 사진 · 시험 타이머)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.4
> 선행 문서: [frontend-integration.md](frontend-integration.md) (인증·오류 형식), [frontend-integration-v0.3.md](frontend-integration-v0.3.md) (ID·날짜 규칙, 권한)
> API 문서: http://127.0.0.1:8000/docs (최종 기준은 OpenAPI)

v0.4는 **F-06 단계별 작품 사진 업로드**와 **F-10 시험 타이머·단계 알림**입니다.
인증(`Authorization: Bearer <access_token>`), 오류 형식(`error.code`), 페이지네이션(`{items, total, limit, offset}`)은 이전과 같습니다.

## 1. 작품 단계와 상태값

| 값 | 의미 |
| --- | --- |
| 사진 단계 `stage` | `SKETCH`(스케치) · `PROGRESS`(중간) · `FINAL`(완성) |
| 작품 진행 `progress` | `NOT_STARTED` · `SKETCH` · `PROGRESS` · `FINAL` — 사진이 있는 가장 늦은 단계 |
| 사진 상태 `status` | `PENDING`(업로드 URL 발급, 완료 전) · `ACTIVE`(작품에 연결됨) · `DELETED` |
| 대표 사진 `is_representative` | 단계별 최대 1장. 단계 첫 사진이 자동으로 대표 |
| 표지 `cover_photo_id` | 가장 늦은 단계의 대표 사진 (목록 썸네일용) |

- 같은 단계에 여러 장 올릴 수 있습니다 (기본 단계당 최대 10장).
- 목록·상세 응답에는 `ACTIVE` 사진만 나옵니다.

## 2. 작품 API

### 2.1 학생 (본인 작품)

```http
POST   /api/v1/artworks                          작품 생성
GET    /api/v1/artworks?academy_id&work_date_from&work_date_to   내 작품 (작업 날짜 최신순)
GET    /api/v1/artworks/{artwork_id}?include_urls=true           상세 + 사진 (+ Signed URL)
PATCH  /api/v1/artworks/{artwork_id}                             수정
DELETE /api/v1/artworks/{artwork_id}                             삭제 (사진 포함)
GET    /api/v1/artworks/{artwork_id}/progress                    진행 상태
GET    /api/v1/artworks/{artwork_id}/photos?include_urls=true    사진 목록
POST   /api/v1/artworks/{artwork_id}/photos                      업로드 요청 (Signed upload URL)
POST   /api/v1/artworks/{artwork_id}/photos/{photo_id}/complete  업로드 완료 처리
PATCH  /api/v1/artworks/{artwork_id}/photos/{photo_id}           대표 사진 지정
DELETE /api/v1/artworks/{artwork_id}/photos/{photo_id}           사진 삭제
GET    /api/v1/artworks/{artwork_id}/photos/{photo_id}/url       사진 Signed URL
```

- **학생 계정(`user_type=STUDENT`)만** 사용합니다. 학원에 소속되지 않아도 개인 작품을 만들 수 있습니다.
- 다른 사람의 작품 ID로 요청하면 404입니다.

```json
// POST /artworks
{ "title": "석고 아그리파 소묘", "description": "4절",
  "work_date": "2026-11-04",                      // 생략하면 오늘(Asia/Seoul)
  "academy_id": "1b2e…",                          // 선택: 학원 연결 (그 학원 학생이어야 함)
  "class_id": "6f0c…",                            // 선택: 내가 배정된 반
  "task_id": "41aa…" }                            // 선택: 나에게 배정된 과제 (반은 자동 연결)

// 응답 201 (상세 GET도 같은 형태)
{
  "id": "a9d1…", "title": "석고 아그리파 소묘", "description": "4절", "work_date": "2026-11-04",
  "academy_id": "1b2e…", "student_membership_id": "c9e1…", "class_id": "6f0c…", "task_id": "41aa…",
  "progress": "SKETCH", "photo_count": 2, "cover_photo_id": "p1…",
  "created_at": "…", "updated_at": "…",
  "stages": [
    { "stage": "SKETCH", "photo_count": 2, "representative_photo_id": "p1…",
      "first_uploaded_at": "…", "last_uploaded_at": "…" },
    { "stage": "PROGRESS", "photo_count": 0, "representative_photo_id": null,
      "first_uploaded_at": null, "last_uploaded_at": null },
    { "stage": "FINAL", "photo_count": 0, "representative_photo_id": null,
      "first_uploaded_at": null, "last_uploaded_at": null }
  ],
  "photos": [
    { "id": "p1…", "artwork_id": "a9d1…", "stage": "SKETCH", "status": "ACTIVE",
      "content_type": "image/jpeg", "size_bytes": 284311, "width": 3024, "height": 4032,
      "is_representative": true, "uploaded_at": "…", "created_at": "…",
      "url": "https://<project>.supabase.co/storage/v1/object/sign/artworks/…?token=…",  // include_urls=true일 때
      "url_expires_at": "2026-11-04T08:05:00Z" }
  ]
}
```

- 연결 오류(소속되지 않은 학원, 배정되지 않은 반·과제, 학원 없이 반만 지정) → 422 `INVALID_ARTWORK_LINK`.
- `PATCH`에서 `academy_id`를 바꾸거나 `null`로 해제하면 반·과제 연결도 함께 초기화됩니다.

### 2.2 강사 (담당 학생 작품, 읽기 전용)

```http
GET /api/v1/academies/{academy_id}/artworks?student_membership_id=…        담당 학생 작품 목록
GET /api/v1/academies/{academy_id}/artworks/{artwork_id}?include_urls=true 상세 + 사진
GET /api/v1/academies/{academy_id}/artworks/{artwork_id}/photos/{photo_id}/url
```

- **학원에 연결된 작품**만 보입니다. 학생의 개인 작품(학원 미연결)은 강사에게 보이지 않습니다.
- 담당 학생(담당 반 학생)만 볼 수 있습니다. OWNER/MANAGER는 학원의 모든 학생을 볼 수 있습니다. 비담당 학생 작품은 403, 다른 학원·개인 작품은 404입니다.
- 응답은 학생 응답에 `student: { membership_id, user_id, display_name, avatar_path }`가 추가된 형태입니다.

## 3. Supabase Storage 업로드 절차

파일은 **백엔드를 거치지 않고** 브라우저에서 Storage로 바로 올립니다. 백엔드는 업로드 전에 권한·형식을 검사하고, 업로드 후에는 실제 파일을 검증합니다.

```text
 [React]                          [ART MATE API]                       [Supabase Storage]
 1. 파일 선택 (형식·크기 미리 검사)
 2. POST /artworks/{id}/photos ──▶ 형식·크기·장수 검증, 사진 PENDING 생성
                               ◀── { photo, upload: {path, token, url, expires_at} }
 3. uploadToSignedUrl(path, token, file) ───────────────────────────▶ 비공개 버킷에 저장
 4. POST …/photos/{photo_id}/complete ─▶ 파일 다운로드 → 실제 이미지 형식·크기·픽셀 검증,
                                         중복(내용 해시) 확인 → ACTIVE, 대표 사진 지정
                               ◀── PhotoRead (status: ACTIVE)
```

```js
// src/lib/artworkUpload.js
import { supabase } from './supabase'
import { api, ApiError } from './api'

const ALLOWED = ['image/jpeg', 'image/png', 'image/webp']
const MAX_BYTES = 10 * 1024 * 1024

export async function uploadStagePhoto(artworkId, stage, file, { replacesPhotoId } = {}) {
  if (!ALLOWED.includes(file.type)) throw new Error('JPG, PNG, WEBP만 올릴 수 있어요')
  if (file.size > MAX_BYTES) throw new Error('10MB 이하 사진만 올릴 수 있어요')

  // 1) 업로드 요청
  const ticket = await api(`/artworks/${artworkId}/photos`, {
    method: 'POST',
    body: JSON.stringify({
      stage,                       // 교체(replacesPhotoId)면 생략 가능
      content_type: file.type,
      file_size: file.size,
      file_name: file.name,        // 확장자 검증용 (서버에 저장하지 않음)
      replaces_photo_id: replacesPhotoId ?? null,
    }),
  })

  // 2) Storage 업로드 (로그인된 supabase 클라이언트 사용)
  const { error } = await supabase.storage
    .from(ticket.upload.bucket)
    .uploadToSignedUrl(ticket.upload.path, ticket.upload.token, file, { contentType: file.type })
  if (error) throw error   // 다시 시도하려면 1)부터 (새 업로드 요청)

  // 3) 완료 처리 (네트워크 오류 시 같은 요청을 다시 보내도 안전: 멱등)
  return api(`/artworks/${artworkId}/photos/${ticket.photo.id}/complete`, { method: 'POST' })
}
```

- 업로드 요청 후 **`upload.expires_at`(기본 1시간) 안에** 업로드와 완료 처리를 끝내야 합니다. 지나면 409 `UPLOAD_EXPIRED`이며, 새로 요청하세요.
- 완료 처리를 하지 않은 사진(PENDING)은 목록에 나오지 않고, 만료 후 자동으로 정리됩니다.
- **교체**: `replaces_photo_id`를 넣어 업로드하면 완료 시점에 기존 사진이 삭제되고, 대표 여부도 이어받습니다. 업로드가 실패하면 기존 사진은 그대로 남습니다.
- 서버 제한(설정값): 형식 JPEG/PNG/WEBP, 최대 10MB, 단계당 10장, 최대 5천만 픽셀. HEIC(아이폰 기본)는 지원하지 않습니다. 브라우저에서 JPEG로 변환하거나 아이폰 설정 > 카메라 > 포맷 > "높은 호환성"을 안내하세요.

## 4. Signed URL 사용 방법

- 버킷은 비공개입니다. 사진은 **짧은 만료(기본 5분)의 Signed URL**로만 볼 수 있습니다.
- 목록·상세 API에 `include_urls=true`를 붙이면 사진마다 `url`과 `url_expires_at`이 옵니다. 사진 1장만 필요하면 `GET …/photos/{photo_id}/url`을 쓰세요.
- URL을 저장하거나 공유하지 마세요. 만료되면 `<img onError>`에서 URL API를 다시 호출해 바꿉니다.
- 응답의 `url`을 그대로 `<img src>`에 쓰면 됩니다 (추가 헤더 불필요).

```jsx
function ArtworkPhoto({ artworkId, photo }) {
  const [src, setSrc] = useState(photo.url)
  const refresh = async () => {
    const { url } = await api(`/artworks/${artworkId}/photos/${photo.id}/url`)
    setSrc(url)
  }
  return <img src={src} onError={refresh} alt={photo.stage} />
}
```

## 5. 시험 타이머

### 5.1 구조

- **템플릿**: 시험 이름·유형·총시간과 단계별 목표 시각(시작 후 몇 분까지 그 단계를 끝낼지)
  - 예: 총 240분, SKETCH 60분 · PROGRESS 180분 · FINAL 230분 (`SKETCH < PROGRESS < FINAL ≤ 총시간`)
- **세션**: 반 단위 실제 시험. 생성 시 템플릿 설정을 복사합니다 → 템플릿을 고쳐도 진행 중 시험은 그대로입니다.
- **시작**하면 서버가 시작 시각, 종료 예정 시각, 단계별 목표 시각을 저장하고, 그 시점의 반 학생을 참가자로 등록합니다(현재 단계 `SKETCH`).
- 상태: `SCHEDULED` → `RUNNING` → `ENDED` (`end_reason`: `MANUAL` 강사 종료 / `TIME_UP` 시간 만료), 시작 전 취소 `CANCELLED`.
- 학생 작업 단계: `SKETCH` → `PROGRESS` → `FINAL` → `DONE`(완료). 뒤로 되돌리기도 가능합니다.

### 5.2 API

```http
# 강사 (템플릿: 강사 이상. 수정·보관은 만든 사람 또는 OWNER/MANAGER)
POST   /api/v1/academies/{academy_id}/exam-templates
GET    /api/v1/academies/{academy_id}/exam-templates?include_archived=false
GET    /api/v1/academies/{academy_id}/exam-templates/{template_id}
PATCH  /api/v1/academies/{academy_id}/exam-templates/{template_id}
PUT    /api/v1/academies/{academy_id}/exam-templates/{template_id}/stage-targets
DELETE /api/v1/academies/{academy_id}/exam-templates/{template_id}         보관

# 강사 (세션: 그 반 담당 강사 또는 OWNER/MANAGER)
POST   /api/v1/academies/{academy_id}/exam-sessions                        { template_id, class_id, title?, start_now? }
GET    /api/v1/academies/{academy_id}/exam-sessions?class_id&status
GET    /api/v1/academies/{academy_id}/exam-sessions/{session_id}           반 전체 현황
POST   /api/v1/academies/{academy_id}/exam-sessions/{session_id}/start
POST   /api/v1/academies/{academy_id}/exam-sessions/{session_id}/end
DELETE /api/v1/academies/{academy_id}/exam-sessions/{session_id}           시작 전 취소

# 학생
GET    /api/v1/academies/{academy_id}/exam-sessions/me?active=true         참가 중인 시험
GET    /api/v1/academies/{academy_id}/exam-sessions/{session_id}/me        내 타이머
PUT    /api/v1/academies/{academy_id}/exam-sessions/{session_id}/me/stage  { "stage": "PROGRESS" }
```

```json
// POST /exam-templates
{ "name": "기초디자인 실전 모의고사", "exam_type": "기초디자인", "total_minutes": 240,
  "stage_targets": [ { "stage": "SKETCH", "offset_minutes": 60 },
                     { "stage": "PROGRESS", "offset_minutes": 180 },
                     { "stage": "FINAL", "offset_minutes": 230 } ] }
```

### 5.3 타이머 응답 형식 (`timer`)

모든 세션 응답에 같은 `timer` 객체가 들어 있습니다. 예: 16:00 시작, 17:15에 조회

```json
{
  "id": "e5…", "class_id": "6f0c…", "class_name": "예고 입시 A반", "title": "11월 모의고사",
  "exam_type": "기초디자인", "total_minutes": 240, "template_id": "…", "academy_id": "…", "created_at": "…",
  "timer": {
    "server_time": "2026-11-10T08:15:00Z",
    "status": "RUNNING", "end_reason": null,
    "started_at": "2026-11-10T07:00:00Z",
    "ends_at": "2026-11-10T11:00:00Z",       // 종료 예정
    "ended_at": null,
    "total_seconds": 14400, "elapsed_seconds": 4500, "remaining_seconds": 9900,
    "stages": [
      { "stage": "SKETCH",   "offset_minutes": 60,  "target_at": "2026-11-10T08:00:00Z", "seconds_remaining": 0,    "passed": true },
      { "stage": "PROGRESS", "offset_minutes": 180, "target_at": "2026-11-10T10:00:00Z", "seconds_remaining": 6300, "passed": false },
      { "stage": "FINAL",    "offset_minutes": 230, "target_at": "2026-11-10T10:50:00Z", "seconds_remaining": 9300, "passed": false }
    ],
    "expected_stage": "PROGRESS",            // 지금 해야 할 단계 (모든 목표가 지나면 DONE)
    "current_target": { "stage": "PROGRESS", "target_at": "2026-11-10T10:00:00Z", "seconds_remaining": 6300, … },
    "next_alert_at": "2026-11-10T10:00:00Z"  // 다음 알림 (다음 단계 목표 또는 종료)
  },
  "me": {                                     // 학생 API에만
    "current_stage": "SKETCH", "stage_updated_at": "…",
    "sketch_at": "…", "progress_at": null, "final_at": null, "done_at": null,
    "behind_schedule": true                   // 현재 단계가 expected_stage보다 늦음
  }
}
```

강사 현황(`GET /exam-sessions/{id}`)에는 추가로 `participant_count`, `stage_counts`(단계별 인원), `behind_count`, `participants[]`(학생별 `current_stage`, 단계 시각, `behind_schedule`)가 옵니다.

### 5.4 프론트 타이머 구현 규칙

- **매초 API를 호출하지 마세요.** 응답의 `server_time`으로 기기 시계 오차를 구하고, 로컬에서 1초마다 다시 그립니다.
- 새로고침하거나 다른 기기로 접속하면 `GET …/{session_id}/me`(학생) 또는 `GET …/{session_id}`(강사)를 한 번 호출해 상태를 복원합니다. 서버가 저장한 시각으로 계산하므로 어느 기기에서나 같은 값이 나옵니다.
- 다시 불러올 시점: 화면 진입, 탭 복귀(`visibilitychange`), 단계 변경 후, `next_alert_at` 도달 시, 강사 화면은 30~60초 간격 정도.

```js
// 서버 시각 기준 카운트다운
function useExamClock(timer) {
  const offset = useMemo(() => Date.parse(timer.server_time) - Date.now(), [timer.server_time])
  const [now, setNow] = useState(() => Date.now() + offset)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() + offset), 1000)
    return () => clearInterval(id)
  }, [offset])
  const left = (iso) => (iso ? Math.max(0, Math.floor((Date.parse(iso) - now) / 1000)) : null)
  return {
    remaining: timer.status === 'RUNNING' ? left(timer.ends_at) : timer.remaining_seconds,
    toNextStage: left(timer.current_target?.target_at),
    timeUp: timer.status === 'RUNNING' && left(timer.ends_at) === 0, // → 다시 조회해 ENDED 확인
  }
}
```

### 5.5 단계 알림 처리 방법

v0.4 서버는 **알림을 보내지 않고 목표 시각 데이터만 제공합니다.** 알림 표시는 프론트(개발자 B) 또는 이후 버전에서 구현합니다.

1. 화면 안 알림(권장, v0.4): `timer.stages[].target_at`, `ends_at` 시각에 토스트·소리·진동을 띄웁니다. `setTimeout(target - (Date.now() + offset))`로 예약하고, 타이머를 다시 받으면 예약을 지우고 다시 만듭니다.
2. 미리 알림: 예를 들어 목표 10분 전과 5분 전에 표시하려면 `target_at - 10분`으로 직접 계산합니다.
3. 브라우저 알림: `Notification.requestPermission()` 후 탭이 열려 있을 때 `new Notification(...)`을 사용합니다. 탭이 닫혀 있으면 동작하지 않습니다.
4. 백그라운드 푸시(이후 버전): Web Push(서비스 워커 + VAPID) 또는 FCM이 필요하고, 서버에 구독 저장과 예약 발송 작업을 추가해야 합니다. v0.4 범위가 아닙니다.
5. 이미 지난 목표(`passed: true`)는 다시 알리지 않습니다. 시험이 `ENDED`면 예약을 모두 지웁니다.

## 6. 화면별 API

| 화면 | 사용자 | API |
| --- | --- | --- |
| 내 작품 목록 | 학생 | `GET /artworks` (썸네일: `cover_photo_id` → `GET …/photos/{id}/url`, 또는 상세 `include_urls`) |
| 작품 만들기·수정 | 학생 | `POST/PATCH /artworks`, 연결 후보: v0.3 `GET /academies?mine=true`, `GET /academies/{id}/classes`, `GET /academies/{id}/tasks/me` |
| 작품 상세 (단계별 사진) | 학생 | `GET /artworks/{id}?include_urls=true`, 업로드 §3, `PATCH`(대표), `DELETE`(사진) |
| 진행 상태 배지 | 학생 | 목록의 `progress` 또는 `GET /artworks/{id}/progress` |
| 학생 작품 보기 | 강사 | `GET /academies/{id}/artworks?student_membership_id=…`, `GET /academies/{id}/artworks/{artwork_id}?include_urls=true` |
| 시험 템플릿 관리 | 강사 | `…/exam-templates` CRUD, `PUT …/stage-targets` |
| 시험 시작·종료 | 강사 | `POST /exam-sessions` (`start_now`), `POST …/start`, `POST …/end` |
| 반 시험 현황판 | 강사 | `GET /exam-sessions/{id}` (30~60초마다 갱신) |
| 시험 중 화면 | 학생 | `GET /exam-sessions/me` → `GET /exam-sessions/{id}/me`, `PUT …/me/stage` |

## 7. 오류 코드

| HTTP | code | 상황 | 프론트 처리 |
| --- | --- | --- | --- |
| 422 | `UNSUPPORTED_FILE_TYPE` | 허용하지 않는 형식·확장자 | 파일 다시 선택 |
| 422 | `FILE_TOO_LARGE` | 크기 초과 (요청·완료 단계 모두) | 압축·리사이즈 안내 |
| 422 | `INVALID_IMAGE` | 실제 이미지가 아님, 손상, 선언 형식과 다름, 픽셀 과다 | 다른 파일 |
| 409 | `PHOTO_LIMIT_REACHED` | 단계당 장수 초과 | 기존 사진 삭제·교체 유도 |
| 409 | `DUPLICATE_PHOTO` | 같은 작품에 같은 파일 (`details.photo_id`) | "이미 올린 사진" 안내 |
| 409 | `UPLOAD_NOT_FOUND` | 완료 처리 시 Storage에 파일 없음 | 업로드 재시도 후 다시 완료 |
| 409 | `UPLOAD_EXPIRED` | 업로드 요청 만료 | 업로드 요청부터 다시 |
| 409 | `PHOTO_NOT_ACTIVE` | 완료 전 사진에 대표 지정·URL·교체 | 완료 처리 먼저 |
| 422 | `INVALID_ARTWORK_LINK` | 학원·반·과제 연결 불가 | 선택지 새로고침 |
| 503 | `STORAGE_UNAVAILABLE` | Storage 일시 장애 | 잠시 후 재시도 (완료 처리는 그대로 다시 호출) |
| 503 | `STORAGE_NOT_CONFIGURED` | 서버 Storage 설정 누락 | 백엔드 담당자 문의 |
| 422 | `INVALID_STAGE_TARGETS` | 단계 누락·중복, 순서 역전, 총시간 초과 | 입력 폼에 표시 |
| 409 | `TEMPLATE_ARCHIVED` | 보관된 템플릿 | 목록 새로고침 |
| 409 | `EXAM_ALREADY_RUNNING` | 그 반에 진행 중 시험 있음 (`details.session_id`) | 기존 시험으로 이동 |
| 409 | `EXAM_INVALID_STATE` | 이미 시작·취소된 시험 시작/취소, 시작 전 종료 | 상태 새로고침 |
| 409 | `EXAM_NOT_RUNNING` | 종료·시간 만료 후 단계 변경 | 종료 화면으로 전환 |
| 403 | `FORBIDDEN` | 비담당 반·학생, 역할 부족, 강사 계정의 작품 생성 | 버튼 숨김 |
| 404 | `NOT_FOUND` | 남의 작품, 다른 학원, 참가하지 않은 시험 | "찾을 수 없음" |

예외 처리 요령
- 업로드 중 네트워크가 끊기면: Storage 업로드가 끝났는지 모르면 **완료 처리부터 호출**합니다. `UPLOAD_NOT_FOUND`면 업로드부터 다시, 성공이면 끝입니다.
- 완료 처리에서 422가 나오면 그 사진은 서버에서 삭제됩니다. 같은 `photo_id`로 다시 시도하지 말고 새로 요청하세요.
- 타이머는 `server_time`과 `status`를 우선합니다. 로컬 카운트다운이 0이 되면 API를 한 번 호출해 `ENDED`를 확인하세요.
