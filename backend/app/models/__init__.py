"""SQLAlchemy ORM 모델.

새 모델을 추가하면 반드시 이 파일에서 import 하세요. Alembic autogenerate는
`app.models`를 import 한 뒤 `Base.metadata`를 비교하므로, 여기 없는 모델은 감지되지 않습니다.
설계는 docs/database-design.md 참고.
"""

from app.db.base import Base
from app.models.academy import Academy
from app.models.membership import AcademyJoinRequest, AcademyMembership
from app.models.profile import Profile

__all__ = ["Academy", "AcademyJoinRequest", "AcademyMembership", "Base", "Profile"]
