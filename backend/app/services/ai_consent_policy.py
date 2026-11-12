"""외부 AI 전송 동의의 유효성 판정 (v0.9.6). API와 Worker가 같은 규칙을 쓴다.

근거 (2026-11 확인)
- OpenAI Under-18 API guidance: 미성년자 대상 서비스는 연령에 맞는 안전 조치가 필요하고,
  만 13세 미만(또는 각국 디지털 동의 연령 미만)의 개인정보는 데이터 무보관(ZDR)을
  먼저 적용하기 전에는
  OpenAI로 처리하지 않는다.
- OpenAI 약관: 만 18세 미만은 보호자(법정대리인) 허락이 필요 (비즈니스 약관 원문은 자동 조회가 막혀
  운영자가 직접 확인해야 함 → AI_PROVIDER_TERMS_CONFIRMED).
- 개인정보 보호법 제22조의2: 만 14세 미만은 법정대리인 동의 + 동의 확인. 시행령 제17조의2:
  확인을 위해 법정대리인 성명·연락처 수집 가능.

판정 (모두 만족해야 유효)
1. 철회되지 않음, 현재 동의서 버전, 현재 제공자(AI_PROVIDER)
2. 연령 구간이 있음 (v2 동의서부터 기록 — 이전 동의는 무효)
3. MINOR·UNDER_13은 보호자가 확인함 (guardian_confirmed_at)
4. UNDER_13은 운영자가 ZDR 승인(AI_ZDR_APPROVED)을 켰을 때만
0. 미성년자(MINOR·UNDER_13)는 운영자가 AI_MINORS_ENABLED를 켜기 전까지 모두 차단 (배포 기본값)
학년(profiles.grade)은 판정에 쓰지 않는다 (중학생이어도 나이는 다를 수 있음).
"""

from __future__ import annotations

import calendar
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.core.config import Settings
from app.models.ai_feedback import AiProcessingConsent
from app.models.enums import AiAgeBand, AiConsentPurpose, AiProvider

GUARDIAN_LINK_DAYS = 7
_BIRTH = re.compile(r"^(19|20)\d{2}-(0[1-9]|1[0-2])$")

# 화면·API에서 쓰는 사유 코드
NOT_CONSENTED = "NOT_CONSENTED"  # 동의 없음·철회·이전 버전·다른 제공자
GUARDIAN_PENDING = "GUARDIAN_PENDING"  # 보호자 확인 대기
UNDER_13_BLOCKED = "UNDER_13_BLOCKED"  # 만 13세 미만 (ZDR 승인 전)
MINOR_BLOCKED = "MINOR_BLOCKED"  # 미성년자 전송을 운영자가 아직 허용하지 않음


def provider_for(settings: Settings) -> AiProvider:
    return AiProvider.OPENAI if settings.ai_provider == "openai" else AiProvider.GOOGLE_GEMINI


def required_version(settings: Settings, purpose: AiConsentPurpose) -> str:
    if purpose == AiConsentPurpose.GROWTH_COACHING:
        return settings.ai_growth_consent_version
    return settings.ai_consent_version


def parse_birth_year_month(value: str) -> tuple[int, int]:
    if not _BIRTH.match(value):
        raise ValueError("birth_year_month must be YYYY-MM")
    year, month = (int(part) for part in value.split("-"))
    return year, month


def age_band(birth_year_month: str, today: date) -> AiAgeBand:
    """생년월 → 연령 구간. 생일을 그 달 마지막 날로 보아 나이를 적게(보수적으로) 계산한다.

    생년월은 이 계산에만 쓰고 저장하지 않는다. 미래 날짜는 ValueError.
    """
    year, month = parse_birth_year_month(birth_year_month)
    birthday = date(year, month, calendar.monthrange(year, month)[1])
    if birthday > today:
        raise ValueError("birth date is in the future")
    age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    if age < 13:
        return AiAgeBand.UNDER_13
    if age < 18:
        return AiAgeBand.MINOR
    return AiAgeBand.ADULT


def needs_guardian(band: AiAgeBand | None) -> bool:
    return band in (AiAgeBand.UNDER_13, AiAgeBand.MINOR)


@dataclass(frozen=True)
class ConsentState:
    is_valid: bool
    reason: str | None  # 유효하지 않은 이유 (NOT_CONSENTED / GUARDIAN_PENDING / UNDER_13_BLOCKED)


def evaluate(
    consent: AiProcessingConsent | None, settings: Settings, purpose: AiConsentPurpose
) -> ConsentState:
    if (
        consent is None
        or consent.revoked_at is not None
        or consent.policy_version != required_version(settings, purpose)
        or consent.provider != provider_for(settings)
        or consent.age_band is None
    ):
        return ConsentState(False, NOT_CONSENTED)
    # 운영자가 미성년자 전송을 허용하기 전(AI_MINORS_ENABLED=false)에는 보호자 확인과 관계없이 차단
    if needs_guardian(consent.age_band) and not settings.ai_minors_enabled:
        return ConsentState(False, MINOR_BLOCKED)
    if needs_guardian(consent.age_band) and consent.guardian_confirmed_at is None:
        return ConsentState(False, GUARDIAN_PENDING)
    if consent.age_band == AiAgeBand.UNDER_13 and not settings.ai_zdr_approved:
        return ConsentState(False, UNDER_13_BLOCKED)
    return ConsentState(True, None)


def new_guardian_token(now: datetime) -> tuple[str, str, datetime]:
    """(원문 토큰, SHA-256, 만료 시각). 원문은 응답으로 한 번만 돌려주고 저장하지 않는다."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token), now + timedelta(days=GUARDIAN_LINK_DAYS)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
