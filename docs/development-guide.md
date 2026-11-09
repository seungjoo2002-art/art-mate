# ART MATE 개발 가이드

두 명의 개발자가 GitHub에서 병렬로 개발하고, 버전(v0.x)이 끝날 때마다 안정 버전을 `main`에 병합하는 것을 전제로 합니다.

## 1. 브랜치 전략

```text
main      ── 안정 버전만. 버전 완료 시 merge + 태그(v0.1.0, v0.2.0 ...)
  └ develop ── 현재 버전 통합 브랜치. 기능 PR의 대상
       ├ feature/v0.2-auth-jwt        (개발자 A)
       └ feature/v0.2-academy-crud    (개발자 B)
```

- `main`, `develop`에 직접 push 금지 (GitHub Branch protection: PR 필수, CI 통과 필수, 승인 1명)
- 기능 브랜치는 `develop`에서 만들고, 작게 자주 PR (권장: 변경 400줄 이하)
- 하루 1회 이상 `develop`을 기능 브랜치에 rebase 또는 merge 해서 충돌을 일찍 발견

> v0.1은 아직 `develop`이 없으므로 `feature/v0.1-backend-foundation` → `main` PR로 병합한 뒤 `main`에서 `develop`을 생성합니다.

### 브랜치 명명 규칙

`<type>/<version>-<짧은-설명>` (소문자, 하이픈)

| type | 용도 | 예 |
| --- | --- | --- |
| `feature/` | 기능 | `feature/v0.2-auth-jwt` |
| `fix/` | 버그 수정 | `fix/v0.2-cors-preflight` |
| `refactor/` | 동작 변경 없는 구조 개선 | `refactor/v0.3-repository-base` |
| `docs/` | 문서 | `docs/v0.2-rls-policy` |
| `chore/` | 설정·의존성·CI | `chore/bump-fastapi` |
| `hotfix/` | `main` 긴급 수정 (main에서 분기, main·develop 모두 반영) | `hotfix/v0.2.1-db-timeout` |

### 커밋 메시지

[Conventional Commits](https://www.conventionalcommits.org/ko/) 형식: `<type>(<scope>): <요약>`

```text
feat(auth): verify Supabase JWT with JWKS
fix(health): return 503 when DB ping times out
docs(db): add teacher_calls index policy
```

## 2. PR 및 Merge 규칙

1. PR 템플릿(`.github/pull_request_template.md`)의 체크리스트를 채웁니다.
2. CI(`backend-ci`) 통과 필수: Ruff lint/format, pytest(+ Postgres 통합 테스트), Alembic 적용, Docker 빌드.
3. 다른 개발자 1명 승인 후 merge. 리뷰 포인트: 학원 격리(`academy_id` 조건), 권한 의존성, 에러 코드, 테스트, 비밀값.
4. 기능 → `develop`: **Squash merge** (기능당 커밋 1개로 히스토리 정리)
5. `develop` → `main`(버전 완료): **Merge commit** + 태그 `v0.x.0`
6. merge한 기능 브랜치는 삭제합니다.

### 충돌이 잦은 파일과 규칙

| 파일 | 규칙 |
| --- | --- |
| `app/api/v1/router.py` | 도메인당 `include_router` 한 줄만 추가 (알파벳 순) |
| `app/models/__init__.py` | 모델 import 한 줄씩 (알파벳 순) |
| `alembic/versions/` | 아래 "마이그레이션 충돌" 참고 |
| `pyproject.toml`, `uv.lock` | 의존성은 `uv add`로만 변경. lock 충돌 시 손으로 고치지 말고 `uv lock` 재실행 |
| `.env.example` | 새 변수는 해당 섹션 끝에 추가 |

### 마이그레이션 충돌

두 사람이 동시에 리비전을 만들면 `alembic heads`가 2개가 됩니다.

```bash
git merge develop                 # 또는 rebase
uv run alembic heads              # head가 2개면
# 방법 1 (권장): 내 리비전 파일의 down_revision 을 상대 리비전 ID로 수정
# 방법 2: uv run alembic merge -m "merge heads" <rev1> <rev2>
uv run alembic upgrade head       # 개발 DB에서 확인
```

DB 스키마를 바꾸는 PR은 동시에 하나씩 진행하도록 미리 이야기하는 것이 가장 쉽습니다.

## 3. 환경변수 관리

- 실제 값은 `backend/.env`(로컬)와 Render 환경변수(운영)에만 둡니다. **`.env`는 절대 커밋하지 않습니다** (`.gitignore` 처리됨).
- 새 환경변수 추가 순서: `Settings` 필드 추가(+ 검증) → `.env.example` → README 표 → PR 설명에 명시 → 상대 개발자에게 공유
- 비밀값 공유는 메신저 평문 대신 비밀번호 관리자(1Password, Bitwarden 등) 사용
- 개발 DB: 운영 Supabase 프로젝트와 **별도 프로젝트**(또는 로컬 Postgres)를 사용합니다. 운영 DB URL을 로컬 `.env`에 넣지 않습니다.
- Supabase `service_role` 키는 백엔드에 넣지 않습니다 (→ database-design.md 4.3).
- 실수로 비밀값을 커밋했다면: 즉시 키를 재발급(rotate)하고 알립니다. 히스토리 삭제만으로는 충분하지 않습니다.

## 4. 로컬 개발 루틴

```bash
cd backend
uv sync                                  # 의존성 동기화 (pull 후 매번)
uv run uvicorn app.main:app --reload     # 서버
uv run pytest                            # 테스트
uv run ruff check . --fix && uv run ruff format .   # PR 전
```

## 5. 새 API 추가 방법

예: 학원 조회 API `GET /api/v1/academies/{academy_id}`

1. **모델** `app/models/academy.py`
   ```python
   class Academy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
       __tablename__ = "academies"
       name: Mapped[str] = mapped_column(String(100))
   ```
   → `app/models/__init__.py`에 `from app.models.academy import Academy` 추가 → `alembic revision --autogenerate`
2. **스키마** `app/schemas/academy.py`
   ```python
   class AcademyRead(APIModel):
       id: UUID
       name: str
       created_at: datetime
   ```
3. **리포지토리** `app/repositories/academy.py`
   ```python
   class AcademyRepository:
       def __init__(self, session: AsyncSession) -> None:
           self.session = session

       async def get(self, academy_id: UUID) -> Academy | None:
           return await self.session.get(Academy, academy_id)
   ```
4. **서비스** `app/services/academy.py` — 권한 확인, 없으면 `NotFoundError()`
   ```python
   class AcademyService:
       def __init__(self, session: AsyncSession) -> None:
           self.academies = AcademyRepository(session)

       async def get_for_member(self, academy_id: UUID, user: AuthenticatedUser) -> Academy:
           academy = await self.academies.get(academy_id)
           if academy is None:  # + 멤버십 확인
               raise NotFoundError("Academy not found")
           return academy
   ```
5. **엔드포인트** `app/api/v1/endpoints/academies.py`
   ```python
   router = APIRouter(prefix="/academies", tags=["academies"])

   @router.get("/{academy_id}")
   async def get_academy(academy_id: UUID, user: CurrentUser, session: DbSession) -> AcademyRead:
       academy = await AcademyService(session).get_for_member(academy_id, user)
       return AcademyRead.model_validate(academy)
   ```
6. **라우터 등록** `app/api/v1/router.py`: `api_v1_router.include_router(academies.router)`
7. **테스트** `tests/api/test_academies.py`: 정상, 401(토큰 없음), 404(다른 학원), 422(잘못된 UUID)
8. 문서: 엔티티가 바뀌었다면 `docs/database-design.md` 갱신

규칙 요약
- 보호 API에는 반드시 `CurrentUser` (공개 API는 PR에서 명시적으로 이유 설명)
- 라우터에서 SQL·`HTTPException` 직접 사용 금지 → 서비스에서 `AppError` 하위 예외
- 응답은 항상 Pydantic 스키마(ORM 객체 직접 반환 금지), 목록은 `Page[T]` + `PaginationQuery`
- 쓰기 작업은 서비스에서 `await session.commit()`

## 6. 테스트 규칙

- 위치: `tests/` 아래 소스 구조를 따라 배치 (`tests/api/`, `tests/services/`)
- 앱은 `create_app(make_settings(...))`로 만들고, `running_client()`로 lifespan까지 실행
- 테스트는 `backend/.env`와 운영 DB에 접근하지 않습니다. 외부 API(Supabase, STT, LLM)는 Mock
- 실제 DB가 필요한 테스트는 `@pytest.mark.integration` + `TEST_DATABASE_URL` (CI에서 Postgres 컨테이너로 실행)

## 7. 버전 완료 체크리스트

`develop` → `main` 병합 전에 확인합니다.

- [ ] 버전 범위의 기능 PR이 모두 `develop`에 merge됨
- [ ] CI 통과 (lint, format, test, integration, alembic, docker)
- [ ] 로컬에서 `uv sync && uv run pytest` 통과 (두 개발자 모두)
- [ ] 새 마이그레이션을 깨끗한 DB에 `upgrade head` → `downgrade base` → `upgrade head` 확인
- [ ] `.env.example`, README, docs/* 최신화
- [ ] `APP_VERSION`, `pyproject.toml`의 version 갱신
- [ ] 보호 API에 인증·학원 권한이 적용되었는지 상호 리뷰
- [ ] 비밀값·개인정보가 커밋/로그에 없는지 확인
- [ ] `develop` → `main` PR merge 후 태그: `git tag v0.x.0 && git push origin v0.x.0`
- [ ] 운영 배포 시: DB 백업 확인 → 마이그레이션 수동 적용 → 배포 → `/health`, `/api/v1/health/db` 확인

## 8. 운영 절차 (v0.2~)

### 8.1 Supabase DB에 마이그레이션 적용

마이그레이션은 서버 기동이나 CI에서 자동 적용하지 않습니다. 리뷰된 리비전을 사람이 적용합니다.

```bash
cd backend
# 0) 대상 확인: backend/.env 의 DATABASE_URL 이 의도한 프로젝트(개발/운영)인지 확인
uv run alembic current                       # 현재 리비전 (처음이면 비어 있음)
uv run alembic upgrade head --sql > ../migration-preview.sql   # 1) 실행될 SQL 미리 보기 (커밋하지 말 것)
# 2) 운영 DB라면: Supabase 대시보드에서 백업(또는 PITR) 확인
uv run alembic upgrade head                  # 3) 적용
uv run alembic check                         # 4) 모델과 일치 확인 → "No new upgrade operations detected."
```

- 운영(`APP_ENV=production`)은 `ALLOW_PRODUCTION_MIGRATIONS=true`를 함께 지정해야만 실행됩니다.
- 적용 후 Supabase 대시보드 → Table Editor에서 모든 앱 테이블(0001: 4개, 0002: 10개)에 **RLS enabled**가 표시되는지, `profiles`에 `fk_profiles_id_auth_users` FK가 생겼는지 확인합니다.
- 0002는 `academy_memberships`에 `uq(academy_id, id)`를 추가합니다. 기존 행이 있어도 `id`가 PK라 항상 성공합니다.
- 되돌리기: `uv run alembic downgrade -1`. 이 경우 테이블과 데이터가 삭제되므로 운영에서는 사용하지 않습니다.

### 8.1a Supabase Storage 설정 (v0.4, 한 번만)

작품 사진(v0.4)과 피드백 녹음(v0.5)은 비공개 버킷 `artworks`, `feedback-audio`와 `storage.objects` RLS 정책이 필요합니다. 이것들은 Supabase 전용이라 Alembic이 아니라 `backend/supabase/storage-setup.sql`로 적용합니다.

1. Alembic `0004`까지 적용 (권한 함수 `artmate_private.can_access_artwork_object`, `manages_student`, `can_access_recording_object` 생성)
2. Supabase 대시보드 → SQL Editor에서 `backend/supabase/storage-setup.sql` 실행 (여러 번 실행해도 안전)
3. 확인: Storage → `artworks`, `feedback-audio` 버킷이 **Private**, Policies에 `artmate_artworks_*` 3개 + `artmate_audio_*` 3개
4. Settings → API → Exposed schemas에 `artmate_private`를 **추가하지 않습니다**
5. 백엔드 환경변수 `SUPABASE_URL`, `SUPABASE_ANON_KEY`(공개 키) 설정. service_role 키는 넣지 않습니다
6. 적용 결과 확인: `uv run python -m scripts.verify_dev_environment` (읽기 전용, [supabase-dev-verification.md](supabase-dev-verification.md))

### 8.1b 리비전 순서와 v0.5.1 적용 규칙

- 현재 head: `0006` (v0.6). 다음 리비전(v0.7)은 `--rev-id 0007`, `down_revision = "0006"`.
- `0006`도 `0005`와 같이 팀 승인 후 개발 DB에 적용합니다 (2026-11-09 기준 개발 DB는 `0004`).
- 개발 DB에는 프론트엔드 담당자가 `0002~0004`와 storage-setup.sql을 적용합니다. 백엔드 담당자는 같은 작업을 반복하지 않고 검증 스크립트로 확인만 합니다.
- `0005`는 팀 승인 후 한 사람만 개발 DB에 적용합니다. 운영 DB 적용은 별도 배포 절차로만 합니다.
- v0.5.1에서 제외한 기능(출석·오늘 할 일·질문 콜·시험 타이머)의 테이블은 보존 중입니다. 물리 삭제는 데이터 확인·승인 후 별도 리비전으로 진행합니다 ([v0.5.1-planning-changes.md §5](v0.5.1-planning-changes.md)).

### 8.1c AI Worker 실행 (v0.6)

```bash
cd backend
uv sync --extra stt                     # faster-whisper 설치 (Worker 전용)
STT_ENABLED=true AI_SUMMARY_ENABLED=true GEMINI_API_KEY=... uv run python -m app.worker
docker build --target worker -t artmate-worker .   # 배포 이미지 (API 이미지는 기본 target)
```

- API 서버와 같은 `DATABASE_URL`을 사용합니다. `GEMINI_API_KEY`는 Worker에만 두고 유료 등급 키를 씁니다.
- 실제 Gemini 호출·실제 학생 데이터 전송은 승인과 동의가 준비된 뒤에만 합니다. 자동 테스트는 가짜 STT·LLM을 씁니다.
- 자세한 구조·자원·비용: [ai-feedback-v0.6.md](ai-feedback-v0.6.md)

### 8.2 시스템 관리자(ADMIN) 지정

ADMIN은 API로 만들 수 없습니다. 대상 사용자가 먼저 가입하고 프로필을 생성한 뒤, Supabase 대시보드 → SQL Editor에서 실행합니다.

```sql
-- user id 는 Authentication > Users 에서 확인
UPDATE profiles SET user_type = 'ADMIN', updated_at = now()
WHERE id = '<user-uuid>';
```

- 지정·해제 시 날짜, 대상, 사유를 팀 문서에 기록합니다(감사 로그 기능은 후속 구현).
- ADMIN 계정은 학원에 소속할 수 없으므로, 강사로도 활동할 사람은 별도 계정을 씁니다.

### 8.3 계정 비활성화

```sql
UPDATE profiles SET is_active = false, updated_at = now() WHERE id = '<user-uuid>';
```

다음 요청부터 보호 API가 403 `ACCOUNT_DISABLED`를 반환합니다. 이미 발급된 토큰에도 즉시 적용됩니다.

### 8.4 로컬 테스트 DB

DB 기반 테스트(`tests/db/`)는 `TEST_DATABASE_URL`이 있을 때만 실행됩니다. 이 값은 **로컬 DB만** 허용됩니다. Supabase 호스트이거나 원격 호스트이면 테스트가 중단됩니다.

```bash
# 예: 로컬 PostgreSQL (Docker 또는 설치형)
docker run -d --name artmate-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=artmate_test -p 5432:5432 postgres:16
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/artmate_test uv run pytest
```

테스트는 시작할 때 `alembic downgrade base` → `upgrade head`를 실행하고, 테스트마다 테이블을 비웁니다. **개발용 데이터가 있는 DB를 지정하지 마세요.** PR에서는 CI의 임시 PostgreSQL로 자동 실행됩니다.
