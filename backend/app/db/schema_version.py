"""DB 스키마 버전(Alembic revision) 안전장치.

v0.9.8 장애(2026-11-16): 운영 코드가 마이그레이션 0015보다 먼저 배포돼 대부분의 API가 500이 됐다.
`/health/db`와 배포 전 점검(scripts/check_db_revision.py)이 같은 판정을 쓴다.

판정 (운영 DB의 alembic_version ↔ 이 코드에 들어 있는 마이그레이션의 head):
- ok      같음
- ahead   DB가 이 코드가 모르는 더 새 revision → 마이그레이션을 먼저 적용한 정상 배포 순서(경고만).
          마이그레이션은 이전 코드와 호환되게 작성한다는 원칙 (docs/deploy-db-revision-check.md)
- behind  코드가 요구하는 revision이 DB에 아직 없음 → 이 코드는 DB에 없는 컬럼·테이블을 쓴다 (장애)
- missing alembic_version이 없거나 비어 있음 → 스키마를 알 수 없음 (장애로 취급)
- unknown 이 배포물에 마이그레이션 파일이 없어 비교할 수 없음 (확인 불가, 경고만)
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory

# backend/alembic (Docker 이미지에서는 /app/alembic, Dockerfile이 함께 복사한다)
ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"

SchemaStatus = Literal["ok", "ahead", "behind", "missing", "unknown"]
FAILING: frozenset[str] = frozenset({"behind", "missing"})


@dataclass(frozen=True, slots=True)
class CodeRevisions:
    heads: tuple[str, ...]
    known: frozenset[str]


@dataclass(frozen=True, slots=True)
class SchemaCheck:
    status: SchemaStatus
    db_revision: str | None
    code_revision: str | None

    @property
    def failing(self) -> bool:
        return self.status in FAILING


@lru_cache(maxsize=4)
def code_revisions(script_location: str | None = None) -> CodeRevisions | None:
    """이 코드에 들어 있는 마이그레이션의 head와 전체 revision 목록 (파일을 한 번만 읽는다)."""
    path = Path(script_location) if script_location else ALEMBIC_DIR
    if not (path / "versions").is_dir():
        return None
    config = Config()
    config.set_main_option("script_location", str(path))
    script = ScriptDirectory.from_config(config)
    return CodeRevisions(
        heads=tuple(sorted(script.get_heads())),
        known=frozenset(rev.revision for rev in script.walk_revisions()),
    )


def _join(revisions: tuple[str, ...] | list[str]) -> str | None:
    return ",".join(sorted(revisions)) or None


def compare(db_revisions: list[str], code: CodeRevisions | None) -> SchemaCheck:
    db = _join(db_revisions)
    if code is None:
        return SchemaCheck("unknown", db, None)
    head = _join(code.heads)
    if not db_revisions:
        return SchemaCheck("missing", None, head)
    if set(db_revisions) == set(code.heads):
        return SchemaCheck("ok", db, head)
    if any(rev not in code.known for rev in db_revisions):
        return SchemaCheck("ahead", db, head)
    return SchemaCheck("behind", db, head)
