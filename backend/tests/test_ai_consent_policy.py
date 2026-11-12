"""AI 전송 동의 판정 (v0.9.6): 만 14세 기준 연령 구간, 연령별 운영자 허용, 보호자 확인, ZDR."""

import datetime as dt
import uuid
from datetime import date

import pytest

from app.models.ai_feedback import AiProcessingConsent
from app.models.enums import AiAgeBand, AiConsentPurpose, AiProvider, ConsentGrantor
from app.services import ai_consent_policy as policy
from tests.conftest import make_settings

TODAY = date(2026, 11, 13)
PURPOSE = AiConsentPurpose.FEEDBACK_SUMMARY
NOW = dt.datetime(2026, 11, 13, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("birth", "band"),
    [
        # 만 14세 경계 (생일은 그 달 말일로 가정 → 나이를 적게 계산)
        ("2012-11", AiAgeBand.UNDER_14),  # 11월 말 생일 → 오늘(11-13)은 아직 13세
        ("2012-10", AiAgeBand.TEEN),  # 10월 말 생일 지남 → 14세
        ("2012-12", AiAgeBand.UNDER_14),
        ("2013-01", AiAgeBand.UNDER_14),
        ("2016-05", AiAgeBand.UNDER_14),  # 10세
        # 만 18세 경계
        ("2008-11", AiAgeBand.TEEN),  # 11월 말 생일 → 아직 17세
        ("2008-10", AiAgeBand.ADULT),  # 18세
        ("1990-05", AiAgeBand.ADULT),
    ],
)
def test_age_band_korean_14_and_18_boundaries(birth: str, band: AiAgeBand) -> None:
    assert policy.age_band(birth, TODAY) == band


def test_age_band_exact_birthday_month_end() -> None:
    # 2012-11 생 → 2026-11-30에 만 14세가 된다고 본다
    assert policy.age_band("2012-11", date(2026, 11, 29)) == AiAgeBand.UNDER_14
    assert policy.age_band("2012-11", date(2026, 11, 30)) == AiAgeBand.TEEN


@pytest.mark.parametrize("birth", ["2027-01", "2026-13", "26-01", "1890-01", "2009/03"])
def test_age_band_rejects_invalid(birth: str) -> None:
    with pytest.raises(ValueError):
        policy.age_band(birth, TODAY)


def _consent(**overrides) -> AiProcessingConsent:  # type: ignore[no-untyped-def]
    values = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "provider": AiProvider.OPENAI,
        "purpose": PURPOSE,
        "policy_version": "2026-12-ai-v2",
        "granted_by": ConsentGrantor.SELF,
        "granted_at": NOW,
        "revoked_at": None,
        "age_band": AiAgeBand.ADULT,
        "guardian_confirmed_at": None,
    }
    return AiProcessingConsent(**(values | overrides))


def _state(consent, **settings):  # type: ignore[no-untyped-def]
    result = policy.evaluate(consent, make_settings(**settings), PURPOSE)
    return (result.is_valid, result.reason)


def test_common_rules() -> None:
    assert _state(_consent()) == (True, None)
    assert _state(None) == (False, "NOT_CONSENTED")
    assert _state(_consent(revoked_at=NOW)) == (False, "NOT_CONSENTED")
    assert _state(_consent(policy_version="2026-11-ai-v1")) == (False, "NOT_CONSENTED")
    # 이전 제공자(Gemini) 동의로는 OpenAI 전송 불가
    assert _state(_consent(provider=AiProvider.GOOGLE_GEMINI)) == (False, "NOT_CONSENTED")
    assert _state(_consent(age_band=None)) == (False, "NOT_CONSENTED")  # 연령 확인 없는 이전 동의


def test_teen_self_consent_only_after_operator_enables() -> None:
    teen = _consent(age_band=AiAgeBand.TEEN)
    assert _state(teen) == (False, "TEEN_NOT_ENABLED")  # 배포 기본값: 차단
    assert _state(teen, ai_teens_enabled=True) == (True, None)  # 국내법: 본인 동의
    # 보호자 허락이 필요하다고 판단되면 운영자가 켬
    required = {"ai_teens_enabled": True, "ai_teen_guardian_required": True}
    assert _state(teen, **required) == (False, "GUARDIAN_PENDING")
    assert _state(_consent(age_band=AiAgeBand.TEEN, guardian_confirmed_at=NOW), **required) == (
        True,
        None,
    )
    # 운영자가 끄면 즉시 다시 차단 (보호자 확인과 무관)
    confirmed = _consent(age_band=AiAgeBand.TEEN, guardian_confirmed_at=NOW)
    assert _state(confirmed) == (False, "TEEN_NOT_ENABLED")


def test_under_14_needs_operator_zdr_and_guardian() -> None:
    child = _consent(age_band=AiAgeBand.UNDER_14)
    confirmed = _consent(age_band=AiAgeBand.UNDER_14, guardian_confirmed_at=NOW)
    for settings in (
        {},
        {"ai_under14_enabled": True},  # ZDR 없음
        {"ai_zdr_approved": True},  # 운영자 허용 없음
        {"ai_teens_enabled": True, "ai_zdr_approved": True},  # 청소년 허용은 무관
    ):
        assert _state(confirmed, **settings) == (False, "UNDER_14_BLOCKED")
    both = {"ai_under14_enabled": True, "ai_zdr_approved": True}
    assert _state(child, **both) == (False, "GUARDIAN_PENDING")  # 법정대리인 확인 필수
    assert _state(confirmed, **both) == (True, None)


def test_needs_guardian() -> None:
    assert policy.needs_guardian(AiAgeBand.UNDER_14, make_settings())
    assert not policy.needs_guardian(AiAgeBand.TEEN, make_settings())
    assert policy.needs_guardian(AiAgeBand.TEEN, make_settings(ai_teen_guardian_required=True))
    assert not policy.needs_guardian(AiAgeBand.ADULT, make_settings(ai_teen_guardian_required=True))


def test_guardian_token_is_hashed_and_expires() -> None:
    token, digest, expires = policy.new_guardian_token(NOW)
    assert len(token) >= 40 and digest == policy.hash_token(token) and digest != token
    assert expires - NOW == dt.timedelta(days=policy.GUARDIAN_LINK_DAYS)
