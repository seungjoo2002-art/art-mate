# 프론트엔드 연동 가이드 (v0.5 질문 콜 · 피드백 녹음)

> 대상: 프론트엔드 개발자 B · 기준 버전: v0.5
> 선행 문서: [frontend-integration.md](frontend-integration.md) (인증·오류 형식), [v0.3](frontend-integration-v0.3.md) (반·membership_id), [v0.4](frontend-integration-v0.4.md) (작품·Storage 업로드·Signed URL)
> API 문서: http://127.0.0.1:8000/docs (최종 기준은 OpenAPI)

v0.5는 **F-07 질문 콜·대기열**과 **F-11 피드백 음성 녹음 저장**입니다. STT·AI 요약은 v0.6에서 추가합니다.

## 1. 질문 콜

### 1.1 상태값

| status | 의미 | 학생 화면 | 강사 화면 |
| --- | --- | --- | --- |
| `WAITING` | 대기 중 | "n번째로 기다리는 중 · 약 m분" | 대기 목록 |
| `CALLED` | 강사가 호출함 | "강사님이 부르고 있어요" (`called_by_name`) | 호출 중 목록 |
| `IN_PROGRESS` | 질문 처리 중 | "질문 중" | 처리 중 목록 |
| `COMPLETED` | 처리 완료 | "완료" | 목록에서 사라짐 |
| `CANCELLED` | 학생·강사가 취소 | "취소됨" | 사라짐 |
| `SKIPPED` | 호출했지만 건너뜀 | "건너뛰었어요. 다시 요청해 주세요" | 사라짐 |

- 활성 상태 = `WAITING`·`CALLED`·`IN_PROGRESS` (`is_active: true`). 같은 반에서 학생당 1개만 만들 수 있습니다.
- 처리 순서는 요청한 순서(서버가 정함)입니다. 순번(`position`)은 `WAITING`일 때만 오고, 1부터 시작합니다.

### 1.2 API

```http
# 학생 (그 반에 배정된 학생)
POST /api/v1/academies/{academy_id}/help-requests                     { class_id, note?, artwork_id? }
GET  /api/v1/academies/{academy_id}/help-requests/me?active=true       내 요청 목록
GET  /api/v1/academies/{academy_id}/help-requests/me/{id}              내 요청 상태 (폴링)
POST /api/v1/academies/{academy_id}/help-requests/me/{id}/cancel       취소 (WAITING·CALLED)
GET  /api/v1/academies/{academy_id}/classes/{class_id}/help-queue/estimate   지금 요청하면 예상 대기시간

# 강사 (그 반 담당 강사 또는 OWNER/MANAGER)
GET  /api/v1/academies/{academy_id}/classes/{class_id}/help-queue            반 대기열 (폴링)
POST /api/v1/academies/{academy_id}/classes/{class_id}/help-queue/call-next  다음 학생 호출
POST /api/v1/academies/{academy_id}/help-requests/{id}/{action}
     action = call | start | complete | skip | requeue | cancel
```

| action | 허용 상태 → 결과 | 버튼 예 |
| --- | --- | --- |
| `call` | WAITING → CALLED | 특정 학생 호출 |
| `start` | WAITING·CALLED → IN_PROGRESS | 질문 시작 |
| `complete` | CALLED·IN_PROGRESS → COMPLETED | 완료 |
| `skip` | WAITING·CALLED → SKIPPED | 건너뛰기 (자리에 없음) |
| `requeue` | CALLED → WAITING | 호출 취소 (원래 순번으로 복귀) |
| `cancel` | WAITING·CALLED·IN_PROGRESS → CANCELLED | 요청 취소 |

- 여러 강사가 같은 반을 담당해도 `call-next`는 **서로 다른 학생**을 호출합니다. 다른 강사가 먼저 처리한 요청에 같은 동작을 하면 409 `HELP_REQUEST_INVALID_STATE`가 오니, 대기열을 새로고침하세요.

### 1.3 요청·응답 예시

```json
// POST /help-requests (학생)
{ "class_id": "6f0c…", "note": "명암 단계가 헷갈려요", "artwork_id": "a9d1…" }

// 201 / GET /help-requests/me/{id}
{
  "id": "h1…", "class_id": "6f0c…", "class_name": "예고 입시 A반",
  "status": "WAITING", "note": "명암 단계가 헷갈려요", "artwork_id": "a9d1…",
  "requested_at": "2026-11-04T07:10:00Z", "called_at": null, "started_at": null,
  "completed_at": null, "closed_at": null,
  "position": 3,                         // 대기 순번 (WAITING일 때만)
  "called_by_name": null, "handled_by_name": null,
  "is_active": true,
  "estimate": {                          // WAITING일 때만
    "estimated_wait_seconds": 240,
    "ahead_count": 4,                    // 내 앞 대기 2명 + 처리 중 2명
    "active_handlers": 2,                // 이 반 담당 강사 수
    "average_handle_seconds": 120,
    "sample_size": 12,
    "source": "RECENT_AVERAGE",          // 또는 DEFAULT
    "is_default": false
  },
  "server_time": "2026-11-04T07:12:30Z"
}

// GET /classes/{class_id}/help-queue (강사)
{
  "class_id": "6f0c…", "class_name": "예고 입시 A반", "server_time": "…",
  "waiting_count": 3, "active_count": 1,
  "active":  [ { "id": "…", "status": "IN_PROGRESS", "student": { "display_name": "이학생", … },
                 "handled_by_name": "김강사", "waiting_seconds": 420, … } ],
  "waiting": [ { "id": "…", "status": "WAITING", "position": 1, "note": "…",
                 "student": { "membership_id": "c9e1…", "display_name": "최학생", … },
                 "waiting_seconds": 95, … } ],
  "estimate_for_new_request": { …WaitEstimate… },
  "last_changed_at": "2026-11-04T07:12:01Z",   // 대기열 마지막 변경
  "recommended_poll_seconds": 5
}
```

### 1.4 폴링 권장값

v0.5는 실시간 연결 없이 **REST 폴링**을 씁니다.

| 화면 | 주기 | 비고 |
| --- | --- | --- |
| 강사 대기열 | **5초** (`recommended_poll_seconds`) | `last_changed_at`이 이전과 같으면 목록을 다시 그리지 않아도 됩니다 |
| 학생 내 요청 (WAITING) | **10초** | 순번·예상 시간 갱신 |
| 학생 내 요청 (CALLED·IN_PROGRESS) | **5초** | 호출 알림을 빨리 보여주기 위해 |
| 요청 없음·종료 | 폴링 중지 | |

- 탭이 숨겨지면(`document.visibilityState === 'hidden'`) 폴링을 멈추고, 돌아오면 즉시 한 번 조회하세요.
- 오류(5xx·네트워크)가 나면 간격을 2배씩(최대 60초) 늘리세요.
- 이후 버전에서 SSE/WebSocket을 붙여도 응답 형식은 같게 유지할 예정입니다. 상태 변경 이벤트(`help_queue_events`)를 서버가 이미 기록하고 있습니다.

```js
function useHelpRequestPolling(academyId, requestId) {
  const [req, setReq] = useState(null)
  useEffect(() => {
    let timer, delay = 10_000, stopped = false
    const tick = async () => {
      if (document.visibilityState === 'visible') {
        try {
          const data = await api(`/academies/${academyId}/help-requests/me/${requestId}`)
          setReq(data); delay = data.status === 'WAITING' ? 10_000 : 5_000
          if (!data.is_active) stopped = true
        } catch { delay = Math.min(delay * 2, 60_000) }
      }
      if (!stopped) timer = setTimeout(tick, delay)
    }
    tick()
    const onVisible = () => document.visibilityState === 'visible' && (clearTimeout(timer), tick())
    document.addEventListener('visibilitychange', onVisible)
    return () => { stopped = true; clearTimeout(timer); document.removeEventListener('visibilitychange', onVisible) }
  }, [academyId, requestId])
  return req
}
```

### 1.5 예상 대기시간 표시

- 계산식: `ahead_count × average_handle_seconds ÷ active_handlers`. `ahead_count` = 내 앞에서 기다리는 인원 + 지금 호출·처리 중인 인원입니다.
- `average_handle_seconds`: 이 반에서 최근 30일 동안 완료된 질문(최대 20건)의 평균 처리시간(시작 또는 호출 시각부터 완료까지)입니다.
- 완료 기록이 3건 미만이면 기본값 180초를 쓰고 `source: "DEFAULT"`, `is_default: true`로 표시됩니다.
- **항상 추정치입니다.** 표시 예:
  - `is_default: false` → "약 4분 예상"
  - `is_default: true` → "약 6분 예상 (기록이 적어 대략적인 시간이에요)"
  - `estimated_wait_seconds == 0` → "곧 차례예요"
- 분 단위로 올림하고(`Math.ceil(s / 60)`), 1분 미만이면 "1분 이내"로 보여주세요. 초 단위 카운트다운은 하지 마세요(실제와 차이가 커집니다).

## 2. 피드백 녹음

### 2.1 흐름

```text
1. 녹음 동의 확인   GET  /recording-consents/me  → is_valid=false면 동의 화면
2. 동의 저장       POST /recording-consents      { policy_version, agreed: true, granted_by }
3. 녹음            MediaRecorder (브라우저)
4. 업로드 요청      POST /artworks/{artwork_id}/recordings   → { recording, upload: {bucket, path, token} }
5. Storage 업로드   supabase.storage.from(bucket).uploadToSignedUrl(path, token, blob)
6. 완료 처리       POST /artworks/{artwork_id}/recordings/{recording_id}/complete
7. 재생            GET  /artworks/{artwork_id}/recordings/{recording_id}/url  → <audio src>
```

업로드·완료·만료(기본 1시간)·재시도 규칙은 v0.4 작품 사진과 같습니다(v0.4 문서 §3).

### 2.2 API

```http
# 녹음 동의 (학생 계정)
GET    /api/v1/recording-consents/me
POST   /api/v1/recording-consents
DELETE /api/v1/recording-consents/me                       동의 철회

# 학생 (본인 작품, 학원 미소속 개인 작품도 가능)
POST   /api/v1/artworks/{artwork_id}/recordings            업로드 요청
POST   /api/v1/artworks/{artwork_id}/recordings/{id}/complete
GET    /api/v1/artworks/{artwork_id}/recordings?include_urls=true
GET    /api/v1/artworks/{artwork_id}/recordings/{id}
GET    /api/v1/artworks/{artwork_id}/recordings/{id}/url
DELETE /api/v1/artworks/{artwork_id}/recordings/{id}

# 강사 (담당 학생의 학원 연결 작품만, 읽기 전용)
GET    /api/v1/academies/{academy_id}/artworks/{artwork_id}/recordings?include_urls=true
GET    /api/v1/academies/{academy_id}/artworks/{artwork_id}/recordings/{id}
GET    /api/v1/academies/{academy_id}/artworks/{artwork_id}/recordings/{id}/url
```

- 학생 개인 작품(학원 미연결)의 녹음은 강사·원장에게 보이지 않습니다(404). 비담당 학생의 녹음은 403입니다.
- 작품을 삭제하면 그 작품의 녹음도 함께 삭제됩니다.

### 2.3 요청·응답 예시

```json
// GET /recording-consents/me
{ "required_version": "2026-11-v1", "is_valid": false, "consent": null }

// POST /recording-consents
{ "policy_version": "2026-11-v1", "agreed": true, "granted_by": "SELF" }   // 만 14세 미만: "GUARDIAN"
// → 201 { "required_version": "2026-11-v1", "is_valid": true,
//         "consent": { "id": "…", "consent_type": "VOICE_RECORDING", "policy_version": "2026-11-v1",
//                      "granted_by": "SELF", "granted_at": "…", "revoked_at": null } }

// POST /artworks/{artwork_id}/recordings
{
  "content_type": "audio/webm;codecs=opus",   // MediaRecorder.mimeType 그대로
  "file_size": 482113,
  "duration_ms": 95400,                       // 녹음 길이 (직접 측정)
  "file_name": "feedback.webm",               // 확장자 검증용 (선택)
  "title": "11/4 명암 첨삭",                   // 선택
  "recorded_at": "2026-11-04T16:30:00+09:00", // 선택
  "speaker_notice_confirmed": true            // 강사에게 녹음 사실을 알림 (필수, true만)
}
// → 201
{
  "recording": {
    "id": "r1…", "artwork_id": "a9d1…", "title": "11/4 명암 첨삭", "status": "PENDING",
    "content_type": "audio/webm", "size_bytes": null, "duration_ms": 95400,
    "recorded_at": "2026-11-04T07:30:00Z", "uploaded_at": null, "created_at": "…",
    "consent_id": "…", "speaker_notice_confirmed": true,
    "transcription_status": "NOT_REQUESTED", "url": null, "url_expires_at": null
  },
  "upload": { "bucket": "feedback-audio", "path": "<user>/<artwork>/<recording>.webm",
              "url": "https://…/object/upload/sign/…", "token": "…", "expires_at": "…" }
}
```

- `transcription_status`는 v0.6 STT용입니다(`NOT_REQUESTED` → `PENDING` → `PROCESSING` → `COMPLETED`/`FAILED`). v0.5에서는 항상 `NOT_REQUESTED`입니다.

### 2.4 MediaRecorder 연동 시 주의사항

```js
const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? ''

const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64_000 })
const chunks = []
let startedAt
recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
recorder.onstart = () => { startedAt = performance.now() }
recorder.onstop = async () => {
  stream.getTracks().forEach((t) => t.stop())            // 마이크 표시등 끄기
  const blob = new Blob(chunks, { type: recorder.mimeType })
  const durationMs = Math.round(performance.now() - startedAt)
  await uploadRecording(artworkId, blob, recorder.mimeType, durationMs)
}
recorder.start(1000)   // 1초마다 청크 (긴 녹음에서 메모리·유실 방지)
```

- **형식**: Chrome·Edge는 `audio/webm`, Firefox는 `audio/ogg` 또는 `audio/webm`, **Safari(iOS 포함)는 `audio/mp4`** 입니다. `isTypeSupported`로 고르고 `recorder.mimeType`을 그대로 `content_type`으로 보내세요. 서버가 `;codecs=` 부분을 정리합니다.
- **길이(duration_ms)**: WebM 파일에는 길이 정보가 없는 경우가 많아 `<audio>.duration`이 `Infinity`로 나올 수 있습니다. 위 코드처럼 시작·종료 시각으로 직접 재서 보내세요. 일시정지(`pause/resume`)를 쓴다면 일시정지 시간은 빼야 합니다. 서버는 범위(최대 20분)만 검증하고, WAV는 헤더로 다시 계산합니다.
- **제한(서버 설정)**: 최대 25MB, 20분, 작품당 20개. 64kbps opus면 20분에 약 10MB입니다.
- **HTTPS 필수**: `getUserMedia`는 HTTPS 또는 `localhost`에서만 동작합니다. 마이크 권한 거부(`NotAllowedError`)는 안내 화면으로 처리하세요.
- **iOS Safari**: 사용자 동작(버튼 클릭) 안에서 `getUserMedia`를 호출해야 합니다. 화면이 꺼지거나 앱이 백그라운드로 가면 녹음이 멈출 수 있으니 녹음 중 안내를 표시하세요.
- **업로드 실패 대비**: 업로드 완료 전에는 `Blob`을 메모리(또는 IndexedDB)에 보관하고, 실패하면 업로드 요청부터 다시 하세요. 완료 처리는 여러 번 호출해도 안전합니다.
- 같은 파일을 같은 작품에 다시 올리면 409 `DUPLICATE_RECORDING`입니다.

### 2.5 재생

```jsx
function RecordingPlayer({ artworkId, recording }) {
  const [src, setSrc] = useState(recording.url)
  const load = async () => {
    const { url } = await api(`/artworks/${artworkId}/recordings/${recording.id}/url`)
    setSrc(url)
  }
  useEffect(() => { if (!src) load() }, [])
  return <audio controls preload="metadata" src={src ?? undefined} onError={load} />
}
```

- Signed URL은 기본 5분 뒤 만료됩니다. 재생 중 만료돼도 이미 받은 부분은 재생되지만, 탐색(seek)하다 `onError`가 나면 URL을 다시 받으세요.
- 강사는 `/academies/{academy_id}/artworks/{artwork_id}/recordings/{id}/url`을 사용합니다.
- 재생 시간 표시는 `duration_ms`를 쓰세요(WebM은 `<audio>.duration`이 정확하지 않을 수 있음).

### 2.6 녹음 동의 UI 요구사항

1. **녹음 전 동의 화면 필수**: `GET /recording-consents/me`의 `is_valid`가 false면 녹음 버튼 대신 동의 화면을 보여줍니다.
2. 동의 화면에 표시할 내용(동의서 버전 `required_version`과 함께):
   - 수집 항목: 피드백 음성 녹음 파일, 녹음 길이·시각
   - 목적: 학생 본인의 첨삭 내용 복습, 담당 강사의 첨삭 확인(학원 연결 작품만)
   - 보관: 학생이 삭제하거나 작품을 삭제할 때까지 (보존 기간 정책 확정 시 갱신)
   - 공개 범위: 본인, 학원 연결 작품은 담당 강사·학원 관리자. 개인 작품 녹음은 본인만
   - 이후 버전 안내: 음성 텍스트 변환(STT)은 별도 고지 후 적용 예정
   - 동의 철회 방법: 설정 화면에서 언제든 철회 가능(철회 후 새 녹음 불가)
3. "동의합니다" 체크박스는 **기본 해제 상태**여야 하고, 체크한 경우에만 `agreed: true`로 저장합니다.
4. **만 14세 미만**: 법정대리인(보호자) 동의를 받은 뒤 `granted_by: "GUARDIAN"`으로 저장합니다(개인정보 보호법 제22조의2). 보호자 확인 절차는 학원 정책에 맞춰 화면에서 안내합니다.
5. **녹음 시작 직전 확인**: "강사님께 녹음한다고 말씀드렸나요?" 확인 후 `speaker_notice_confirmed: true`로 보냅니다. 강사 목소리가 함께 녹음되기 때문입니다.
6. 녹음 중에는 빨간 표시와 경과 시간을 항상 보여주세요.
7. `required_version`이 바뀌면(서버 설정) 기존 동의가 무효가 되어 `is_valid: false`가 됩니다. 새 동의를 받으세요.

## 3. 오류 코드

| HTTP | code | 상황 | 프론트 처리 |
| --- | --- | --- | --- |
| 409 | `HELP_REQUEST_ALREADY_ACTIVE` | 같은 반에 진행 중인 요청 있음 (`details.help_request_id`) | 기존 요청 화면으로 이동 |
| 409 | `HELP_REQUEST_INVALID_STATE` | 허용되지 않는 전이 (다른 강사가 먼저 처리 등, `details.status`) | 대기열 새로고침 |
| 409 | `HELP_QUEUE_EMPTY` | 다음 학생 호출 시 대기자 없음 | "대기 중인 학생이 없어요" |
| 404 | `NOT_FOUND` | 배정되지 않은 반, 남의 요청·녹음, 다른 학원 | "찾을 수 없음" |
| 403 | `FORBIDDEN` | 담당 아닌 반·학생, 학생의 강사 API 호출, 강사의 학생 API 호출 | 버튼 숨김 |
| 409 | `CLASS_ARCHIVED` | 종료된 반에 질문 요청 | 안내 |
| 422 | `INVALID_ARTWORK_LINK` | 남의 작품을 질문에 연결 | 작품 다시 선택 |
| 409 | `RECORDING_CONSENT_REQUIRED` | 현재 버전 동의 없음 (`details.required_version`) | 동의 화면 |
| 422 | `VALIDATION_ERROR` | 동의 버전 불일치(`details.required_version`), `agreed`·`speaker_notice_confirmed` 누락 | 화면 갱신 |
| 422 | `UNSUPPORTED_FILE_TYPE` | 허용하지 않는 형식·확장자 | 형식 안내 |
| 422 | `FILE_TOO_LARGE` | 25MB 초과 | 짧게 나눠 녹음 |
| 422 | `AUDIO_TOO_LONG` | 20분 초과 | 짧게 나눠 녹음 |
| 422 | `INVALID_AUDIO` | 실제 오디오가 아님, 선언 형식과 다름 | 다시 녹음 |
| 409 | `DUPLICATE_RECORDING` | 같은 작품에 같은 파일 (`details.recording_id`) | "이미 올린 녹음" |
| 409 | `RECORDING_LIMIT_REACHED` | 작품당 20개 초과 | 기존 녹음 삭제 유도 |
| 409 | `UPLOAD_NOT_FOUND` / `UPLOAD_EXPIRED` | 완료 처리 시 파일 없음 / 업로드 요청 만료 | 업로드 재시도 / 처음부터 |
| 409 | `RECORDING_NOT_ACTIVE` | 완료 전 녹음 재생 URL 요청 | 완료 처리 먼저 |
| 503 | `STORAGE_UNAVAILABLE` / `STORAGE_NOT_CONFIGURED` | Storage 장애 / 서버 설정 누락 | 재시도 / 백엔드 문의 |

## 4. 화면별 API

| 화면 | 사용자 | API |
| --- | --- | --- |
| 수업 중 질문 버튼 | 학생 | `GET …/help-queue/estimate` (버튼 옆 예상 시간), `POST /help-requests` |
| 내 질문 상태 카드 | 학생 | `GET /help-requests/me?active=true` → `GET /help-requests/me/{id}` 폴링, `POST …/cancel` |
| 질문 대기열 | 강사 | `GET /classes/{class_id}/help-queue` 5초 폴링, `POST …/call-next`, `POST /help-requests/{id}/{action}` |
| 녹음 동의 | 학생 | `GET/POST/DELETE /recording-consents…` |
| 작품 상세 녹음 탭 | 학생 | `GET /artworks/{id}/recordings?include_urls=true`, 녹음 업로드 §2.1, `DELETE` |
| 학생 작품 녹음 듣기 | 강사 | `GET /academies/{id}/artworks/{artwork_id}/recordings?include_urls=true` |
