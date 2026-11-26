"""AI 수정본 이미지 수정 프롬프트 (v1.3).

버전을 바꾸면 request_hash가 달라져 이전 결과를 재사용하지 않는다.

보내는 것: 작업 단계, 실기 주제, 실기 유형, 제시물 사진 유무, 학생이 고른 개선사항(개인정보 가림
처리).
보내지 않는 것: 음성·전사 원문, 학생·강사 이름, 학원, 작품 제목·자유 메모.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.models.enums import ArtworkStage

PROMPT_VERSION = "visual-critique-v1"

STAGE_LABELS = {
    ArtworkStage.SKETCH: "스케치",
    ArtworkStage.PROGRESS: "중간 작업",
    ArtworkStage.FINAL: "완성",
}

BASE_RULES = """다음 조건을 반드시 준수하여 입력 작품을 수정하십시오.

1. 제공된 개선사항만 작품에 반영하십시오.
2. 학생의 기존 그림체, 표현 기법, 재료 특성을 최대한 유지하십시오.
3. 개선사항과 무관한 사물, 배경, 색상, 형태는 변경하지 마십시오.
4. 새로운 사물이나 장식 요소를 임의로 추가하지 마십시오.
5. 현재 작품의 작업 단계와 완성도를 유지하십시오.
6. 학생이 실제로 따라 수정할 수 있는 현실적인 수준으로 개선하십시오.
7. 원본 작품의 화면 비율과 방향을 최대한 유지하십시오.
8. 실기시험의 출제 주제 및 제시물 조건을 유지하십시오.
9. 이미지에 설명 문구, 워터마크, 화살표, 로고 등을 추가하지 마십시오.
10. 작품 전체를 새로운 그림으로 재창작하지 마십시오.
11. 원본 이미지와 비교했을 때 지적받은 부분의 변화가 확인될 수 있도록 수정하십시오.
12. 수정된 작품 이미지 한 장을 출력하십시오."""

STAGE_RULES = {
    ArtworkStage.SKETCH: """[스케치 단계 추가 조건]
- 연필 또는 기존 스케치 재료의 표현을 유지하십시오.
- 형태, 비례, 구도, 투시 등을 중심으로 수정하십시오.
- 원본에 없던 채색을 추가하지 마십시오.
- 완성된 채색 작품으로 변환하지 마십시오.""",
    ArtworkStage.PROGRESS: """[중간 작업 단계 추가 조건]
- 현재 채색 진행 정도를 유지하십시오.
- 기존에 채색되지 않은 영역을 임의로 완성하지 마십시오.
- 명암, 색채, 입체감, 형태 등 지적된 부분을 중심으로 수정하십시오.
- 기존 채색 재료 및 표현 방식을 유지하십시오.""",
    ArtworkStage.FINAL: """[완성 단계 추가 조건]
- 기존 작품의 전체적인 스타일을 유지하십시오.
- 명암, 색채, 재질, 디테일, 공간감 등 개선사항을 중심으로 수정하십시오.
- 지적되지 않은 영역까지 과도하게 변경하지 마십시오.""",
}


def _one_line(text: str | None, limit: int = 200) -> str:
    value = " ".join((text or "").split())
    return value[:limit] if value else "정보 없음"


def format_improvements(improvements: Sequence[dict[str, Any]]) -> str:
    lines = []
    for i, item in enumerate(improvements, start=1):
        lines.append(
            f"{i}. [{item['category_label']}·{item['kind_label']}] {_one_line(item['text'], 400)}"
        )
    return "\n".join(lines)


def build_prompt(
    *,
    stage: ArtworkStage,
    stage_name: str,
    subject: str | None,
    practical_type: str | None,
    has_reference: bool,
    improvements: Sequence[dict[str, Any]],
) -> str:
    stage_label = STAGE_LABELS[stage]
    stage_text = stage_label if stage_name == stage_label else f"{stage_label} ({stage_name})"
    inputs = (
        "첫 번째 입력 이미지는 학생이 직접 그린 실제 미술 작품이며 수정 대상입니다.\n"
        "두 번째 입력 이미지는 실기시험 제시물(참고) 사진입니다. 제시물 사진은 수정하거나 출력에 "
        "합성하지 말고 사물의 형태·비례 확인용으로만 참고하십시오."
        if has_reference
        else "입력 이미지는 학생이 직접 그린 실제 미술 작품입니다."
    )
    return "\n".join(
        [
            "당신은 한국 미대입시 실기 교육을 보조하는 시각적 첨삭 AI입니다.",
            "",
            inputs,
            "",
            f"작품 주제: {_one_line(subject)}",
            f"실기 유형: {_one_line(practical_type)}",
            f"현재 작업 단계: {stage_text}",
            "",
            "반영해야 하는 개선사항:",
            format_improvements(improvements),
            "",
            BASE_RULES,
            "",
            STAGE_RULES[stage],
        ]
    )
