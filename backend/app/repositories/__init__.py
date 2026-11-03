"""DB 접근 계층. AsyncSession을 받아 쿼리만 수행하고, 비즈니스 규칙·커밋 결정은 하지 않는다.

예: repositories/academy.py
    class AcademyRepository:
        async def get(self, academy_id: UUID) -> Academy | None: ...
"""
