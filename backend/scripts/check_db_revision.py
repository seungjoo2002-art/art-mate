"""배포 전 DB 스키마 버전 점검 (읽기 전용).

이 코드(체크아웃한 커밋)의 Alembic head와 DATABASE_URL이 가리키는 DB의 alembic_version을 비교한다.
판정은 `/health/db`와 같다 (app/db/schema_version.py).

  uv run python -m scripts.check_db_revision            # backend/.env 또는 환경변수 DATABASE_URL
  ENV_FILE=.env.production uv run python -m scripts.check_db_revision

종료 코드: 0 = 배포 가능 (ok·ahead), 1 = 배포하면 장애 (behind·missing), 2 = 점검 불가 (설정·연결).
출력은 판정과 revision 번호뿐이다 (접속 정보는 출력하지 않는다).
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import get_settings
from app.db.schema_version import code_revisions, compare
from app.db.session import Database, build_engine

MESSAGES = {
    "ok": "일치: 배포 가능",
    "ahead": "DB가 더 새 버전 (마이그레이션 선적용): 배포 가능",
    "unknown": "이 체크아웃에 마이그레이션 파일이 없어 비교 불가",
    "behind": "코드가 DB보다 새 버전: 먼저 운영 DB에 마이그레이션 적용 필요 (지금 배포하면 장애)",
    "missing": "DB에 alembic_version이 없음: 스키마를 확인할 수 없음 (배포 중단)",
}


async def _db_revisions() -> list[str]:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not configured")
    database = Database(build_engine(settings, use_null_pool=True))
    try:
        return await database.schema_revisions(timeout_s=15)
    finally:
        await database.dispose()


def main() -> int:
    try:
        revisions = asyncio.run(_db_revisions())
    except Exception as exc:  # 접속 정보가 섞일 수 있어 예외 메시지는 출력하지 않는다
        print(f"check failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    check = compare(revisions, code_revisions())
    print(f"schema_status={check.status} db={check.db_revision} code={check.code_revision}")
    print(MESSAGES[check.status])
    return 1 if check.failing else 0


if __name__ == "__main__":
    sys.exit(main())
