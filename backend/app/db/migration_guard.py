"""Alembic 실행 대상 안전장치.

운영 DB(Supabase)에 대한 마이그레이션은 사람이 명시적으로 허용했을 때만 실행한다.
`APP_ENV=production` 뿐 아니라, 개발 설정(.env)이 실수로 운영 Supabase를 가리키는 경우도 막는다
(2026-11-16: 로컬 backend/.env가 APP_ENV=development 로 운영 DB를 가리키고 있던 사례).
"""

from sqlalchemy.engine import make_url

ALLOW_ENV = "ALLOW_PRODUCTION_MIGRATIONS"
SUPABASE_HOST_SUFFIXES = (".supabase.co", ".supabase.com")


def is_supabase_host(database_url: str) -> bool:
    host = (make_url(database_url).host or "").lower().rstrip(".")
    return host.endswith(SUPABASE_HOST_SUFFIXES)


def migration_block_reason(app_env: str, database_url: str, allow: str | None) -> str | None:
    """마이그레이션을 막아야 하면 사용자에게 보여줄 이유를, 아니면 None."""
    if allow == "true":
        return None
    if app_env == "production":
        return "APP_ENV=production"
    if is_supabase_host(database_url):
        return "DATABASE_URL이 Supabase(운영) 호스트"
    return None
