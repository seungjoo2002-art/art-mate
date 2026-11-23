"""ART MATE PWA 아이콘 생성기.

구성: 흰 바탕(#FFFFFF) + 커다란 주황 'A'(--color-primary) + 기존 마스코트(mascot-cheer, 손 든 포즈)를
크게, A 오른쪽 다리 앞에 겹쳐 둔다. 가슴 앞 앞발이 A 다리에 닿아 'A를 붙잡고 인사하는' 느낌.
마스코트는 기존 에셋을 비율 그대로 확대·축소만 한다 (새로 그리거나 변형하지 않음).

실행 (Pillow 필요, 백엔드 가상환경에 있음):
    backend/.venv/Scripts/python frontend/scripts/pwa-icons/make_icons.py
출력: frontend/public/icons/{icon-192,icon-512,icon-maskable-512,apple-touch-icon,favicon-48,favicon-32}.png
확인용 미리보기(64·48·32px 확대): --preview DIR
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]  # frontend/
MASCOT = ROOT / "src/assets/mascot/mascot-cheer.webp"
OUT = ROOT / "public/icons"

N = 1024  # 원본 크기 (여기서 그려 줄인다)
SS = 4  # A를 4배로 그려 줄여서 가장자리를 부드럽게
WHITE = (255, 255, 255, 255)
ORANGE = (242, 147, 58, 255)  # --color-primary #f2933a

# ---- 배치 (1024 기준 좌표, 수정할 때 여기만 바꾸면 된다)
A_APEX = (430, 105)  # 꼭짓점
A_LEFT = (120, 915)  # 왼쪽 다리 끝
A_RIGHT = (760, 915)  # 오른쪽 다리 끝
A_STROKE = 140  # 획 굵기
A_BAR_Y = 650  # 가로획 높이
A_BAR = (215, 650)  # 가로획 x 범위 (오른쪽 끝은 고양이 뒤로 숨음)
CAT_HEIGHT = 700  # 고양이 높이 (원본 비율 유지)
CAT_CENTER = (705, 655)  # 고양이 이미지 중심


def draw_a(scale: float) -> Image.Image:
    big = N * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def p(x: float, y: float) -> tuple[float, float]:
        c = N / 2
        return ((c + (x - c) * scale) * SS, (c + (y - c) * scale) * SS)

    w = A_STROKE * scale * SS
    apex, left, right = p(*A_APEX), p(*A_LEFT), p(*A_RIGHT)
    d.line([apex, left], fill=ORANGE, width=int(w))
    d.line([apex, right], fill=ORANGE, width=int(w))
    for x, y in (apex, left, right):  # 둥근 끝 (Jua 같은 둥근 제목 글꼴 느낌)
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=ORANGE)
    d.line(
        [p(A_BAR[0], A_BAR_Y), p(A_BAR[1], A_BAR_Y)],
        fill=ORANGE,
        width=int(A_STROKE * 0.82 * scale * SS),
    )
    return img.resize((N, N), Image.LANCZOS)


def compose(scale: float = 1.0) -> Image.Image:
    """scale < 1: maskable용으로 전체를 가운데로 모음 (원형 안전 영역 안에)."""
    base = Image.new("RGBA", (N, N), WHITE)
    base.alpha_composite(draw_a(scale))
    cat = Image.open(MASCOT).convert("RGBA")
    h = round(CAT_HEIGHT * scale)
    w = round(cat.width * h / cat.height)  # 비율 유지
    cat = cat.resize((w, h), Image.LANCZOS)
    c = N / 2
    cx = c + (CAT_CENTER[0] - c) * scale
    cy = c + (CAT_CENTER[1] - c) * scale
    base.alpha_composite(cat, (round(cx - w / 2), round(cy - h / 2)))
    return base.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, help="작은 크기 확인용 미리보기 폴더")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    full, mask = compose(1.0), compose(0.8)
    outputs = {
        "icon-192.png": (full, 192),
        "icon-512.png": (full, 512),
        "icon-maskable-512.png": (mask, 512),
        "apple-touch-icon.png": (full, 180),
        "favicon-48.png": (full, 48),
        "favicon-32.png": (full, 32),
    }
    for name, (img, size) in outputs.items():
        img.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
    if args.preview:
        args.preview.mkdir(parents=True, exist_ok=True)
        full.save(args.preview / "full-1024.png")
        mask.save(args.preview / "maskable-1024.png")
        for size in (64, 48, 32):
            small = full.resize((size, size), Image.LANCZOS)
            small.resize((size * 4, size * 4), Image.NEAREST).save(args.preview / f"x{size}.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
