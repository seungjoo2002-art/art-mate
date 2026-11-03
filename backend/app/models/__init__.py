"""SQLAlchemy ORM 모델.

새 모델을 추가하면 반드시 이 파일에서 import 하세요. Alembic autogenerate는
`app.models`를 import 한 뒤 `Base.metadata`를 비교하므로, 여기 없는 모델은 감지되지 않습니다.

    from app.models.academy import Academy  # noqa: F401

v0.1에는 엔티티 모델이 없습니다. 설계는 docs/database-design.md 참고.
"""

from app.db.base import Base

__all__ = ["Base"]
