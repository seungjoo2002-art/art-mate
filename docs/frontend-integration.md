# 프론트엔드 연동 가이드 (v0.2 인증·사용자·학원)

> 대상: 프론트엔드 개발자 · 기준 버전: v0.2 · API 문서(개발 서버): http://127.0.0.1:8000/docs
>
> **v0.3 학원 운영 API(출석·일정·과제·개인 할 일·대시보드)는 [frontend-integration-v0.3.md](frontend-integration-v0.3.md)를 보세요.**

## 1. 인증 구조 한눈에 보기

```text
 [React]                                  [Supabase Auth]            [ART MATE API]
  회원가입/로그인/로그아웃/비번재설정 ───▶  계정·비밀번호·이메일 관리
                          ◀── session (access_token, refresh_token)
  API 호출 ── Authorization: Bearer <access_token> ─────────────────▶  JWT 검증(JWKS 공개키)
                                                                       → profiles / 학원 권한 확인
```

- **회원가입·로그인·로그아웃·토큰 갱신·비밀번호 재설정은 전부 Supabase Auth SDK로 처리**합니다.
  ART MATE API에는 로그인/회원가입 엔드포인트가 없습니다 (인증 로직 중복 방지).
- API는 access token만 검증합니다. 사용자 식별은 **토큰의 `sub`** 으로만 하며, 요청 본문의 `user_id` 같은 값은 받지 않습니다.
- 서비스 정보(이름, 사용자 유형, 학원 소속)는 ART MATE API의 `profiles`·학원 테이블에 있습니다. 이메일·비밀번호는 Supabase에만 있습니다.

## 2. 환경변수 (frontend/.env.local)

```env
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon(publishable) key>
VITE_API_BASE_URL=http://127.0.0.1:8000
```

- 값은 Supabase 대시보드 → **Project Settings → API** 에서 확인합니다.
- anon(publishable) 키는 브라우저에 노출되도록 설계된 공개 키입니다.
- **`service_role`(secret) 키는 절대 프론트엔드·저장소에 넣지 않습니다.** (모든 보안 규칙을 우회하는 키)
- `.env.local`은 Git에 커밋하지 않습니다 (Vite 기본 `.gitignore`의 `*.local`로 제외됨).
- 백엔드 `CORS_ORIGINS`에 프론트 주소(`http://localhost:5173`)가 들어 있어야 합니다 (기본값에 포함).

### Supabase 대시보드 설정 (한 번만)

| 위치 | 설정 |
| --- | --- |
| Authentication → Sign In / Providers → Email | Email 활성화, **Confirm email 켜기** 권장 |
| Authentication → URL Configuration | Site URL: `http://localhost:5173` (운영 배포 시 운영 주소로 변경), Redirect URLs에 `http://localhost:5173/**` 추가 |
| Authentication → Sign In / Providers | **Anonymous sign-ins 끄기** (API가 익명 사용자 토큰을 거부함) |

## 3. Supabase 클라이언트

```bash
cd frontend
npm install @supabase/supabase-js
```

```js
// src/lib/supabase.js
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)
```

## 4. API 호출 도우미 (토큰 전달 · 만료 처리)

```js
// src/lib/api.js
import { supabase } from './supabase'

const BASE = `${import.meta.env.VITE_API_BASE_URL}/api/v1`

export class ApiError extends Error {
  constructor(status, error) {
    super(error?.message ?? `HTTP ${status}`)
    this.status = status
    this.code = error?.code          // ← 화면 분기는 code로 (message는 바뀔 수 있음)
    this.details = error?.details
    this.requestId = error?.request_id
  }
}

async function accessToken() {
  const { data } = await supabase.auth.getSession()   // SDK가 만료 전에 자동 갱신
  return data.session?.access_token ?? null
}

export async function api(path, { method = 'GET', body, retry = true } = {}) {
  const token = await accessToken()
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (res.status === 204) return null
  const json = await res.json().catch(() => null)
  if (res.ok) return json

  const error = json?.error
  // access token 만료: 한 번만 갱신 후 재시도
  if (res.status === 401 && error?.code === 'TOKEN_EXPIRED' && retry) {
    const { error: refreshError } = await supabase.auth.refreshSession()
    if (!refreshError) return api(path, { method, body, retry: false })
  }
  if (res.status === 401) await supabase.auth.signOut()   // 무효 토큰 → 로그인 화면으로
  throw new ApiError(res.status, error)
}
```

> access token 기본 유효시간은 1시간입니다. 로그아웃(`signOut`) 후에도 이미 발급된 access token은 만료 전까지 유효할 수 있으므로, 클라이언트는 로그아웃 시 저장된 세션을 반드시 지웁니다 (SDK가 처리).

## 5. 화면 흐름

### 5.1 회원가입 → 프로필 생성 (온보딩)

```js
// 1) Supabase 계정 생성
const { error } = await supabase.auth.signUp({
  email, password,
  options: { emailRedirectTo: `${location.origin}/auth/callback` },
})
// Confirm email이 켜져 있으면 메일 인증 후 로그인 상태가 된다.

// 2) 로그인 상태가 되면 프로필 확인
try {
  const me = await api('/users/me')            // 200 → 홈으로
} catch (e) {
  if (e.code === 'PROFILE_NOT_FOUND') {
    // 3) 온보딩 화면: 이름 + 사용자 유형(학생/강사) 입력
    await api('/users/me', {
      method: 'POST',
      body: { display_name: '김학생', user_type: 'STUDENT' },   // 'STUDENT' | 'INSTRUCTOR'
    })
  }
}
```

- `POST /users/me`는 **멱등**입니다. 네트워크 오류로 실패했으면 그냥 다시 호출하면 됩니다 (이미 있으면 200 + 기존 프로필, 값은 바뀌지 않음).
- 로그인할 때마다 `GET /users/me` → `PROFILE_NOT_FOUND`면 온보딩으로 보내면, 가입 도중 이탈한 사용자도 자연스럽게 복구됩니다.
- 사용자 유형 선택지는 **학생 / 강사 두 가지뿐**입니다. 관리자(ADMIN)는 API로 만들 수 없습니다.
- 가입 후 사용자 유형은 변경할 수 없습니다 (v0.2). 잘못 선택한 경우 운영자 문의로 처리합니다.

### 5.2 로그인 / 로그아웃 / 로그인 상태

```js
await supabase.auth.signInWithPassword({ email, password })   // 로그인
await supabase.auth.signOut()                                   // 로그아웃

// 로그인 상태 구독 (앱 시작 시 1회)
supabase.auth.onAuthStateChange((event, session) => {
  // SIGNED_IN, SIGNED_OUT, TOKEN_REFRESHED, PASSWORD_RECOVERY ...
})
```

"로그인 상태 확인" = Supabase 세션 존재 + `GET /users/me` 200.

### 5.3 비밀번호 재설정

```js
// 1) 재설정 메일 요청 (계정 존재 여부와 관계없이 같은 안내 문구를 보여 주세요)
await supabase.auth.resetPasswordForEmail(email, {
  redirectTo: `${location.origin}/reset-password`,
})

// 2) /reset-password 페이지: 메일 링크로 들어오면 PASSWORD_RECOVERY 이벤트 발생
supabase.auth.onAuthStateChange(async (event) => {
  if (event === 'PASSWORD_RECOVERY') {
    await supabase.auth.updateUser({ password: newPassword })
  }
})
```

## 6. 권한별 화면 접근 기준

### 6.1 사용자 유형 (`GET /users/me` → `user_type`)

| 화면 | STUDENT | INSTRUCTOR | ADMIN |
| --- | --- | --- | --- |
| 내 프로필 | ✅ | ✅ | ✅ |
| 학원 찾기·가입 요청 | ✅ | ✅ | ❌ |
| 학원 등록 신청 | ❌ | ✅ | ❌ |
| 학원 등록 심사 (`/admin/...`) | ❌ | ❌ | ✅ |

### 6.2 학원 내 역할 (`GET /academies?mine=true` → `my_role`, 또는 학원 상세의 `my_membership.role`)

| 화면 | STUDENT | INSTRUCTOR | MANAGER | OWNER |
| --- | --- | --- | --- | --- |
| 학원 정보 | ✅ | ✅ | ✅ | ✅ |
| 멤버 목록 | ❌ | ✅ | ✅ | ✅ |
| 가입 요청 승인·거절 | ❌ | ❌ | ✅ | ✅ |
| 멤버 내보내기 | ❌ | ❌ | ✅ (OWNER·MANAGER 제외) | ✅ |
| MANAGER 지정/해제 | ❌ | ❌ | ❌ | ✅ |
| 학원 탈퇴 | ✅ | ✅ | ✅ | ❌ (OWNER는 탈퇴 불가) |

> 화면 숨김은 UX일 뿐이고, 실제 권한은 서버가 모든 요청에서 다시 검사합니다.
> 학원 상태가 `PENDING_APPROVAL`이면 OWNER에게 "승인 대기 중" 안내를 보여 주세요 (가입 요청 받기 불가).

## 7. API 요청·응답 예시

모든 보호 API는 `Authorization: Bearer <access_token>` 헤더가 필요합니다. 시각은 UTC ISO 8601, ID는 UUID 문자열입니다.

### 프로필

```http
GET /api/v1/users/me
```
```json
{
  "id": "2b1f9f3e-7a43-4d2c-9a55-3c7e0a6d1f10",
  "display_name": "김학생",
  "user_type": "STUDENT",
  "avatar_path": null,
  "is_active": true,
  "created_at": "2026-11-03T08:00:00Z",
  "updated_at": "2026-11-03T08:00:00Z",
  "email": "student@example.com"
}
```

```http
POST /api/v1/users/me          → 201 (생성) / 200 (이미 있음)
{ "display_name": "김학생", "user_type": "STUDENT" }

PATCH /api/v1/users/me         → 200
{ "display_name": "김미술", "avatar_path": "avatars/<내 user id>/profile.png" }
```

- 수정 가능한 필드: `display_name`(1~50자), `avatar_path`(null이면 삭제). 다른 필드를 보내면 422.
- `avatar_path`는 Storage 경로이며 `avatars/<본인 id>/<파일명>` 형식만 허용됩니다 (이미지 업로드 자체는 v0.3).

### 학원

```http
POST /api/v1/academies                     (강사) → 201
{ "name": "아트메이트 미술학원", "description": "예고 입시 전문" }
```
```json
{
  "id": "6f0c…", "name": "아트메이트 미술학원", "description": "예고 입시 전문",
  "status": "PENDING_APPROVAL", "created_at": "…",
  "my_membership": { "id": "…", "role": "OWNER", "status": "ACTIVE", "joined_at": "…" }
}
```

```http
GET /api/v1/academies?q=아트&limit=20&offset=0     학원 찾기 (승인된 학원만)
GET /api/v1/academies?mine=true                    내 학원 (+ my_role)
GET /api/v1/academies/{academy_id}                 학원 상세 (+ my_membership)
```
```json
{
  "items": [
    { "id": "6f0c…", "name": "아트메이트 미술학원", "description": "…",
      "status": "ACTIVE", "created_at": "…", "my_role": "OWNER" }
  ],
  "total": 1, "limit": 20, "offset": 0
}
```

### 가입 요청 · 승인

```http
POST /api/v1/academies/{academy_id}/join-requests          (학생·강사) → 201
{ "message": "예고 입시반 등록 희망합니다" }
```
```json
{ "id": "a1…", "academy_id": "6f0c…", "user_id": "2b1f…", "requested_role": "STUDENT",
  "status": "PENDING", "message": "예고 입시반 등록 희망합니다",
  "review_note": null, "reviewed_at": null, "created_at": "…" }
```

```http
GET /api/v1/users/me/join-requests                          내 요청 상태 (+ academy_name)
GET /api/v1/academies/{academy_id}/join-requests?status=PENDING      (OWNER/MANAGER)
```
```json
{ "items": [ { "id": "a1…", "requested_role": "STUDENT", "status": "PENDING", "…": "…",
               "applicant": { "display_name": "김학생", "avatar_path": null } } ],
  "total": 1, "limit": 20, "offset": 0 }
```

```http
PATCH /api/v1/academies/{academy_id}/join-requests/{request_id}     (OWNER/MANAGER) → 200
{ "decision": "APPROVE" }                       또는  { "decision": "REJECT", "note": "정원 마감" }
```

### 멤버

```http
GET    /api/v1/academies/{academy_id}/members?role=STUDENT&status=ACTIVE   (OWNER/MANAGER/INSTRUCTOR)
PATCH  /api/v1/academies/{academy_id}/members/{membership_id}              (OWNER) { "role": "MANAGER" | "INSTRUCTOR" }
DELETE /api/v1/academies/{academy_id}/members/{membership_id}              (OWNER/MANAGER) → 204
DELETE /api/v1/academies/{academy_id}/members/me                           (본인 탈퇴) → 204
```
```json
{ "items": [ { "id": "<membership id>", "user_id": "…", "display_name": "김학생", "avatar_path": null,
               "role": "STUDENT", "status": "ACTIVE", "joined_at": "…", "left_at": null } ],
  "total": 1, "limit": 20, "offset": 0 }
```

### 시스템 관리자

```http
GET   /api/v1/admin/academies?status=PENDING_APPROVAL
PATCH /api/v1/admin/academies/{academy_id}    { "decision": "APPROVE" | "REJECT", "note": "…" }
```

## 8. 오류 응답과 처리

모든 오류는 같은 형식입니다. **화면 분기는 `error.code`로** 하세요.

```json
{ "error": { "code": "JOIN_REQUEST_ALREADY_PENDING", "message": "A join request is already pending",
             "details": null, "request_id": "9ebf70ea…" } }
```

| HTTP | code | 의미 | 프론트 처리 |
| --- | --- | --- | --- |
| 401 | `UNAUTHORIZED` | 토큰 없음 | 로그인 화면 |
| 401 | `TOKEN_EXPIRED` | access token 만료 | `refreshSession()` 후 1회 재시도 (§4) |
| 401 | `INVALID_TOKEN` | 위조·다른 프로젝트·익명 토큰 | 로그아웃 → 로그인 화면 |
| 401 | `AUTH_NOT_CONFIGURED` | 서버 설정 누락 (`SUPABASE_URL`) | 백엔드 담당자에게 문의 |
| 403 | `PROFILE_REQUIRED` | 프로필 미생성 | 온보딩 화면 |
| 403 | `ACCOUNT_DISABLED` | 비활성 계정 | 안내 화면 (기능 차단) |
| 403 | `FORBIDDEN` | 역할 권한 없음 | 버튼 숨김/안내 |
| 404 | `PROFILE_NOT_FOUND` | `GET /users/me`: 프로필 없음 | 온보딩 화면 |
| 404 | `NOT_FOUND` | 없음 또는 접근 권한 없는 학원 | "찾을 수 없음" |
| 409 | `ALREADY_MEMBER` | 이미 소속 | 학원 화면으로 이동 |
| 409 | `JOIN_REQUEST_ALREADY_PENDING` | 대기 중 요청 있음 | "승인 대기 중" 표시 |
| 409 | `JOIN_REQUEST_ALREADY_REVIEWED` | 다른 관리자가 이미 처리 | 목록 새로고침 |
| 409 | `ACADEMY_NOT_ACCEPTING_MEMBERS` | 학원이 승인 전·정지 | 안내 |
| 409 | `ACADEMY_ALREADY_REVIEWED` | (ADMIN) 이미 심사됨 | 목록 새로고침 |
| 409 | `ACADEMY_APPLICATION_LIMIT` | 승인 대기 학원 3개 초과 | 안내 |
| 409 | `OWNER_CANNOT_LEAVE` | OWNER 탈퇴 시도 | 안내 |
| 409 | `MEMBER_ROLE_NOT_CHANGEABLE` | 강사가 아닌 멤버의 역할 변경 | 안내 |
| 409 | `APPLICANT_INACTIVE` | 신청자 계정 비활성 | 거절 처리 권장 |
| 422 | `VALIDATION_ERROR` | 입력값 오류 (`details[].field`, `message`) | 입력 폼에 표시 |
| 503 | `DATABASE_UNAVAILABLE`, `AUTH_PROVIDER_UNAVAILABLE` | 일시 장애 | 잠시 후 재시도 |

- 문의·버그 리포트에는 `request_id`(응답 헤더 `X-Request-ID`)를 함께 보내 주세요.
- 목록 API 공통: `limit`(1~100, 기본 20), `offset`(기본 0), 응답 `{items, total, limit, offset}`.

## 9. 로컬에서 함께 실행하기

```bash
# 백엔드 (backend/.env 에 DATABASE_URL, SUPABASE_URL 설정 필요)
cd backend && uv run uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs

# 프론트엔드
cd frontend && npm run dev                               # http://localhost:5173
```

> 개발 Supabase DB에 v0.2 마이그레이션이 적용되기 전까지는 프로필·학원 API가 500/503을 반환할 수 있습니다. 적용 여부는 백엔드 담당자에게 확인하세요.
