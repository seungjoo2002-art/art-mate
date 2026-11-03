# ART MATE 백엔드 아키텍처

> 대상 버전: v0.1 (기반 구축) · 이후 버전에서 변경 시 이 문서를 함께 갱신합니다.

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
| 인증 없음/실패 | 401 | `UNAUTHORIZED` (+ `WWW-Authenticate: Bearer`) | `UnauthorizedError` |
| 인증 미구현(v0.1) | 401 | `AUTH_NOT_CONFIGURED` | `verify_access_token` |
| 권한 없음 | 403 | `FORBIDDEN` | `ForbiddenError` |
| 리소스 없음 | 404 | `NOT_FOUND` | `NotFoundError`, 존재하지 않는 경로 |
| 허용되지 않은 메서드 | 405 | `METHOD_NOT_ALLOWED` | 라우터 |
| 중복·상태 충돌 | 409 | `CONFLICT` | `ConflictError` |
| 서버 내부 오류 | 500 | `INTERNAL_SERVER_ERROR` (메시지 고정, 스택트레이스 미노출) | 미들웨어 |
| 일시적 불가 | 503 | `SERVICE_UNAVAILABLE`, `DATABASE_NOT_CONFIGURED`, `DATABASE_UNAVAILABLE` | `ServiceUnavailableError` 계열 |

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

### 공개 / 보호 API 분리

| 구분 | 경로 | 인증 |
| --- | --- | --- |
| 공개 | `/`, `/health`, `/api/v1/health`, `/api/v1/health/db` | 없음 (내부 정보 미노출) |
| 보호 | 그 외 모든 `/api/v1/*` 비즈니스 API | `CurrentUser` 의존성 필수 |

v0.1에서는 `verify_access_token()`이 항상 401(`AUTH_NOT_CONFIGURED`)을 반환합니다(**fail-closed**). 따라서 v0.2 이전에 보호 API를 추가해도 공개되지 않습니다.

### Supabase JWT 검증 (v0.2 구현 방향)

1. `Authorization: Bearer <access_token>` 추출 (`HTTPBearer`, 누락 시 401)
2. JWT 헤더의 `kid`로 Supabase JWKS(`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) 공개키 선택 — 비대칭 서명키(ES256/RS256) 기준. JWKS는 메모리에 캐시(예: 10분)하고, 모르는 `kid`면 1회 재조회
3. 검증 항목
   - **서명**: 허용 알고리즘 화이트리스트(`alg: none`, HS/RS 혼동 공격 거부)
   - **iss** = `{SUPABASE_URL}/auth/v1`
   - **aud** = `authenticated`
   - **exp / nbf / iat**, leeway ≤ 30초
   - **sub**: UUID 형식 → `AuthenticatedUser.user_id`
   - `role` 클레임이 `authenticated`인지 확인 (`anon` 토큰 거부)
4. 실패 사유는 서버 로그에만 남기고 응답은 401 `UNAUTHORIZED`로 통일
5. 라이브러리 후보: `PyJWT[crypto]` (`PyJWKClient`) — v0.2에서 추가
6. 레거시 HS256 공유 시크릿 방식은 사용하지 않습니다(시크릿 유출 시 토큰 위조 가능). 프로젝트가 아직 레거시 키라면 Supabase 대시보드에서 비대칭 키로 전환합니다.

### 역할과 학원 소속

- 역할(`admin`/`teacher`/`student`)은 **학원별 소속(`academy_memberships`)의 속성**입니다. 같은 사용자가 A 학원에서는 강사, B 학원에서는 관리자일 수 있습니다.
- 역할은 JWT 커스텀 클레임에 넣지 않고 DB에서 조회합니다 (변경 즉시 반영, 토큰 재발급 불필요).
- 학원 범위 API는 경로에 학원을 명시합니다: `/api/v1/academies/{academy_id}/students/...`
- v0.2에서 추가할 의존성 (라우터는 선언만):

```python
# app/api/deps.py (v0.2 예시)
async def get_academy_member(academy_id: UUID, user: CurrentUser, session: DbSession) -> Membership:
    membership = await MembershipRepository(session).get_active(academy_id, user.user_id)
    if membership is None:
        raise NotFoundError()          # 소속이 아니면 학원 존재 여부도 숨김
    return membership

def require_roles(*roles: AcademyRole): ...   # 역할 검사 의존성 팩토리

@router.post("/academies/{academy_id}/classes")
async def create_class(member: Annotated[Membership, Depends(require_roles(AcademyRole.ADMIN))], ...): ...
```

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
