# 배포 전 DB 스키마 버전 확인 절차 (v0.9.9)

> 배경: 2026-11-13 v0.9.8(PR #60)이 운영 DB 마이그레이션 0015보다 먼저 배포되어, 코드가 DB에 없는 컬럼·테이블을 조회하면서 작품·첨삭·녹음 API 대부분이 500이 됐다. 당시 `/health/db`는 `ok`였다.

## 1. 원칙

1. **마이그레이션 먼저, 코드 나중.** 운영 DB에 새 revision을 적용한 뒤 그 revision을 요구하는 코드를 배포한다.
2. 그래서 마이그레이션은 **이전 코드와 호환**되게 작성한다 (컬럼·테이블 추가, 기본값 있는 NOT NULL, 제약 완화 등). 컬럼 삭제·이름 변경은 코드에서 먼저 사용을 없앤 다음 릴리스에서 한다.
3. Render·worker는 마이그레이션을 실행하지 않는다 (Dockerfile CMD는 uvicorn만).

## 2. 판정 (코드·`/health/db`·CI 공통, `app/db/schema_version.py`)

| 상태 | 뜻 | `/health/db` | CI `db-revision` |
| --- | --- | --- | --- |
| `ok` | DB revision = 코드 head | 200 | 통과 |
| `ahead` | DB가 더 새 버전 (마이그레이션 선적용, 정상 순서) | 200 + 경고 로그 | 통과 |
| `behind` | **코드가 DB보다 새 버전 (v0.9.8 장애 상황)** | **503 `DATABASE_SCHEMA_MISMATCH`** | **실패** |
| `missing` | `alembic_version` 없음·비어 있음 | 503 `DATABASE_SCHEMA_MISMATCH` | 실패 |
| `unknown` | 배포물에 마이그레이션 파일 없음 | 200 + 경고 로그 | 통과 |

응답·로그에는 revision 번호만 나온다 (접속 정보 없음). 예:

```json
{"error": {"code": "DATABASE_SCHEMA_MISMATCH",
           "details": {"schema_status": "behind", "db_revision": "0014", "code_revision": "0015"}}}
```

## 3. 릴리스 절차

**마이그레이션이 없는 PR**: CI `db-revision`이 통과하면 그대로 병합·배포.

**마이그레이션이 있는 PR** (예: 0016):

1. PR에서 CI `db-revision`이 실패한다 (`behind`) — 정상. 병합하지 않는다.
2. 운영 DB 백업 확인.
3. PR 브랜치에서 리뷰된 마이그레이션 적용 (운영 대상은 명시적 허용 필요):
   ```bash
   cd backend
   ENV_FILE=.env.production ALLOW_PRODUCTION_MIGRATIONS=true uv run alembic upgrade head
   ```
4. 확인: `ENV_FILE=.env.production uv run python -m scripts.check_db_revision` → `schema_status=ok`
   (이 시점의 운영 코드는 `ahead`로 계속 정상 동작)
5. PR의 `db-revision` 체크 재실행 → 통과 → 병합 → Vercel·Render 자동 배포
6. 배포 후 `GET /api/v1/health/db` → `schema_status: "ok"`

## 4. 자동 차단 설정 (운영자, 1회)

`db-revision-guard.yml`은 PR과 main push에서 운영 DB revision을 읽기 전용으로 확인한다 (`WORKER_DATABASE_URL` Secret 사용, SELECT만).

| 위치 | 설정 | 효과 |
| --- | --- | --- |
| GitHub → Settings → Branches → `main` 보호 규칙 | Required status check: `db-revision` | `behind`인 PR은 병합 불가 |
| Render → 서비스 → Settings → Build & Deploy → Auto-Deploy | **After CI Checks Pass** | main push의 체크가 실패하면 Render가 배포하지 않음 |
| Render → Settings → Health Check Path (선택) | `/api/v1/health/db` | 새 배포가 `behind`면 헬스체크 실패 → 이전 버전 유지. `ahead`는 200이라 마이그레이션 선적용 중 재시작 루프 없음. 단 DB 일시 장애(503)에도 배포가 실패할 수 있다 |

Vercel(프론트)은 DB를 직접 쓰지 않지만 새 API를 부를 수 있으므로, 백엔드 배포가 막힌 동안 프론트도 병합하지 않는다 (같은 PR이면 병합 자체가 막힌다).

## 5. 점검 명령

```bash
cd backend
ENV_FILE=.env.production uv run python -m scripts.check_db_revision   # 운영 (읽기 전용)
curl -s https://art-mate-dwc9.onrender.com/api/v1/health/db             # 배포된 코드 기준
```

종료 코드: 0 배포 가능 · 1 배포하면 장애 · 2 점검 불가(설정·연결).
