"""v1.3 AI 수정본 단위 테스트 (DB·네트워크 없음).

OpenAI 이미지 수정 클라이언트(MockTransport), 프롬프트, 원본 이미지 정리(EXIF·GPS 제거), 크기 선택,
요청 해시, 비용, 동의 규칙, 설정.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime

import httpx
import pytest
from PIL import Image

from app.core.config import ConfigurationError, load_settings
from app.integrations.ai.openai_image import (
    EditImage,
    ImageEditError,
    OpenAiImageEditor,
    build_image_editor,
    safety_identifier,
)
from app.models.ai_feedback import AiProcessingConsent
from app.models.enums import AiAgeBand, AiConsentPurpose, AiProvider, ArtworkStage
from app.services import ai_consent_policy as policy
from app.services.ai_revision_candidates import candidate_key, normalize
from app.services.ai_revision_images import (
    InvalidImage,
    choose_size,
    inspect_result,
    prepare_source,
)
from app.services.ai_revision_prompt import build_prompt
from app.services.ai_revisions import estimate_cost, request_hash
from tests.conftest import make_settings
from tests.fake_storage import image_bytes

KEY = "sk-test-secret-key"
IMPROVEMENTS = [
    {
        "key": "a",
        "category": "FORM",
        "category_label": "형태",
        "kind": "WEAKNESS",
        "kind_label": "부족한 점",
        "text": "유리병 입구 타원이 납작하다.",
    },
    {
        "key": "b",
        "category": "VALUE",
        "category_label": "명암",
        "kind": "FIX",
        "kind_label": "수정 방법",
        "text": "주제부의 명암 대비를 강화한다.",
    },
]


def _settings(**overrides):  # type: ignore[no-untyped-def]
    return make_settings(openai_api_key=KEY, image_edit_enabled=True, **overrides)


def _editor(handler, **overrides) -> OpenAiImageEditor:  # type: ignore[no-untyped-def]
    return OpenAiImageEditor(_settings(**overrides), transport=httpx.MockTransport(handler))


def _ok_body() -> dict:  # type: ignore[type-arg]
    return {
        "created": 1,
        "data": [{"b64_json": base64.b64encode(image_bytes("JPEG", (40, 60))).decode()}],
        "output_format": "jpeg",
        "usage": {
            "input_tokens": 1500,
            "output_tokens": 1400,
            "input_tokens_details": {"image_tokens": 1200, "text_tokens": 300},
        },
    }


async def _edit(editor: OpenAiImageEditor):  # type: ignore[no-untyped-def]
    return await editor.edit(
        images=[EditImage(image_bytes("JPEG"), "image/jpeg", "artwork.jpg")],
        prompt="prompt",
        size="1024x1536",
        user_key="user-123",
    )


# ============================================================================ OpenAI 클라이언트


async def test_edit_request_and_response() -> None:
    seen: dict = {}  # type: ignore[type-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json=_ok_body())

    result = await _edit(_editor(handler))
    assert seen["url"] == "https://api.openai.com/v1/images/edits"
    assert seen["auth"] == f"Bearer {KEY}"
    body = seen["body"].decode("latin-1")
    for field, value in [
        ("model", "gpt-image-2.5-flare"),
        ("quality", "medium"),
        ("size", "1024x1536"),
        ("output_format", "jpeg"),
        ("n", "1"),
    ]:
        assert f'name="{field}"\r\n\r\n{value}\r\n' in body
    # 사용자 ID 원문이 아닌 해시만
    assert safety_identifier("user-123") in body and "user-123" not in body
    assert 'name="image"; filename="artwork.jpg"' in body
    assert (result.input_tokens, result.input_image_tokens, result.output_tokens) == (
        1500,
        1200,
        1400,
    )
    assert Image.open(io.BytesIO(result.image)).size == (40, 60)


async def test_two_images_use_array_field() -> None:
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(200, json=_ok_body())

    await _editor(handler).edit(
        images=[
            EditImage(b"a", "image/jpeg", "artwork.jpg"),
            EditImage(b"b", "image/jpeg", "reference.jpg"),
        ],
        prompt="p",
        size="1024x1024",
        user_key="u",
    )
    assert bodies[0].count(b'name="image[]"') == 2


@pytest.mark.parametrize(
    ("status", "error", "code", "retryable"),
    [
        (429, {"code": "rate_limit_exceeded"}, "IMAGE_RATE_LIMITED", True),
        (429, {"code": "insufficient_quota"}, "IMAGE_QUOTA_EXCEEDED", False),
        (500, {}, "IMAGE_UNAVAILABLE", True),
        (503, {}, "IMAGE_UNAVAILABLE", True),
        (504, {}, "IMAGE_RESULT_UNKNOWN", False),
        (401, {"code": "invalid_api_key"}, "IMAGE_AUTH_FAILED", False),
        (403, {}, "IMAGE_AUTH_FAILED", False),
        (404, {"code": "model_not_found"}, "IMAGE_MODEL_UNAVAILABLE", False),
        (400, {"code": "moderation_blocked"}, "IMAGE_BLOCKED", False),
        (400, {"code": "invalid_value"}, "IMAGE_BAD_REQUEST", False),
    ],
)
async def test_error_mapping(status: int, error: dict, code: str, retryable: bool) -> None:  # type: ignore[type-arg]
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "secret detail", **error}})

    with pytest.raises(ImageEditError) as caught:
        await _edit(_editor(handler))
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert KEY not in str(caught.value) and "secret detail" not in str(caught.value)


@pytest.mark.parametrize(
    ("exc", "code", "retryable", "called"),
    [
        (httpx.ConnectError("x"), "IMAGE_UNAVAILABLE", True, False),
        (httpx.ConnectTimeout("x"), "IMAGE_UNAVAILABLE", True, False),
        (httpx.WriteTimeout("x"), "IMAGE_UNAVAILABLE", True, False),
        # 응답 대기 중 시간 초과·끊김: 처리됐을 수 있어 재호출하지 않는다
        (httpx.ReadTimeout("x"), "IMAGE_RESULT_UNKNOWN", False, True),
        (httpx.RemoteProtocolError("x"), "IMAGE_RESULT_UNKNOWN", False, True),
    ],
)
async def test_network_errors(exc: Exception, code: str, retryable: bool, called: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    with pytest.raises(ImageEditError) as caught:
        await _edit(_editor(handler))
    assert (caught.value.code, caught.value.retryable, caught.value.called) == (
        code,
        retryable,
        called,
    )


async def test_empty_or_broken_result_is_not_retried() -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    with pytest.raises(ImageEditError) as caught:
        await _edit(_editor(empty))
    assert caught.value.code == "IMAGE_EMPTY_RESPONSE" and caught.value.retryable is False

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(ImageEditError) as caught:
        await _edit(_editor(broken))
    assert caught.value.code == "IMAGE_INVALID_RESPONSE"


def test_model_quality_and_size_come_from_settings() -> None:
    editor = OpenAiImageEditor(
        _settings(image_edit_model="gpt-image-2.5-sunburst", image_edit_quality="high")
    )
    assert editor.model_name == "gpt-image-2.5-sunburst"
    form = editor._form("p", "1024x1024", "u")
    assert form["quality"] == "high" and form["output_compression"] == "90"


def test_editor_built_only_when_enabled_and_keyed() -> None:
    assert build_image_editor(make_settings(openai_api_key=KEY)) is None  # 꺼짐
    assert build_image_editor(make_settings(image_edit_enabled=True)) is None  # 키 없음
    assert build_image_editor(_settings()) is not None
    # 배포 환경: 운영자 확인 두 가지가 모두 있어야
    prod = dict(app_env="production", database_url="postgresql://u:p@localhost/db")
    assert build_image_editor(_settings(**prod)) is None
    assert build_image_editor(_settings(**prod, ai_provider_terms_confirmed=True)) is None
    assert (
        build_image_editor(
            _settings(**prod, ai_provider_terms_confirmed=True, image_edit_operator_confirmed=True)
        )
        is not None
    )


# ============================================================================ 프롬프트


def test_prompt_includes_rules_and_selected_improvements_only() -> None:
    sketch = build_prompt(
        stage=ArtworkStage.SKETCH,
        stage_name="스케치",
        subject="유리병과 사과",
        practical_type="소묘",
        has_reference=False,
        improvements=IMPROVEMENTS,
    )
    assert "한국 미대입시 실기 교육을 보조하는 시각적 첨삭 AI" in sketch
    assert "작품 주제: 유리병과 사과" in sketch and "실기 유형: 소묘" in sketch
    assert "1. [형태·부족한 점] 유리병 입구 타원이 납작하다." in sketch
    assert "2. [명암·수정 방법] 주제부의 명암 대비를 강화한다." in sketch
    assert "원본에 없던 채색을 추가하지 마십시오." in sketch
    assert "12. 수정된 작품 이미지 한 장을 출력하십시오." in sketch
    assert "제시물" not in sketch.split("반영해야 하는")[0].split("입력 이미지는")[1][:40]

    progress = build_prompt(
        stage=ArtworkStage.PROGRESS,
        stage_name="채색",
        subject=None,
        practical_type=None,
        has_reference=True,
        improvements=IMPROVEMENTS[:1],
    )
    assert "현재 작업 단계: 중간 작업 (채색)" in progress
    assert "기존에 채색되지 않은 영역을 임의로 완성하지 마십시오." in progress
    assert "두 번째 입력 이미지는 실기시험 제시물(참고) 사진" in progress
    assert "작품 주제: 정보 없음" in progress and "주제부의 명암" not in progress

    final = build_prompt(
        stage=ArtworkStage.FINAL,
        stage_name="완성",
        subject="x",
        practical_type="y",
        has_reference=False,
        improvements=IMPROVEMENTS,
    )
    assert "지적되지 않은 영역까지 과도하게 변경하지 마십시오." in final
    assert "원본에 없던 채색" not in final


# ============================================================================ 이미지


def _jpeg_with_exif(size=(60, 40), orientation: int = 6) -> bytes:  # type: ignore[no-untyped-def]
    image = Image.new("RGB", size, "white")
    exif = Image.Exif()
    exif[0x0112] = orientation  # 90도 회전
    exif[0x8825] = {2: (37.0, 30.0, 0.0)}  # GPS 위도 (위치 정보)
    exif[0x010F] = "PhoneMaker"
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def test_prepare_source_strips_metadata_and_applies_orientation() -> None:
    prepared = prepare_source(_jpeg_with_exif(), max_px=1536)
    with Image.open(io.BytesIO(prepared.data)) as image:
        assert image.size == (40, 60)  # EXIF 방향 적용 (화면에 보이는 방향)
        assert not image.getexif()  # GPS·제조사 등 메타데이터 없음
    assert prepared.content_type == "image/jpeg"


def test_prepare_source_downscales_long_side_keeping_ratio() -> None:
    big = image_bytes("PNG", (3000, 2000))
    prepared = prepare_source(big, max_px=1536)
    assert (prepared.width, prepared.height) == (1536, 1024)
    with pytest.raises(InvalidImage):
        prepare_source(b"not an image", max_px=1536)


def test_inspect_result_and_size_choice() -> None:
    info = inspect_result(image_bytes("JPEG", (30, 50)), max_bytes=10_000_000)
    assert (info.content_type, info.width, info.height) == ("image/jpeg", 30, 50)
    with pytest.raises(InvalidImage):
        inspect_result(b"", max_bytes=10)
    with pytest.raises(InvalidImage):
        inspect_result(image_bytes("JPEG"), max_bytes=10)
    assert choose_size(3000, 4000, "match") == "1024x1536"
    assert choose_size(4000, 3000, "match") == "1536x1024"
    assert choose_size(1000, 1100, "match") == "1024x1024"
    assert choose_size(1000, 1100, "auto") == "auto"


# ============================================================================ 해시·비용·키


def test_request_hash_ignores_order_and_spacing_but_not_settings() -> None:
    settings = {"model": "m", "quality": "medium"}
    a = request_hash("sha", IMPROVEMENTS, settings)
    spaced = [dict(IMPROVEMENTS[1]), {**IMPROVEMENTS[0], "text": "유리병  입구 타원이 납작하다"}]
    assert request_hash("sha", spaced, settings) == a
    assert request_hash("other", IMPROVEMENTS, settings) != a
    assert request_hash("sha", IMPROVEMENTS, {**settings, "quality": "high"}) != a
    assert request_hash("sha", IMPROVEMENTS[:1], settings) != a


def test_estimate_cost_and_candidate_key() -> None:
    cost = estimate_cost(make_settings(), text_tokens=1000, image_tokens=2000, output_tokens=1500)
    assert float(cost) == pytest.approx((1000 * 5 + 2000 * 8 + 1500 * 30) / 1_000_000)
    assert normalize(" 유리병, 입구!  ") == "유리병입구"
    from app.models.enums import FeedbackItemKind, WeaknessCategory

    k = candidate_key(WeaknessCategory.FORM, FeedbackItemKind.WEAKNESS, "타원이 납작하다.")
    assert k == candidate_key(WeaknessCategory.FORM, FeedbackItemKind.WEAKNESS, "타원이 납작하다")
    assert k != candidate_key(WeaknessCategory.FORM, FeedbackItemKind.FIX, "타원이 납작하다")


# ============================================================================ 동의


def _consent(provider: AiProvider, band: AiAgeBand, version: str, **extra) -> AiProcessingConsent:  # type: ignore[no-untyped-def]
    return AiProcessingConsent(
        provider=provider,
        purpose=AiConsentPurpose.VISUAL_CRITIQUE,
        policy_version=version,
        granted_at=datetime.now(UTC),
        revoked_at=None,
        age_band=band,
        **extra,
    )


def test_visual_consent_is_openai_only_and_age_gated() -> None:
    settings = make_settings(ai_provider="gemini")
    purpose = AiConsentPurpose.VISUAL_CRITIQUE
    version = settings.ai_visual_consent_version
    # 요약 제공자가 Gemini여도 작품 이미지는 OpenAI 동의
    assert policy.provider_for(settings, purpose) == AiProvider.OPENAI
    assert policy.required_version(settings, purpose) == version
    adult = _consent(AiProvider.OPENAI, AiAgeBand.ADULT, version)
    assert policy.evaluate(adult, settings, purpose).is_valid
    assert not policy.evaluate(
        _consent(AiProvider.GOOGLE_GEMINI, AiAgeBand.ADULT, version), settings, purpose
    ).is_valid
    assert (
        policy.evaluate(
            _consent(AiProvider.OPENAI, AiAgeBand.ADULT, "old"), settings, purpose
        ).reason
        == policy.NOT_CONSENTED
    )
    teen = _consent(AiProvider.OPENAI, AiAgeBand.TEEN, version)
    assert policy.evaluate(teen, settings, purpose).reason == policy.TEEN_NOT_ENABLED
    # 만 14~17세 작품 이미지: OpenAI 약관 §3.3(c) → 보호자 확인 필수 (설정과 무관)
    teens_on = make_settings(ai_teens_enabled=True, ai_teen_guardian_required=False)
    assert policy.evaluate(teen, teens_on, purpose).reason == policy.GUARDIAN_PENDING
    assert policy.needs_guardian(AiAgeBand.TEEN, teens_on, purpose) is True
    assert (
        policy.needs_guardian(AiAgeBand.TEEN, teens_on, AiConsentPurpose.FEEDBACK_SUMMARY) is False
    )
    confirmed = _consent(
        AiProvider.OPENAI,
        AiAgeBand.TEEN,
        version,
        guardian_confirmed_at=datetime.now(UTC),
        guardian_name="보호자",
    )
    assert policy.evaluate(confirmed, teens_on, purpose).is_valid
    # 만 14세 미만: 운영자 허용 + 조직 ZDR 승인 + ZDR 호환 모델 모두 필요
    child = _consent(
        AiProvider.OPENAI,
        AiAgeBand.UNDER_14,
        version,
        guardian_confirmed_at=datetime.now(UTC),
        guardian_name="보호자",
    )
    open_all = dict(ai_under14_enabled=True, ai_zdr_approved=True)
    assert policy.evaluate(child, make_settings(**open_all), purpose).is_valid
    not_zdr_model = make_settings(**open_all, image_edit_model="gpt-image-2.6-flare")
    assert policy.evaluate(child, not_zdr_model, purpose).reason == policy.UNDER_14_BLOCKED
    assert (
        policy.evaluate(child, make_settings(ai_under14_enabled=True), purpose).reason
        == policy.UNDER_14_BLOCKED
    )


def test_settings_defaults_are_safe() -> None:
    settings = make_settings()
    assert settings.image_edit_enabled is False and settings.image_edit_active is False
    assert settings.image_edit_model == "gpt-image-2.5-flare"
    assert settings.image_edit_quality == "medium"
    assert (settings.image_edit_daily_limit, settings.image_edit_monthly_limit) == (3, 20)
    assert settings.image_edit_max_attempts == 2
    assert settings.image_edit_zdr_compatible is True
    assert make_settings(image_edit_zdr_models="a,b").image_edit_zdr_models == ["a", "b"]
    with pytest.raises(ConfigurationError):
        load_settings(image_edit_size="huge")


def test_no_api_key_in_editor_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    editor = OpenAiImageEditor(_settings())
    assert KEY not in repr(editor.__dict__.get("model_name"))
    assert KEY not in json.dumps(editor._form("p", "auto", "u"))
