import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PracticalType, UserType
from app.models.profile import Profile


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> Profile | None:
        return await self.session.get(Profile, user_id)

    async def insert_if_absent(
        self,
        user_id: uuid.UUID,
        display_name: str,
        user_type: UserType,
        practical_type: PracticalType | None = None,
        real_name: str | None = None,
    ) -> bool:
        """프로필이 없을 때만 생성한다 (동시·중복 요청에도 안전). 생성했으면 True."""
        stmt = (
            insert(Profile)
            .values(
                id=user_id,
                display_name=display_name,
                user_type=user_type,
                practical_type=practical_type,
                real_name=real_name,
            )
            .on_conflict_do_nothing(index_elements=[Profile.id])
            .returning(Profile.id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def get_for_update(self, user_id: uuid.UUID) -> Profile | None:
        stmt = select(Profile).where(Profile.id == user_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()
