# ART MATE API (backend)

미대입시·예중·예고 입시학원을 위한 **AI 기반 실기교육·학생관리 플랫폼** ART MATE의 백엔드입니다.

> **현재 버전: v0.5** — v0.4 + **질문 콜·대기열(폴링)**, **피드백 음성 녹음 저장·녹음 동의**.
> 이전(v0.4): v0.3 + **단계별 작품 사진 업로드(Supabase Storage 비공개 버킷, Signed URL)**, **시험 타이머·단계 목표 알림 데이터**.
> 이전: v0.2(Supabase Auth JWT 인증, 사용자 프로필, 학원 등록·심사·가입·소속) + **학원 운영: 반·반 배정·담당 강사, 정규 수업·휴강·보강 일정, 출석·수정 이력, 수업 주제·과제 배포, 학생 개인 할 일, 오늘 할 일 통합, 강사 수업 현황 대시보드**.
> 작품 업로드, 질문 콜, 녹음, AI 피드백, 커뮤니티는 이후 버전에서 구현합니다.

| 문서 | 내용 |
| --- | --- |
| [docs/architecture.md](../docs/architecture.md) | 레이어 구조, 요청 흐름, 인증·AI 연동 구조 |
| [docs/database-design.md](../docs/database-design.md) | 엔티티 설계, 학원별 데이터 격리, RLS 방향 |
| [docs/development-guide.md](../docs/development-guide.md) | Git 협업 규칙, 새 API 추가 방법, 버전 체크리스트, 운영 절차(마이그레이션 적용·ADMIN 지정) |
| [docs/frontend-integration.md](../docs/frontend-integration.md) | 프론트엔드 인증 연동, API 예시, 오류 코드 |
| [docs/frontend-integration-v0.5.md](../docs/frontend-integration-v0.5.md) | v0.5 질문 콜 상태·폴링·예상 대기시간, 녹음 업로드·MediaRecorder·동의 UI |
| [docs/frontend-integration-v0.4.md](../docs/frontend-integration-v0.4.md) | v0.4 작품 사진 업로드 절차·Signed URL, 시험 타이머 응답·알림 처리 |
| [docs/frontend-integration-v0.3.md](../docs/frontend-integration-v0.3.md) | v0.3 학원 운영 API: 출석·일정·과제·개인 할 일·대시보드, 권한, 날짜·시간 규칙 |
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

v0.3 학원 운영 API (경로 접두사 `/api/v1/academies/{id}`, 상세: docs/frontend-integration-v0.3.md)

| 경로 | 설명 | 권한 |
| --- | --- | --- |
| `/classes`, `/classes/{class_id}` | 반 생성·목록·상세·수정·보관 | 생성·수정 OWNER/MANAGER, 조회 멤버(학생은 배정 반) |
| `/classes/{class_id}/members` | 학생 배정·담당 강사 지정·해제 | OWNER/MANAGER, 담당 강사(학생만) |
| `/classes/{class_id}/schedules`, `/schedule-exceptions` | 정규 수업, 휴강·1회 변경·보강 | OWNER/MANAGER, 담당 강사 |
| `GET /schedules?from&to` | 날짜 범위 일정 (학생별·강사별·반별) | 멤버 |
| `/attendance/check-in`, `/attendance/me[/today]` | 출석하기, 내 출석 | STUDENT |
| `/attendance`, `/attendance/records[/{id}[/history]]` | 출석 현황·기록·수정·이력 | 강사 이상 (담당 학생) |
| `/classes/{class_id}/lesson-topics` | 수업 주제·다음 수업 공지 | 조회 반 멤버, 쓰기 담당 강사 |
| `/tasks`, `/tasks/{task_id}` | 과제 배포·수정·취소·완료 현황 | 강사 이상 (담당 반) |
| `/tasks/me`, `PUT /tasks/{task_id}/completion` | 받은 과제, 완료 체크 | STUDENT |
| `GET /dashboard` | 강사 수업 현황 대시보드 | 강사 이상 |
| `/api/v1/personal-todos[/{id}]` | 개인 할 일 (본인만) | STUDENT 사용자 |
| `GET /api/v1/users/me/today` | 오늘 할 일 통합 (학원 과제 + 개인 할 일 + 주제) | STUDENT 사용자 |

v0.4 작품·시험 API (상세: docs/frontend-integration-v0.4.md)

| 경로 | 설명 | 권한 |
| --- | --- | --- |
| `/api/v1/artworks[/{id}]`, `/progress` | 내 작품 생성·조회·수정·삭제, 진행 상태 | STUDENT 사용자 (학원 미소속 가능) |
| `/api/v1/artworks/{id}/photos[...]` | 업로드 요청·완료, 대표 지정, 삭제·교체, Signed URL | 작품 소유자 |
| `/api/v1/academies/{id}/artworks[...]` | 담당 학생의 학원 연결 작품 조회 | 강사 이상 (담당 학생) |
| `/api/v1/academies/{id}/exam-templates[...]` | 시험 템플릿·단계별 목표 시각 | 강사 이상 (수정: 만든 사람·관리자) |
| `/api/v1/academies/{id}/exam-sessions[...]` | 반 시험 생성·시작·종료·현황 | 담당 강사·관리자 |
| `/api/v1/academies/{id}/exam-sessions/me`, `/{sid}/me[/stage]` | 내 시험 타이머, 작업 단계 변경 | STUDENT |

v0.5 질문 콜·녹음 API (상세: docs/frontend-integration-v0.5.md)

| 경로 | 설명 | 권한 |
| --- | --- | --- |
| `POST /api/v1/academies/{id}/help-requests`, `/me[/{rid}[/cancel]]` | 질문 요청·내 상태(순번·예상 대기)·취소 | 반 학생 |
| `/api/v1/academies/{id}/classes/{cid}/help-queue[/call-next]` | 반 대기열, 다음 학생 호출 | 담당 강사·관리자 |
| `POST /api/v1/academies/{id}/help-requests/{rid}/{action}` | call·start·complete·skip·requeue·cancel | 담당 강사·관리자 |
| `GET /api/v1/academies/{id}/classes/{cid}/help-queue/estimate` | 예상 대기시간 | 반 학생·강사 |
| `/api/v1/recording-consents[/me]` | 녹음 동의·철회 | STUDENT 사용자 |
| `/api/v1/artworks/{id}/recordings[...]` | 녹음 업로드 요청·완료·목록·재생 URL·삭제 | 작품 소유자 |
| `/api/v1/academies/{id}/artworks/{aid}/recordings[...]` | 담당 학생 녹음 조회·재생 | 강사 이상 (담당 학생) |

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
│   │   ├── timezone.py      # Asia/Seoul 날짜·시각 규칙 (local_today, local_day_bounds)
│   │   └── security.py      # Supabase JWT 검증 (JWKS, ES256/RS256), CurrentUser
│   ├── api/
│   │   ├── router.py        # /, /health + /api/v1 마운트
│   │   ├── deps.py          # DbSession, ActiveProfile, require_user_types, require_academy_roles
│   │   ├── responses.py     # OpenAPI 공통 에러 응답
│   │   └── v1/
│   │       ├── router.py    # v1 도메인 라우터 등록
│   │       └── endpoints/   # health, users, academies, admin, classes, schedules, attendance,
│   │                        # lesson_topics, tasks, personal_todos, dashboard
│   ├── db/
│   │   ├── base.py          # Declarative Base, naming convention, UUID/timestamp mixin
│   │   └── session.py       # Database(engine, session_factory, ping), Supabase pooler 대응
│   ├── models/              # profile, academy, membership, academy_class, attendance, task,
│   │                        # personal_todo, enums
│   ├── schemas/             # common, fields, user, academy, classes, attendance, tasks,
│   │                        # personal_todo, dashboard, health
│   ├── repositories/        # profiles, academies, memberships, classes, attendance, tasks
│   ├── services/            # access(담당 반·학생 권한), academies, memberships, classes,
│   │                        # schedules, attendance, tasks, personal_todos, dashboard
│   ├── integrations/        # supabase/, ai/ 외부 연동
│   └── utils/
├── alembic/                 # env.py(async), versions/0001 (v0.2), 0002 (v0.3 학원 운영), 0003 (v0.4 작품·시험), 0004 (v0.5 질문 콜·녹음)
├── supabase/storage-setup.sql  # Supabase 전용: artworks·feedback-audio 버킷, storage.objects RLS 정책 (수동 적용)
├── tests/
├── .env.example
├── alembic.ini
├── pyproject.toml / uv.lock
└── Dockerfile / .dockerignore
```
