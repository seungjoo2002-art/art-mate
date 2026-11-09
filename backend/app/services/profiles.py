from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode, ForbiddenError, NotFoundError
from app.core.security import AuthenticatedUser
from app.models.profile import Profile
from app.repositories.profiles import ProfileRepository
from app.schemas.user import ProfileCreate, ProfileUpdate


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.profiles = ProfileRepository(session)

    async def get_me(self, user: AuthenticatedUser) -> Profile:
        profile = await self.profiles.get(user.user_id)
        if profile is None:
            raise NotFoundError("Profile has not been created", code=ErrorCode.PROFILE_NOT_FOUND)
        return profile

    async def create_me(self, user: AuthenticatedUser, data: ProfileCreate) -> tuple[Profile, bool]:
        """프로필 생성 (멱등). 이미 있으면 기존 프로필을 그대로 반환한다 (값을 바꾸지 않음).

        회원가입 직후 생성이 실패했거나 중복 요청이 와도 다시 호출하면 복구된다.
        """
        created = await self.profiles.insert_if_absent(
            user.user_id, data.display_name, data.user_type, data.practical_type
        )
        await self.session.commit()
        profile = await self.profiles.get(user.user_id)
        assert profile is not None
        return profile, created

    async def update_me(self, profile: Profile, data: ProfileUpdate) -> Profile:
        # 다른 사용자의 Storage 파일을 자기 프로필 이미지로 지정하지 못하게 한다
        if data.avatar_path is not None and not data.avatar_path.startswith(
            f"avatars/{profile.id}/"
        ):
            raise ForbiddenError("avatar_path must be inside your own avatars folder")
        locked = await self.profiles.get_for_update(profile.id)
        assert locked is not None
        for field_name in data.model_fields_set:
            setattr(locked, field_name, getattr(data, field_name))
        await self.session.commit()
        await self.session.refresh(locked)
        return locked
