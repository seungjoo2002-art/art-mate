"""외부 AI 전송 동의의 유효성 판정 (v0.9.6). API와 Worker가 같은 규칙을 쓴다.

근거 (2026-11 확인, 법률 검토 전)
- OpenAI Under-18 API guidance: 미성년자(18세 미만)에게 안전하고 연령에 맞는 콘텐츠, 연령에 맞는
  AI 안내, 필터·모니터링, 필요 시 연령 확인, 최신 주력 모델. "13세 미만 또는 해당 지역의 디지털 동의
  연령 미만" 아동의 개인정보는 ZDR을 먼저 적용하기 전에는 처리하지 않는다. (보호자 동의 언급 없음)
- 개인정보 보호법 제22조의2: 만 14세 미만은 법정대리인 동의 + 동의 확인(시행령 제17조의2).
  만 14세 이상은 본인 동의 가능. → 한국의 "디지털 동의 연령"을 만 14세로 보고 만 14세 미만을 ZDR
  대상으로 본다 (보수적 해석 — 법률 검토로 확정).
- 국외 이전(제28조의8): AI 전송 동의서에서 별도 동의로 받는다.

판정 순서 (모두 만족해야 유효)
1. 철회되지 않음, 현재 동의서 버전, 현재 제공자(AI_PROVIDER), 연령 구간 기록
2. ADULT: 유효
3. TEEN(만 14~17세): AI_TEENS_ENABLED가 켜져 있어야 함. AI_TEEN_GUARDIAN_REQUIRED면 보호자 확인도
4. UNDER_14: AI_UNDER14_ENABLED와 AI_ZDR_APPROVED가 모두 켜져 있고 법정대리인 확인이 있어야 함
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
TEEN_NOT_ENABLED = "TEEN_NOT_ENABLED"  # 만 14~17세 전송을 운영자가 아직 허용하지 않음
UNDER_14_BLOCKED = "UNDER_14_BLOCKED"  # 만 14세 미만 (법정대리인 확인 방법·ZDR 승인 전)


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
    if age < 14:
        return AiAgeBand.UNDER_14
    if age < 18:
        return AiAgeBand.TEEN
    return AiAgeBand.ADULT


def needs_guardian(band: AiAgeBand | None, settings: Settings) -> bool:
    """이 연령 구간에 보호자(법정대리인) 확인이 필요한지."""
    if band == AiAgeBand.UNDER_14:
        return True
    return band == AiAgeBand.TEEN and settings.ai_teen_guardian_required


@dataclass(frozen=True)
class ConsentState:
    is_valid: bool
    reason: str | None  # NOT_CONSENTED / TEEN_NOT_ENABLED / UNDER_14_BLOCKED / GUARDIAN_PENDING


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
    band = consent.age_band
    if band == AiAgeBand.TEEN and not settings.ai_teens_enabled:
        return ConsentState(False, TEEN_NOT_ENABLED)
    if band == AiAgeBand.UNDER_14 and not (
        settings.ai_under14_enabled and settings.ai_zdr_approved
    ):
        return ConsentState(False, UNDER_14_BLOCKED)
    if needs_guardian(band, settings) and consent.guardian_confirmed_at is None:
        return ConsentState(False, GUARDIAN_PENDING)
    return ConsentState(True, None)


def new_guardian_token(now: datetime) -> tuple[str, str, datetime]:
    """(원문 토큰, SHA-256, 만료 시각). 원문은 응답으로 한 번만 돌려주고 저장하지 않는다."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token), now + timedelta(days=GUARDIAN_LINK_DAYS)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
