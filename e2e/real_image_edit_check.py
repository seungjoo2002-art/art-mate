"""v1.3 AI 수정본 실제 OpenAI 이미지 수정 점검 (유료 — 승인된 소량 테스트 전용).

Worker와 같은 코드(원본 정리 → 프롬프트 → OpenAI 이미지 수정 → 결과 검사)로 이미지 1장을 수정하고
소요 시간·토큰·예상 비용·결과 이미지를 저장한다. DB·Storage·운영 데이터는 쓰지 않는다.

- 키는 OPENAI_API_KEY 환경변수에서만 읽고 출력·저장하지 않는다.
- `--yes` 없이 실행하면 요청 내용만 보여 주고 호출하지 않는다 (비용 0).
- `--max-cost-usd`(기본 0.20)를 넘는 결과가 나오면 다음 호출을 하지 말라고 종료 코드 3으로 알린다.

usage (backend/에서):
  uv run python ../e2e/real_image_edit_check.py --image sketch.jpg --stage SKETCH \
    --subject "유리병과 사과" --type "소묘" \
    --improvement "FORM|WEAKNESS|유리병 입구의 타원이 지나치게 납작하다." --out ../e2e-out/real --yes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import load_settings  # noqa: E402
from app.integrations.ai.openai_image import EditImage, ImageEditError, OpenAiImageEditor  # noqa: E402
from app.models.enums import (  # noqa: E402
    WEAKNESS_CATEGORY_LABELS,
    ArtworkStage,
    FeedbackItemKind,
    WeaknessCategory,
)
from app.services.ai_revision_candidates import KIND_LABELS  # noqa: E402
from app.services.ai_revision_images import choose_size, inspect_result, prepare_source  # noqa: E402
from app.services.ai_revision_prompt import build_prompt  # noqa: E402
from app.services.ai_revisions import estimate_cost  # noqa: E402


def improvement(spec: str) -> dict:
    category, kind, text = spec.split("|", 2)
    cat, knd = WeaknessCategory(category), FeedbackItemKind(kind)
    return {
        "key": f"{category}-{kind}",
        "category": cat.value,
        "category_label": WEAKNESS_CATEGORY_LABELS[cat],
        "kind": knd.value,
        "kind_label": KIND_LABELS[knd],
        "text": text.strip(),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--stage", required=True, choices=["SKETCH", "PROGRESS", "FINAL"])
    parser.add_argument("--stage-name", default=None)
    parser.add_argument("--subject", default=None)
    parser.add_argument("--type", dest="practical_type", default=None)
    parser.add_argument("--reference", default=None, help="원본 제시물 사진 (선택)")
    parser.add_argument("--improvement", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-cost-usd", type=float, default=0.20)
    parser.add_argument("--yes", action="store_true", help="실제 유료 호출")
    args = parser.parse_args()

    settings = load_settings(image_edit_enabled=True)
    stage = ArtworkStage(args.stage)
    improvements = [improvement(s) for s in args.improvement]
    source = prepare_source(Path(args.image).read_bytes(), max_px=settings.image_edit_max_input_px)
    images = [EditImage(source.data, source.content_type, "artwork.jpg")]
    if args.reference:
        ref = prepare_source(Path(args.reference).read_bytes(), max_px=settings.image_edit_max_input_px)
        images.append(EditImage(ref.data, ref.content_type, "reference.jpg"))
    prompt = build_prompt(
        stage=stage,
        stage_name=args.stage_name or {"SKETCH": "스케치", "PROGRESS": "중간 작업", "FINAL": "완성"}[args.stage],
        subject=args.subject,
        practical_type=args.practical_type,
        has_reference=len(images) > 1,
        improvements=improvements,
    )
    size = choose_size(source.width, source.height, settings.image_edit_size)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.image).stem
    (out / f"{stem}.original.jpg").write_bytes(source.data)
    (out / f"{stem}.prompt.txt").write_text(prompt, encoding="utf-8")
    plan = {
        "model": settings.image_edit_model,
        "quality": settings.image_edit_quality,
        "size": size,
        "input_px": [source.width, source.height],
        "images": len(images),
        "improvements": [i["text"] for i in improvements],
    }
    print(json.dumps({"plan": plan}, ensure_ascii=False))
    if not args.yes:
        print("dry run (no API call). add --yes to call OpenAI")
        return 0
    if settings.openai_api_key is None:
        print("OPENAI_API_KEY is not set")
        return 2

    editor = OpenAiImageEditor(settings)
    started = time.monotonic()
    try:
        result = await editor.edit(images=images, prompt=prompt, size=size, user_key="artmate-real-check")
    except ImageEditError as exc:
        elapsed = round(time.monotonic() - started, 2)
        print(json.dumps({"error": exc.code, "message": str(exc), "retryable": exc.retryable,
                          "elapsed_s": elapsed}, ensure_ascii=False))
        return 1
    elapsed = round(time.monotonic() - started, 2)
    info = inspect_result(result.image, max_bytes=settings.image_edit_max_result_bytes)
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[info.content_type]
    (out / f"{stem}.revision.{ext}").write_bytes(result.image)
    text_tokens = result.input_text_tokens or max(0, result.input_tokens - result.input_image_tokens)
    cost = estimate_cost(settings, text_tokens=text_tokens, image_tokens=result.input_image_tokens,
                         output_tokens=result.output_tokens)
    report = {
        **plan,
        "api_seconds": elapsed,
        "output_px": [info.width, info.height],
        "output_bytes": len(result.image),
        "input_tokens": result.input_tokens,
        "input_image_tokens": result.input_image_tokens,
        "input_text_tokens": text_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost_usd": float(cost),
    }
    (out / f"{stem}.report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 3 if float(cost) > args.max_cost_usd else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
