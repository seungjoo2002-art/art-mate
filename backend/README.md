# ART MATE API (backend)

미대입시·예중·예고 입시학원을 위한 **AI 기반 실기교육·학생관리 플랫폼** ART MATE의 백엔드입니다.

> **현재 버전: v0.1** — 백엔드 기반(설정, DB 연결 구조, 공통 예외·로깅, Health API, 테스트, 문서)만 포함합니다.
> 회원가입/로그인, 작품 업로드, 첨삭, AI 기능 등은 이후 버전에서 구현합니다.

| 문서 | 내용 |
| --- | --- |
| [docs/architecture.md](../docs/architecture.md) | 레이어 구조, 요청 흐름, 인증·AI 연동 구조 |
| [docs/database-design.md](../docs/database-design.md) | 엔티티 설계, 학원별 데이터 격리, RLS 방향 |
| [docs/development-guide.md](../docs/development-guide.md) | Git 협업 규칙, 새 API 추가 방법, 버전 체크리스트 |

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
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | v0.2부터 | 인증 연동용. **service_role 키는 사용하지 않습니다** |
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
- 실제 Postgres 통합 테스트(선택): 테스트 전용 DB를 띄우고
  `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/artmate_test uv run pytest -m integration`
  (GitHub Actions CI에서는 Postgres 서비스 컨테이너로 자동 실행)

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
│   │   └── security.py      # Bearer 인증 의존성 (v0.1: fail-closed), AcademyRole
│   ├── api/
│   │   ├── router.py        # /, /health + /api/v1 마운트
│   │   ├── deps.py          # AppSettings, DatabaseDep, DbSession 의존성
│   │   └── v1/
│   │       ├── router.py    # v1 도메인 라우터 등록
│   │       └── endpoints/   # 도메인별 엔드포인트 (health.py)
│   ├── db/
│   │   ├── base.py          # Declarative Base, naming convention, UUID/timestamp mixin
│   │   └── session.py       # Database(engine, session_factory, ping), Supabase pooler 대응
│   ├── models/              # ORM 모델 (v0.1: 없음, Alembic 등록 지점)
│   ├── schemas/             # Pydantic 스키마 (common.py: 에러·페이지네이션 규칙)
│   ├── repositories/        # DB 접근
│   ├── services/            # 비즈니스 로직
│   ├── integrations/        # supabase/, ai/ 외부 연동
│   └── utils/
├── alembic/                 # env.py(async), script.py.mako, versions/
├── tests/
├── .env.example
├── alembic.ini
├── pyproject.toml / uv.lock
└── Dockerfile / .dockerignore
```
