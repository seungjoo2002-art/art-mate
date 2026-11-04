# ART MATE 백엔드 아키텍처

> 대상 버전: v0.2 (인증·사용자·학원 소속) · 변경 시 이 문서를 함께 갱신합니다.

## 1. 전체 구성

```text
 ┌──────────────┐  Supabase Auth 로그인   ┌──────────────────────────┐
 │ Web Frontend │ ──────────────────────▶ │ Supabase                 │
 │ (Vite :5173) │ ◀── access token(JWT) ─ │  - Auth (auth.users)     │
 └──────┬───────┘                         │  - PostgreSQL            │
        │ HTTPS  Authorization: Bearer    │  - Storage (작품/음성)    │
        ▼                                 └──────▲─────────▲─────────┘
 ┌──────────────────────────────────────┐        │ asyncpg │ JWKS / signed URL
 │ ART MATE API (FastAPI, Render)       │────────┘         │
 │  api → services → repositories → db  │──────────────────┘
 │            └→ integrations ──────────┼──▶ STT API, LLM API (향후)
 └──────────────────────────────────────┘
```

- 클라이언트는 **Supabase Auth로 직접 로그인**하고, 받은 access token을 API에 Bearer로 전달합니다.
- API 서버는 토큰을 검증하고, 학원 소속·역할은 **우리 DB**에서 확인합니다.
- 이미지·음성 파일은 **Supabase Storage**에 저장하고 DB에는 경로(object key)와 메타데이터만 저장합니다.
- AI(STT/LLM)는 백엔드만 호출합니다. 프론트엔드에 AI API 키를 두지 않습니다.

## 2. 레이어별 책임

| 레이어 | 위치 | 책임 | 하지 않는 일 |
| --- | --- | --- | --- |
| API (Router) | `app/api/v1/endpoints/*.py` | HTTP 요청 파싱·검증(Pydantic), 의존성 주입(인증, 세션), 서비스 호출, 응답 스키마 반환 | 비즈니스 규칙, SQL |
| Schema | `app/schemas/` | 요청/응답 모델, 공통 규칙(`ErrorResponse`, `Page[T]`, `PaginationParams`) | DB 접근 |
| Service | `app/services/` | 비즈니스 규칙, **학원 단위 권한 확인**, 여러 리포지토리 조합, 트랜잭션 `commit` | HTTP 객체(Request, HTTPException) 사용 |
| Repository | `app/repositories/` | `AsyncSession`으로 쿼리 수행, 엔티티 반환. **모든 조회에 academy_id 조건 포함** | 커밋 결정, 권한 판단 |
| Model | `app/models/` | SQLAlchemy ORM 매핑 | 로직 |
| Integration | `app/integrations/` | Supabase(JWKS, Storage), STT, LLM 등 외부 API 래핑 | 도메인 규칙 |
| Core | `app/core/` | 설정, 로깅, 미들웨어, 예외, 인증 의존성 | 다른 `app.*` 계층 import |
| DB | `app/db/` | Base/mixin, 엔진·세션 생성 | 도메인 쿼리 |

### 의존 방향 (순환 참조 방지)

```text
api ──▶ services ──▶ repositories ──▶ models ──▶ db.base
 │          └──────▶ integrations
 └──▶ schemas            (모든 계층) ──▶ core
```

- 아래 방향으로만 import 합니다. `core`는 어떤 `app.*` 계층도 import 하지 않습니다(`core.config`/`core.logging`/`core.exceptions` 간 참조만 허용).
- 서비스는 HTTP를 모르므로 예외는 `app.core.exceptions`의 `NotFoundError`, `ForbiddenError` 등을 던지고, 응답 변환은 공통 핸들러가 합니다.

## 3. API 요청 흐름

```text
Client
  │
  ▼ CORSMiddleware            허용 Origin 검사, 프리플라이트 처리 (가장 바깥)
  ▼ RequestContextMiddleware  X-Request-ID 발급/전파, 접근 로그, 처리 안 된 예외 → 안전한 500
  ▼ ExceptionMiddleware       AppError / 검증 오류 / HTTPException → 공통 에러 JSON
  ▼ Router (/api/v1/...)
  ▼ Dependencies              get_current_user(인증) → get_db_session(세션)
  ▼ Endpoint 함수             스키마 검증된 입력 → service 호출
  ▼ Service → Repository → AsyncSession → PostgreSQL
  ▲ Response schema (Pydantic) 직렬화
```

### 응답 규칙

| 구분 | 형식 |
| --- | --- |
| 단건 성공 | 리소스 스키마를 그대로 반환 (envelope 없음) |
| 목록 | `Page[T]` = `{ "items": [...], "total", "limit", "offset" }`, `limit` 기본 20 · 최대 100 |
| 에러 | `{ "error": { "code", "message", "details", "request_id" } }` |
| 시각 | DB `timestamptz`(UTC)로 저장, 응답은 ISO 8601 + 타임존 (`2026-11-03T05:50:09Z`) |
| ID | UUID (URL 경로·응답 모두 문자열 UUID) |
| 필드명 | snake_case |

### HTTP 상태 코드 · 에러 코드

| 상황 | Status | `error.code` | 발생 위치 |
| --- | --- | --- | --- |
| 입력 검증 실패 | 422 | `VALIDATION_ERROR` (`details`에 field/message/type, 입력값은 미포함) | Pydantic |
| 잘못된 요청(도메인) | 400 | `BAD_REQUEST` | `BadRequestError` |
| 인증 없음 | 401 | `UNAUTHORIZED` (+ `WWW-Authenticate: Bearer`) | `UnauthorizedError` |
| 토큰 무효 / 만료 | 401 | `INVALID_TOKEN` / `TOKEN_EXPIRED` | `SupabaseJWTVerifier` |
| 인증 설정 누락 | 401 | `AUTH_NOT_CONFIGURED` (`SUPABASE_URL` 미설정, fail-closed) | `get_current_user` |
| 권한 없음 | 403 | `FORBIDDEN`, `PROFILE_REQUIRED`, `ACCOUNT_DISABLED` | `ForbiddenError` |
| 리소스 없음 | 404 | `NOT_FOUND` | `NotFoundError`, 존재하지 않는 경로 |
| 허용되지 않은 메서드 | 405 | `METHOD_NOT_ALLOWED` | 라우터 |
| 중복·상태 충돌 | 409 | `CONFLICT` 및 도메인 코드 (`ALREADY_MEMBER` 등, docs/frontend-integration.md §8) | `ConflictError` |
| 서버 내부 오류 | 500 | `INTERNAL_SERVER_ERROR` (메시지 고정, 스택트레이스 미노출) | 미들웨어 |
| 일시적 불가 | 503 | `SERVICE_UNAVAILABLE`, `DATABASE_NOT_CONFIGURED`, `DATABASE_UNAVAILABLE`, `AUTH_PROVIDER_UNAVAILABLE` | `ServiceUnavailableError` 계열 |

새 도메인 에러 코드가 필요하면 `ErrorCode`에 추가합니다(예: `CALL_ALREADY_PENDING`). 프론트엔드는 `message`가 아니라 `code`로 분기합니다.

> 다른 학원의 리소스에 접근하면 **403이 아니라 404**를 반환합니다(리소스 존재 여부 노출 방지).

## 4. DB 연동 구조

- `create_app()` → lifespan 시작 시 `create_database(settings)`가 `AsyncEngine` + `async_sessionmaker`를 만들어 `app.state.database`에 보관합니다. 엔진 생성은 연결을 열지 않으므로 **DB 장애가 있어도 서버는 기동**하고 `/health`는 200을 반환합니다.
- 요청마다 `DbSession` 의존성이 세션을 열고, 요청이 끝나면 닫습니다(커밋 안 된 변경은 롤백).
- **트랜잭션 경계는 서비스 계층**: 쓰기 작업의 마지막에 서비스가 `await session.commit()`.
- 연결 풀: `pool_size=5`, `max_overflow=5`, `pool_pre_ping=True`, `pool_recycle=1800s`, 연결 타임아웃 5s (환경변수로 조정).
- Supabase pooler: transaction pooler(6543)는 prepared statement를 지원하지 않아 자동으로 asyncpg statement cache를 끕니다. 상시 실행 서버는 session pooler(5432) 사용을 권장합니다.
- DB 분리: 운영/개발/테스트는 서로 다른 `DATABASE_URL`을 사용합니다. 테스트는 `.env`를 읽지 않고 `TEST_DATABASE_URL`(테스트 전용 DB)만 사용합니다.
- 마이그레이션: Alembic(async env). 앱 기동 시 자동 적용하지 않습니다.

## 5. 인증·권한 구조

### 인증 방식 결정: 프론트엔드가 Supabase Auth SDK를 직접 사용

| 기능 | 처리 위치 |
| --- | --- |
| 회원가입·로그인·로그아웃·토큰 갱신·비밀번호 재설정·이메일 인증 | **Supabase Auth SDK (프론트엔드)** |
| access token 검증, 프로필·학원 권한 | ART MATE API |

- 백엔드가 로그인 API를 감싸면 비밀번호가 백엔드를 거치고, 토큰 갱신·이메일 인증·재설정 로직이 중복됩니다. 그래서 인증은 Supabase에 맡기고 백엔드는 **검증만** 합니다.
- 백엔드에는 service_role 키가 없습니다. Supabase Admin API(사용자 삭제 등)가 필요한 기능은 별도 배치나 운영 도구로 분리합니다.
- 프론트엔드 연동 방법: [frontend-integration.md](frontend-integration.md)

### 공개 / 보호 API 분리

| 구분 | 경로 | 인증 |
| --- | --- | --- |
| 공개 | `/`, `/health`, `/api/v1/health`, `/api/v1/health/db` | 없음 (내부 정보 미노출) |
| 보호 | 그 외 모든 `/api/v1/*` | `CurrentUser` 이상의 의존성 필수 |

`SUPABASE_URL`이 없으면 verifier가 만들어지지 않고, 보호 API는 모두 401 `AUTH_NOT_CONFIGURED`로 거부됩니다(**fail-closed**).

### Supabase JWT 검증 (`app/core/security.py`)

1. `Authorization: Bearer <access_token>` 추출 (`HTTPBearer`, 누락 시 401 `UNAUTHORIZED`)
2. 헤더 `alg`가 **ES256/RS256**이 아니면 거부합니다(`none`, HS256 알고리즘 혼동 차단). `kid`가 없어도 거부합니다.
3. `kid`로 JWKS(`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) 공개키를 찾습니다(`JWKSKeyResolver`).
   - 메모리 캐시: `AUTH_JWKS_CACHE_SECONDS`(기본 600초)
   - 모르는 `kid`이면 재조회하되 **최소 30초 간격**을 둡니다. 위조 `kid`로 Supabase를 반복 호출하게 만드는 공격을 막기 위해서입니다.
   - 조회에 실패해도 캐시가 있으면 계속 쓰고, 캐시가 없으면 503 `AUTH_PROVIDER_UNAVAILABLE`을 반환합니다.
4. `jwt.decode`로 서명과 클레임을 검증합니다.
   - **iss** = `{SUPABASE_URL}/auth/v1`, **aud** = `AUTH_JWT_AUDIENCE`(기본 `authenticated`)
   - `exp`, `iat`, `sub`, `aud`, `iss` 필수, 시계 오차 `AUTH_JWT_LEEWAY_SECONDS`(기본 10초)
   - `role == "authenticated"`이어야 하고(anon·service_role 토큰 거부), `is_anonymous == true`(익명 로그인)도 거부
   - `sub`는 UUID → `AuthenticatedUser.user_id`
5. 만료는 401 `TOKEN_EXPIRED`, 그 밖의 실패는 401 `INVALID_TOKEN`입니다. 실패 사유(예외 종류)는 서버 로그에만 남기고, 토큰 원문은 기록하지 않습니다.
6. 검증한 서울 개발 프로젝트는 ES256 비대칭 키(JWKS)를 사용합니다. 레거시 HS256 공유 시크릿 방식은 지원하지 않습니다.

> 로그아웃 후에도 이미 발급된 access token은 만료 전까지(기본 1시간) 유효합니다. 즉시 차단이 필요한 경우(계정 정지)는 `profiles.is_active=false`로 처리하며, 다음 요청부터 403 `ACCOUNT_DISABLED`가 됩니다.

### 사용자 유형과 학원 내 역할 (권한 분리)

| 구분 | 값 | 저장 위치 | 부여 방법 |
| --- | --- | --- | --- |
| 서비스 사용자 유형 | `STUDENT`, `INSTRUCTOR` | `profiles.user_type` | 가입 시 본인 선택 (`POST /users/me`), 이후 변경 불가 |
| 시스템 관리자 | `ADMIN` | `profiles.user_type` | **API로 부여 불가**. DB에서 수동 지정 (development-guide.md §8) |
| 학원 내 역할 | `OWNER`, `MANAGER`, `INSTRUCTOR`, `STUDENT` | `academy_memberships.role` | 아래 정책 |

- **시스템 ADMIN ≠ 학원 관리자.** 시스템 ADMIN은 학원 등록 심사만 할 수 있고, 학원 소속이 아니면 학원 내부 데이터(멤버, 가입 요청)에 접근할 수 없습니다(404).
- 역할은 JWT 클레임이 아니라 DB에서 매 요청 조회합니다. 변경이 즉시 반영됩니다.

학원 정책 (v0.2 확정)

| 항목 | 정책 |
| --- | --- |
| 학원 생성 | `INSTRUCTOR`가 등록 신청 → `PENDING_APPROVAL` → 시스템 ADMIN 승인 시 `ACTIVE`, 거절 시 `REJECTED`. 승인 대기 신청은 1인당 최대 3개 |
| 학원 관리자 | 신청자가 `OWNER`(학원당 1명). OWNER가 소속 강사를 `MANAGER`로 지정·해제. OWNER 양도는 v0.3 |
| 학생·강사 합류 | 본인이 가입 요청 → OWNER/MANAGER 승인. 신청 역할은 사용자 유형에서 결정(학생→STUDENT, 강사→INSTRUCTOR) |
| 탈퇴·제외 | 본인 탈퇴 `LEFT`, 관리자 제외 `REMOVED`. OWNER는 탈퇴·제외 불가. MANAGER는 다른 MANAGER를 제외할 수 없음 |
| 재가입 | 새 가입 요청 → 승인 시 기존 소속 행을 `ACTIVE`로 재활성화 (역할은 요청 역할로 초기화) |

### 권한 의존성 (`app/api/deps.py`)

```python
CurrentUser                              # 유효한 토큰 (프로필 없어도 됨)          → 401
ActiveProfile                            # + 프로필 존재, is_active               → 403 PROFILE_REQUIRED / ACCOUNT_DISABLED
Depends(require_user_types(UserType.ADMIN))           # 서비스 사용자 유형         → 403
Depends(require_academy_roles(*ACADEMY_ADMIN_ROLES))  # 경로 academy_id의 ACTIVE 소속·역할 → 404(비소속) / 403(역할 부족)

@router.get("/{academy_id}/members")
async def list_members(academy_id: UUID, _: AcademyStaff, session: DbSession, ...): ...
```

- 학원 범위 API는 경로에 `academy_id`를 둡니다. 하위 리소스(요청, 멤버)는 **`academy_id`와 리소스 ID를 함께** 조회하므로, 다른 학원의 ID를 넣으면 404가 됩니다.
- 동시성: 가입 요청 중복은 DB 부분 유니크 인덱스로 막고, 승인·거절은 요청 행을 `SELECT ... FOR UPDATE`로 잠가 한 번만 처리합니다.

### 학원 운영 권한 (v0.3, `app/services/access.py`)

- 경로 의존성(`AcademyMember`/`AcademyStudent`/`AcademyStaff`/`AcademyAdmin`)으로 학원 소속·역할을 먼저 확인하고, 반·학생 단위 권한은 서비스 계층의 `AccessService`가 판단합니다.
- **담당 반**: `class_memberships`에 담당 강사(INSTRUCTOR)로 지정된 ACTIVE 반. **담당 학생**: 담당 반의 ACTIVE 학생. OWNER/MANAGER는 학원 전체.
- 강사 이상은 반·일정·주제를 학원 전체 읽기, 쓰기와 학생 데이터(출석·과제 완료)는 담당 범위만. 학생은 배정된 반과 본인 기록만.
- 개인 할 일(`personal_todos`)은 학원 데이터가 아니므로 `academy_id`가 없고, 본인 토큰으로만 접근합니다.
- 2차 방어: 학원 소유 테이블의 부모 참조는 `(academy_id, id)` 복합 FK → 교차 학원 연결을 DB가 거부합니다.
- 동시성: 출석·반 배정은 유니크 제약 + `ON CONFLICT`, 출석 수정·일정 겹침 검사·과제 배포는 행 잠금(`FOR UPDATE`).
- 시간대: `app/core/timezone.py` (시각=UTC timestamptz, 운영 날짜=Asia/Seoul date, 정규 수업 시간=Asia/Seoul time).

## 6. 향후 AI 연동 구조

```text
강사 음성 녹음 ──▶ Storage(audio) ──▶ [작업] STT ──▶ transcript
                                                 │
작품 사진/단계 ──────────────────────────────────┤
                                                 ▼
                                    [작업] LLM 첨삭 요약 ──▶ ai_analyses (status=completed, draft)
                                                 │
                         강사 검토·수정 후 확정 ──▶ feedbacks (source=teacher_confirmed)
```

- **인터페이스 분리**: `app/integrations/ai/`에 `SpeechToText`, `FeedbackSummarizer` 등 `Protocol`을 정의하고 공급자별 구현을 둡니다. 서비스는 Protocol에만 의존 → 공급자 교체·테스트 Mock이 쉬움.
- **비동기 처리**: STT/LLM은 수 초~수십 초 걸리므로 요청 안에서 기다리지 않습니다. `ai_analyses` 레코드를 `pending`으로 만들고 `202 Accepted`로 응답 → 백그라운드 작업이 처리 후 `completed/failed`로 갱신, 클라이언트는 폴링(또는 Supabase Realtime 구독). 초기에는 FastAPI `BackgroundTasks`, 부하가 커지면 별도 워커(큐)로 분리.
- **AI 결과와 확정 피드백 분리**: AI 결과는 `ai_analyses`에 원문 그대로 저장(모델명·프롬프트 버전 포함), 강사가 확정한 내용만 `feedbacks`에 저장합니다. 학생·학부모 리포트에는 확정본만 노출합니다.
- **개인정보**: LLM에 보내는 데이터는 최소화(학생 실명·연락처 제외, 내부 ID만 사용). 원본 음성은 보존 기간 후 삭제(→ database-design.md).
- **비용·안정성**: 타임아웃, 재시도(지수 백오프), 학원별 사용량 기록을 integration 계층에서 공통 처리합니다.

## 7. 로깅·관측

- 모든 로그에 `request_id` 포함, 응답 헤더 `X-Request-ID`로 클라이언트에도 전달 (문의 시 추적용)
- 운영: 한 줄 JSON(stdout) → Render 로그 검색 / 개발: 읽기 쉬운 text
- 요청당 접근 로그 1줄: `method`, `path`, `status_code`, `duration_ms` (쿼리스트링·바디는 기록하지 않음)
- 비밀번호·토큰·DB URL·학생 개인정보를 로그에 남기지 않습니다. SQL 로그는 `DEBUG=true`에서만.
