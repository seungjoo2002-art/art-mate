"""AI 전송 동의 판정 (v0.9.6): 연령 구간, 보호자 확인, 13세 미만 차단, 제공자·버전."""

import datetime as dt
import uuid
from datetime import date

import pytest

from app.models.ai_feedback import AiProcessingConsent
from app.models.enums import AiAgeBand, AiConsentPurpose, AiProvider, ConsentGrantor
from app.services import ai_consent_policy as policy
from tests.conftest import make_settings

TODAY = date(2026, 11, 12)
PURPOSE = AiConsentPurpose.FEEDBACK_SUMMARY


@pytest.mark.parametrize(
    ("birth", "band"),
    [
        ("2014-01", AiAgeBand.UNDER_13),  # 12세
        ("2013-12", AiAgeBand.UNDER_13),  # 12월 말 생일 가정 → 아직 12세 (보수적)
        ("2013-10", AiAgeBand.MINOR),  # 13세
        ("2008-12", AiAgeBand.MINOR),  # 17세 (12월 말 생일 가정)
        ("2008-10", AiAgeBand.ADULT),  # 18세
        ("1990-05", AiAgeBand.ADULT),
    ],
)
def test_age_band_is_conservative(birth: str, band: AiAgeBand) -> None:
    assert policy.age_band(birth, TODAY) == band


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
        "granted_at": dt.datetime(2026, 11, 12, tzinfo=dt.UTC),
        "revoked_at": None,
        "age_band": AiAgeBand.ADULT,
        "guardian_confirmed_at": None,
    }
    return AiProcessingConsent(**(values | overrides))


def test_evaluate_rules() -> None:
    settings = make_settings()
    now = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)

    def state(consent, s=settings):  # type: ignore[no-untyped-def]
        result = policy.evaluate(consent, s, PURPOSE)
        return (result.is_valid, result.reason)

    assert state(_consent()) == (True, None)
    assert state(None) == (False, "NOT_CONSENTED")
    assert state(_consent(revoked_at=now)) == (False, "NOT_CONSENTED")
    assert state(_consent(policy_version="2026-11-ai-v1")) == (False, "NOT_CONSENTED")
    # 이전 제공자(Gemini) 동의로는 OpenAI 전송 불가
    assert state(_consent(provider=AiProvider.GOOGLE_GEMINI)) == (False, "NOT_CONSENTED")
    # 연령 확인 없는 이전 동의
    assert state(_consent(age_band=None)) == (False, "NOT_CONSENTED")
    # 미성년자: 보호자 확인 전/후
    assert state(_consent(age_band=AiAgeBand.MINOR)) == (False, "GUARDIAN_PENDING")
    assert state(_consent(age_band=AiAgeBand.MINOR, guardian_confirmed_at=now)) == (True, None)
    # 13세 미만: 보호자 확인이 있어도 ZDR 승인 전에는 차단
    under13 = _consent(age_band=AiAgeBand.UNDER_13, guardian_confirmed_at=now)
    assert state(under13) == (False, "UNDER_13_BLOCKED")
    assert state(_consent(age_band=AiAgeBand.UNDER_13)) == (False, "GUARDIAN_PENDING")
    assert state(under13, make_settings(ai_zdr_approved=True)) == (True, None)
    # 학년은 쓰지 않음: 판정에 grade 입력 자체가 없다


def test_guardian_token_is_hashed_and_expires() -> None:
    now = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)
    token, digest, expires = policy.new_guardian_token(now)
    assert len(token) >= 40 and digest == policy.hash_token(token) and digest != token
    assert expires - now == dt.timedelta(days=policy.GUARDIAN_LINK_DAYS)
