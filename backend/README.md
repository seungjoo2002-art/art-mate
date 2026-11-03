# ART MATE API (backend)

미대입시·예중·예고 입시학원을 위한 **AI 기반 실기교육·학생관리 플랫폼** ART MATE의 백엔드입니다.

> **현재 버전: v0.2** — v0.1 기반(설정, DB, 공통 예외·로깅, Health API) + **Supabase Auth JWT 인증, 사용자 프로필, 학원 등록·심사, 학원 가입 요청·승인, 소속 관리**.
> 작품 업로드, 첨삭, AI 기능 등은 이후 버전에서 구현합니다.

| 문서 | 내용 |
| --- | --- |
| [docs/architecture.md](../docs/architecture.md) | 레이어 구조, 요청 흐름, 인증·AI 연동 구조 |
| [docs/database-design.md](../docs/database-design.md) | 엔티티 설계, 학원별 데이터 격리, RLS 방향 |
| [docs/development-guide.md](../docs/development-guide.md) | Git 협업 규칙, 새 API 추가 방법, 버전 체크리스트, 운영 절차(마이그레이션 적용·ADMIN 지정) |
| [docs/frontend-integration.md](../docs/frontend-integration.md) | 프론트엔드 인증 연동, API 예시, 오류 코드 |
| [docs/privacy-and-data-policy.md](../docs/privacy-and-data-policy.md) | 개인정보 최소 수집, 미성년자·탈퇴 후속 과제 |

## 기술 스택

| 영역 | 사용 기술 (v0.1 lock 기준 버전) |
| --- | --- |
| Language | Python 3.12 |
| Framework / Server | FastAPI 0.162, Uvicorn 0.54 |
| Validation / Config | Pydantic 2.14, pydantic-settings 2.16 |
| Database | Supabase PostgreSQL, SQLAlchemy 2.1 (async), asyncpg 0.32 |
| Migration | Alembic 1.20 |
| Test | pytest 9, pytest-asyncio 1.4, httpx 0.28 |
| Lint / Format | Ruff 0.17 |
| Package manager | [uv](https://docs.astral.sh/uv/) (`uv.lock`로 두 개발자 환경 고정) |

## 설치

사전 준비: Python 3.12, uv

```bash
cd backend
uv sync              # .venv 생성 + 의존성(개발용 포함) 설치. Python 3.12가 없으면 uv가 안내합니다.
cp .env.example .env # 값 채우기 (아래 참고)
```

> 의존성 추가/변경은 `uv add <패키지>` (개발용은 `uv add --dev <패키지>`)로 하고, 변경된 `uv.lock`을 함께 커밋합니다.

## 환경변수

모든 설정은 `app/core/config.py`의 `Settings`에서 읽습니다. 전체 목록과 설명은 [`.env.example`](.env.example)을 보세요.

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `APP_ENV` | | `development`(기본) / `test` / `staging` / `production` |
| `DEBUG` | | staging·production에서 `true`면 기동 실패 |
| `DATABASE_URL` | production에서 필수 | Supabase Postgres URL. `postgresql://...` 그대로 붙여넣으면 asyncpg용으로 자동 변환. 비우면 DB 기능 비활성 |
| `CORS_ORIGINS` | | 쉼표 구분. staging·production에서 `*` 금지 |
| `DOCS_ENABLED` | | 비우면 development/test에서만 API 문서 공개 |
| `SUPABASE_URL` | 인증 사용 시 필수 | `https://<ref>.supabase.co`. JWT 발급자·JWKS 공개키 주소를 여기서 만듭니다. 비우면 보호 API 전부 401 (fail-closed) |
| `AUTH_JWT_AUDIENCE`, `AUTH_JWT_LEEWAY_SECONDS`, `AUTH_JWKS_CACHE_SECONDS` | | 기본값 `authenticated`, 10초, 600초 |
| `SUPABASE_ANON_KEY` | | 백엔드는 사용하지 않음 (프론트용). **service_role 키는 사용하지 않습니다** |
| `LOG_LEVEL`, `LOG_FORMAT` | | 로그 수준, `json`/`text` |

잘못된 값이 있으면 서버가 기동하지 않고, 어떤 변수가 왜 잘못됐는지 **비밀값을 제외하고** 출력합니다.

### Supabase 연결 문자열 선택

| 방식 | 주소 | 용도 |
| --- | --- | --- |
| Session pooler | `...pooler.supabase.com:5432` | **권장**: 로컬 개발, Render 같은 상시 실행 서버, Alembic |
| Transaction pooler | `...pooler.supabase.com:6543` | 서버리스용. 포트 6543이면 prepared statement를 자동으로 끕니다 |
| Direct | `db.<ref>.supabase.co:5432` | IPv6 환경에서만 |

## 로컬 서버 실행

```bash
cd backend
uv run uvicorn app.main:app --reload            # http://127.0.0.1:8000
```

| 경로 | 설명 |
| --- | --- |
| `GET /` | 서비스 정보 `{"service","version","status"}` |
| `GET /health` | 프로세스 상태 (DB와 무관, 헬스체크용) |
| `GET /api/v1/health` | API v1 상태 |
| `GET /api/v1/health/db` | `SELECT 1` 실행. 미설정·장애 시 `503` (`DATABASE_NOT_CONFIGURED` / `DATABASE_UNAVAILABLE`) |

v0.2 인증 API (모두 `Authorization: Bearer <Supabase access token>` 필요, 상세: docs/frontend-integration.md)

| 경로 | 설명 | 권한 |
| --- | --- | --- |
| `GET / POST / PATCH /api/v1/users/me` | 내 프로필 조회 / 생성(멱등) / 수정 | 로그인 |
| `GET /api/v1/users/me/join-requests` | 내 가입 요청 | 프로필 |
| `POST /api/v1/academies` | 학원 등록 신청 | INSTRUCTOR |
| `GET /api/v1/academies[?q=&mine=true]` | 학원 찾기 / 내 학원 | 프로필 |
| `GET /api/v1/academies/{id}` | 학원 상세 | 프로필 (비승인 학원은 소속·ADMIN만) |
| `GET /api/v1/academies/{id}/members` | 멤버 목록 | OWNER/MANAGER/INSTRUCTOR |
| `PATCH /api/v1/academies/{id}/members/{membership_id}` | MANAGER 지정/해제 | OWNER |
| `DELETE /api/v1/academies/{id}/members/{membership_id}` | 멤버 제외 | OWNER/MANAGER |
| `DELETE /api/v1/academies/{id}/members/me` | 학원 탈퇴 | 소속 멤버 (OWNER 제외) |
| `POST / GET /api/v1/academies/{id}/join-requests` | 가입 요청 / 요청 목록 | 학생·강사 / OWNER·MANAGER |
| `PATCH /api/v1/academies/{id}/join-requests/{request_id}` | 승인·거절 | OWNER/MANAGER |
| `GET /api/v1/admin/academies`, `PATCH /api/v1/admin/academies/{id}` | 학원 등록 심사 | 시스템 ADMIN |

## API 문서

development/test 환경에서 다음 주소로 접근할 수 있습니다. staging/production에서는 기본적으로 비공개이며 `DOCS_ENABLED=true`로 켤 수 있습니다.

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

## 테스트 · 코드 품질

```bash
cd backend
uv run pytest                    # 전체 테스트 (DB 통합 테스트는 TEST_DATABASE_URL 없으면 skip)
uv run ruff check .              # lint
uv run ruff format .             # 포맷 적용 (CI는 --check)
```

- 테스트는 `backend/.env`를 **읽지 않으며** 운영 DB에 접근하지 않습니다.
- DB 연결 실패 테스트는 접속이 거부되는 로컬 주소(`127.0.0.1:1`)로 실제 asyncpg 연결을 시도해 검증합니다.
- 인증 테스트는 테스트용 EC 키로 Supabase 형식 JWT를 직접 만들어 검증합니다 (실제 Supabase 미접속).
- DB 기반 테스트(`tests/db/`: 프로필·학원·가입 요청·권한·동시성·마이그레이션)는 **로컬 테스트 DB**가 필요합니다.
  `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/artmate_test uv run pytest`
  - 로컬(localhost) DB만 허용되고 Supabase 호스트이면 테스트가 중단됩니다. 시작할 때 스키마를 초기화하므로 개발 데이터가 있는 DB를 지정하지 마세요.
  - GitHub Actions CI에서는 Postgres 서비스 컨테이너로 자동 실행됩니다.

## DB 마이그레이션 (Alembic)

```bash
cd backend
uv run alembic revision --autogenerate -m "create academies"  # 모델 변경 후 리비전 생성
uv run alembic upgrade head                                    # 개발 DB에 적용
uv run alembic upgrade head --sql                              # 적용될 SQL만 확인
```

- 새 모델은 `app/models/__init__.py`에 import 해야 autogenerate가 인식합니다.
- 생성된 리비전 파일은 **반드시 직접 검토**한 뒤 커밋합니다.
- 서버 기동·Docker 이미지에서 마이그레이션을 자동 실행하지 않습니다.
  `APP_ENV=production` 대상은 `ALLOW_PRODUCTION_MIGRATIONS=true`를 명시해야만 실행됩니다.

## Docker

```bash
cd backend
docker build -t artmate-api .
docker run --rm -p 8000:8000 --env-file .env -e APP_ENV=development artmate-api
```

- 비루트 사용자(`app`, uid 10001)로 실행, `PORT` 환경변수로 포트 지정(Render가 자동 주입)
- 이미지 기본값은 `APP_ENV=production` → `DATABASE_URL`이 없으면 설정 오류로 종료
- `HEALTHCHECK`는 `/health`를 호출합니다 (Render Health Check Path도 `/health`로 설정)

## 폴더 구조

```text
backend/
├── app/
│   ├── main.py              # create_app(): 앱 생성, 미들웨어·예외·라우터 등록, lifespan
│   ├── core/                # 앱 전역 공통 (다른 app.* 계층에 의존하지 않음)
│   │   ├── config.py        # Settings (pydantic-settings), 환경별 검증 규칙
│   │   ├── logging.py       # JSON/text 구조화 로깅, request_id 주입
│   │   ├── middleware.py    # request id, 접근 로그, 안전한 500 응답
│   │   ├── exceptions.py    # AppError 계층, 공통 에러 응답 형식
│   │   └── security.py      # Supabase JWT 검증 (JWKS, ES256/RS256), CurrentUser
│   ├── api/
│   │   ├── router.py        # /, /health + /api/v1 마운트
│   │   ├── deps.py          # DbSession, ActiveProfile, require_user_types, require_academy_roles
│   │   ├── responses.py     # OpenAPI 공통 에러 응답
│   │   └── v1/
│   │       ├── router.py    # v1 도메인 라우터 등록
│   │       └── endpoints/   # health, users, academies, admin
│   ├── db/
│   │   ├── base.py          # Declarative Base, naming convention, UUID/timestamp mixin
│   │   └── session.py       # Database(engine, session_factory, ping), Supabase pooler 대응
│   ├── models/              # profile, academy, membership(소속·가입 요청), enums
│   ├── schemas/             # common(에러·페이지네이션), user, academy, health
│   ├── repositories/        # profiles, academies, memberships, pagination
│   ├── services/            # profiles, academies, memberships (권한 규칙·트랜잭션)
│   ├── integrations/        # supabase/, ai/ 외부 연동
│   └── utils/
├── alembic/                 # env.py(async), versions/0001 (v0.2 테이블·RLS·auth FK)
├── tests/
├── .env.example
├── alembic.ini
├── pyproject.toml / uv.lock
└── Dockerfile / .dockerignore
```
