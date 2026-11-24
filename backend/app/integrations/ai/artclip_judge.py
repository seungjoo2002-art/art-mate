"""ArtCLIP(APDDv2) 기반 주제별 합격권 판정 모듈.

구성
- ArtClipScorer  : 그림 → ArtCLIP 점수 11개(총점 0~100, 속성 0~10) + 768차원 임베딩.  (torch 필요)
- TopicReference : 한 주제(예: 2024 이화여대 패션디자인 '유리컵과 털실')의 합격작 기준 데이터.
                   새 그림을 이 기준에 비춰 '합격권 / 경계 / 합격권 밖'으로 판정.  (numpy만 필요)

판정 방식 (기준 합격작 n장)
  1) 점수 기준  : 총점이 기준 합격작 총점의 하위 q 분위수(기본 10%) 이상인가
  2) 유사도 기준: 가장 비슷한 합격작 k장(기본 3장)과의 평균 코사인 유사도가,
                  합격작끼리 같은 방식으로 잰 유사도의 하위 q 분위수 이상인가
  둘 다 통과 → '합격권', 하나만 → '경계', 둘 다 실패 → '합격권 밖'
  index(0~100) = 총점 백분위와 유사도 백분위의 평균 (기준 합격작 사이에서의 위치)
  strengths / weaknesses = 속성 점수가 합격작 중앙값 이상 / 하위 20% 미만인 항목 (화면의 '주요 유사 특징')

  화면 표시 주의
  - similarity(코사인 유사도) 원값을 %로 바꿔 보여 주지 말 것. 같은 소재 그림끼리는 원값이 좁은 범위에
    몰리기 쉬워서 누구나 비슷한 높은 숫자가 나온다. 보여 줄 숫자는 index 또는 similarity_percentile.
  - index는 '합격 확률'이 아님. 불합격작 데이터로 보정하기 전까지는 '합격작 대비 위치(점수)'로 표기.

주의
  - 같은 주제 합격작끼리는 소재가 같아서, 유사도는 '잘 그렸나'보다 '주제를 비슷하게 풀었나'에 가깝다.
  - 합격작만으로 검증하면(leave_one_out) '항상 합격'이라고 답하는 시스템도 통과한다.
    같은 주제의 불합격작·연습작을 evaluate()에 넣어 떨어뜨려야 할 그림을 떨어뜨리는지도 봐야 한다.
  - 판정은 '합격 확률'이 아니라 '기준 합격작들 사이에서의 위치'다.
  - ArtCLIP 가중치는 CC BY-NC-ND 4.0 데이터셋(APDDv2)으로 학습됨 → 상업적 사용 전 저자 확인 필요.

백엔드 사용 예
    from artclip_judge import ArtClipScorer, TopicReference
    scorer = ArtClipScorer('/path/to/artclip_weights')              # 서버 시작 시 한 번 (GPU 약 4GB)
    ref = TopicReference(scorer.extract(accepted_paths),
                         info={'year': 2024, 'university': '이화여대', 'dept': '패션디자인', 'topic': '유리컵과 털실'},
                         exclude_attrs=('color',))                    # 소묘면 색채 제외
    ref.save('2024_ewha_fashion.npz')                                 # 주제별로 미리 저장
    ref = TopicReference.load('2024_ewha_fashion.npz')
    result = ref.judge(scorer.extract([uploaded_bytes]))[0]           # json.dumps 가능한 dict

명령줄
    python artclip_judge.py loo   --weights W --images 주제폴더 [--neg 비교작폴더]
    python artclip_judge.py build --weights W --images 주제폴더 --out ref.npz [--info '{"year":2024}']
    python artclip_judge.py judge --weights W --ref ref.npz 학생그림.jpg ...

ArtCLIP 모델 구조: APDDv2 저장소(github.com/BestiVictory/APDDv2)의 AesCLIP_reg와 같은 계산
(CLIP ViT-B/16 이미지 인코더 출력 768차원 → Linear(768→1)). 전처리는 저장소 eval.py와 같은 방식
(그림 전체를 224x224로 bilinear 리사이즈 + CLIP 정규화).
"""

from __future__ import annotations

import argparse
import glob
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile, ImageOps

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 400_000_000
try:  # 아이폰 HEIC 사진 (pip install pillow-heif)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

# (체크포인트 폴더 번호, JSON 키, 표시 이름)
ATTRS = [
    (1, "total", "총점"),
    (2, "theme_logic", "주제·논리"),
    (3, "creativity", "창의성"),
    (4, "composition", "구도"),
    (5, "space_perspective", "공간·원근"),
    (6, "order", "질서감"),
    (7, "light_shadow", "명암"),
    (8, "color", "색채"),
    (9, "detail_texture", "디테일·질감"),
    (10, "overall", "전체감"),
    (11, "mood", "분위기"),
]
ATTR_KEYS = [a[1] for a in ATTRS]
LABEL = {a[1]: a[2] for a in ATTRS}
VERDICTS = ("합격권", "경계", "합격권 밖")
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)


# ----------------------------------------------------------------------------- 파일·이미지
def find_checkpoints(root):
    """weights 폴더에서 '0.' ~ '11.' 로 시작하는 폴더/파일의 .pth를 찾아 {번호: 경로}."""
    found = {}
    root = Path(root)
    for p in sorted(glob.glob(str(root / "**" / "*.pth"), recursive=True)):
        parts = Path(p).relative_to(root).parts
        if "__MACOSX" in parts or parts[-1].startswith("._"):
            continue
        for i in range(12):
            if i not in found and any(part.startswith(f"{i}.") for part in parts):
                found[i] = p
    return found


def is_truncated(path):
    """torch 체크포인트(zip 형식)가 중간에 잘렸는지. 옛 형식(zip 아님)은 검사하지 않고 정상으로 봄."""
    import zipfile

    with open(path, "rb") as f:
        head = f.read(4)
    return head == b"PK\x03\x04" and not zipfile.is_zipfile(path)


def list_images(folder):
    folder = Path(folder)
    return sorted(
        p for p in folder.rglob("*") if p.suffix.lower() in IMG_EXT and not p.name.startswith(".")
    )


def load_image(src):
    """경로(str/Path), bytes, PIL.Image 모두 받음 → RGB PIL.Image."""
    if isinstance(src, Image.Image):
        img = src
    elif isinstance(src, (bytes, bytearray, memoryview)):
        img = Image.open(io.BytesIO(bytes(src)))
    else:
        img = Image.open(src)
    if getattr(img, "format", None) == "JPEG":
        img.draft("RGB", (448, 448))  # 큰 사진 빠르게 디코딩
    return ImageOps.exif_transpose(img).convert("RGB")


def to_array(img, mode="squash", size=224):
    """224x224 uint8 배열. squash=eval.py와 동일(전체를 늘려 맞춤), center_crop=demo.py 방식, pad=흰 여백."""
    w, h = img.size
    if mode == "pad":
        s = max(w, h)
        canvas = Image.new("RGB", (s, s), (255, 255, 255))
        canvas.paste(img, ((s - w) // 2, (s - h) // 2))
        img = canvas.resize((size, size), Image.Resampling.BILINEAR)
    elif mode == "center_crop":
        r = size / min(w, h)
        img = img.resize(
            (max(size, round(w * r)), max(size, round(h * r))), Image.Resampling.BICUBIC
        )
        w, h = img.size
        l, t = (w - size) // 2, (h - size) // 2
        img = img.crop((l, t, l + size, t + size))
    else:
        img = img.resize((size, size), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.uint8)


def _default_id(src, i):
    if isinstance(src, (str, Path)):
        return Path(src).name
    return f"image_{i}"


# ----------------------------------------------------------------------------- 특징
@dataclass
class Features:
    ids: list
    scores: np.ndarray  # (N, 11), ATTRS 순서. 총점은 0~100, 나머지 0~10
    emb: np.ndarray  # (N, D)

    def __len__(self):
        return len(self.ids)

    def take(self, idx):
        idx = list(idx)
        return Features([self.ids[i] for i in idx], self.scores[idx], self.emb[idx])

    @staticmethod
    def concat(items):
        return Features(
            sum((list(f.ids) for f in items), []),
            np.concatenate([f.scores for f in items]),
            np.concatenate([f.emb for f in items]),
        )

    def to_records(self):
        return [
            {
                "id": self.ids[i],
                **{k: round(float(self.scores[i, j]), 3) for j, k in enumerate(ATTR_KEYS)},
            }
            for i in range(len(self))
        ]


# ----------------------------------------------------------------------------- torch 부분
_TORCH = None


def _torch_parts():
    """torch와 CLIP VisionTransformer 클래스를 필요할 때만 불러옴."""
    global _TORCH
    if _TORCH is not None:
        return _TORCH
    from collections import OrderedDict

    import torch
    from torch import nn

    # --- 아래 4개 클래스: OpenAI CLIP (MIT License, Copyright (c) 2021 OpenAI)
    #     APDDv2 저장소 models/clip/model.py 그대로 (마지막 proj 미적용 → 768차원 출력)
    class LayerNorm(nn.LayerNorm):
        def forward(self, x):
            orig_type = x.dtype
            ret = super().forward(x.type(torch.float32))
            return ret.type(orig_type)

    class QuickGELU(nn.Module):
        def forward(self, x):
            return x * torch.sigmoid(1.702 * x)

    class ResidualAttentionBlock(nn.Module):
        def __init__(self, d_model, n_head, attn_mask=None):
            super().__init__()
            self.attn = nn.MultiheadAttention(d_model, n_head)
            self.ln_1 = LayerNorm(d_model)
            self.mlp = nn.Sequential(
                OrderedDict(
                    [
                        ("c_fc", nn.Linear(d_model, d_model * 4)),
                        ("gelu", QuickGELU()),
                        ("c_proj", nn.Linear(d_model * 4, d_model)),
                    ]
                )
            )
            self.ln_2 = LayerNorm(d_model)
            self.attn_mask = attn_mask

        def attention(self, x):
            self.attn_mask = (
                self.attn_mask.to(dtype=x.dtype, device=x.device)
                if self.attn_mask is not None
                else None
            )
            return self.attn(x, x, x, need_weights=False, attn_mask=self.attn_mask)[0]

        def forward(self, x):
            x = x + self.attention(self.ln_1(x))
            x = x + self.mlp(self.ln_2(x))
            return x

    class Transformer(nn.Module):
        def __init__(self, width, layers, heads, attn_mask=None):
            super().__init__()
            self.width = width
            self.layers = layers
            self.resblocks = nn.Sequential(
                *[ResidualAttentionBlock(width, heads, attn_mask) for _ in range(layers)]
            )

        def forward(self, x):
            return self.resblocks(x)

    class VisionTransformer(nn.Module):
        def __init__(self, input_resolution, patch_size, width, layers, heads, output_dim):
            super().__init__()
            self.input_resolution = input_resolution
            self.output_dim = output_dim
            self.conv1 = nn.Conv2d(3, width, kernel_size=patch_size, stride=patch_size, bias=False)
            scale = width**-0.5
            self.class_embedding = nn.Parameter(scale * torch.randn(width))
            self.positional_embedding = nn.Parameter(
                scale * torch.randn((input_resolution // patch_size) ** 2 + 1, width)
            )
            self.ln_pre = LayerNorm(width)
            self.transformer = Transformer(width, layers, heads)
            self.ln_post = LayerNorm(width)
            self.proj = nn.Parameter(scale * torch.randn(width, output_dim))

        def forward(self, x):
            x = self.conv1(x)
            x = x.reshape(x.shape[0], x.shape[1], -1)
            x = x.permute(0, 2, 1)
            x = torch.cat(
                [
                    self.class_embedding.to(x.dtype)
                    + torch.zeros(x.shape[0], 1, x.shape[-1], dtype=x.dtype, device=x.device),
                    x,
                ],
                dim=1,
            )
            x = x + self.positional_embedding.to(x.dtype)
            x = self.ln_pre(x)
            x = x.permute(1, 0, 2)
            x = self.transformer(x)
            x = x.permute(1, 0, 2)
            return self.ln_post(x[:, 0, :])

    # --- OpenAI CLIP 코드 끝

    def build_visual(sd):
        key = next((k for k in sd if k.endswith("visual.conv1.weight")), None)
        if key is None:
            raise KeyError(
                "체크포인트에서 이미지 인코더를 찾지 못함. 앞부분 키: " + ", ".join(list(sd)[:5])
            )
        prefix = key[: -len("conv1.weight")]
        vsd = {k[len(prefix) :]: v.float() for k, v in sd.items() if k.startswith(prefix)}
        width, patch = vsd["conv1.weight"].shape[0], vsd["conv1.weight"].shape[-1]
        grid = round((vsd["positional_embedding"].shape[0] - 1) ** 0.5)
        layers = len({k.split(".")[2] for k in vsd if k.startswith("transformer.resblocks.")})
        vt = VisionTransformer(
            patch * grid, patch, width, layers, width // 64, vsd["proj"].shape[1]
        )
        vt.load_state_dict(vsd, strict=True)
        return vt

    class ArtCLIPReg(nn.Module):
        """AesCLIP_reg.forward 와 같은 계산: score = mlp(aesclip.visual(x))."""

        def __init__(self, sd):
            super().__init__()
            self.visual = build_visual(sd)
            wk = next(k for k in sd if k.endswith("mlp.0.weight"))
            self.head = nn.Linear(sd[wk].shape[1], 1)
            self.head.load_state_dict(
                {"weight": sd[wk].float(), "bias": sd[wk[:-6] + "bias"].float()}
            )

        def forward(self, x):
            f = self.visual(x)
            return self.head(f).squeeze(-1), f

    def load_sd(path):
        try:
            obj = torch.load(path, map_location="cpu", weights_only=True)
        except Exception:
            obj = torch.load(
                path, map_location="cpu", weights_only=False
            )  # 공식 링크에서 받은 파일만
        for key in ("state_dict", "model", "model_state_dict"):
            if isinstance(obj, dict) and isinstance(obj.get(key), dict):
                obj = obj[key]
        return obj

    _TORCH = (torch, ArtCLIPReg, build_visual, load_sd)
    return _TORCH


class ArtClipScorer:
    """ArtCLIP 모델 11개(총점 + 속성 10개)를 한 번에 올려 두고 그림을 점수·임베딩으로 바꿈."""

    def __init__(
        self,
        weights_dir,
        device=None,
        half=False,
        resize_mode="squash",
        embedding="total",
        verbose=True,
    ):
        torch, ArtCLIPReg, build_visual, load_sd = _torch_parts()
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.half = bool(half) and str(self.device).startswith("cuda")
        self.resize_mode = resize_mode
        self.embedding = embedding
        ckpts = find_checkpoints(weights_dir)
        missing = [i for i in range(1, 12) if i not in ckpts]
        if missing:
            raise FileNotFoundError(f"{weights_dir} 에서 못 찾은 체크포인트 번호: {missing}")
        self.models, self.skipped = [], []
        for i, key, label in ATTRS:
            try:
                m = ArtCLIPReg(load_sd(ckpts[i])).to(self.device).eval()
            except Exception as e:
                if i == 1:
                    raise RuntimeError(
                        f"총점 모델 파일이 손상됨: {ckpts[i]} → 가중치를 다시 받아야 함"
                    ) from e
                print(f"  [건너뜀] ArtCLIP {i:>2}. {label}: 파일 손상 → 이 항목 없이 진행")
                self.models.append(None)
                self.skipped.append(key)
                continue
            self.models.append(m.half() if self.half else m)
            if verbose:
                print(f"  ArtCLIP {i:>2}. {label} 로드")
        self.base = None
        if embedding == "base":
            if 0 not in ckpts:
                raise FileNotFoundError('embedding="base"에는 0번(기본 ArtCLIP) 체크포인트가 필요')
            b = build_visual(load_sd(ckpts[0])).to(self.device).eval()
            self.base = b.half() if self.half else b
        self._mean = torch.tensor(CLIP_MEAN, device=self.device).view(1, 3, 1, 1)
        self._std = torch.tensor(CLIP_STD, device=self.device).view(1, 3, 1, 1)

    def extract(self, images, ids=None, batch_size=32, skip_errors=False):
        """images: 경로/bytes/PIL 리스트 → Features. skip_errors=True면 못 읽는 그림은 건너뜀."""
        torch = self.torch
        images = list(images)
        ids = list(ids) if ids is not None else [_default_id(x, i) for i, x in enumerate(images)]
        arrays, keep = [], []
        for i, src in enumerate(images):
            try:
                arrays.append(to_array(load_image(src), self.resize_mode))
                keep.append(i)
            except Exception as e:
                if not skip_errors:
                    raise ValueError(f"그림을 읽지 못함: {ids[i]} ({e})") from e
                print(f"  [건너뜀] {ids[i]}: {e}")
        if not arrays:
            raise ValueError("읽을 수 있는 그림이 없음")
        scores, embs = [], []
        with torch.no_grad():
            for b in range(0, len(arrays), batch_size):
                x = torch.from_numpy(np.stack(arrays[b : b + batch_size])).permute(0, 3, 1, 2)
                x = x.to(self.device).float().div_(255).sub_(self._mean).div_(self._std)
                if self.half:
                    x = x.half()
                cols, emb = [], None
                for (i, _, _), m in zip(ATTRS, self.models):
                    if m is None:  # 손상돼서 건너뛴 항목
                        cols.append(np.full(len(x), np.nan))
                        continue
                    s, f = m(x)
                    cols.append(s.float().cpu().numpy().reshape(-1))
                    if i == 1:
                        emb = f.float().cpu().numpy()
                if self.base is not None:
                    emb = self.base(x).float().cpu().numpy()
                sc = np.stack(cols, axis=1)
                sc[:, 0] *= 10  # 총점 0~100 (저장소 demo.py와 동일)
                scores.append(sc)
                embs.append(emb)
        return Features([ids[i] for i in keep], np.concatenate(scores), np.concatenate(embs))


# ----------------------------------------------------------------------------- 판정
def _l2(X):
    X = np.asarray(X, dtype=np.float64)
    return X / np.clip(np.linalg.norm(X, axis=1, keepdims=True), 1e-12, None)


def _pct(x, arr):
    """기준 분포 arr 안에서 x의 백분위(0~100). 동점은 절반만 셈."""
    arr = np.asarray(arr)
    return float(((arr < x).sum() + 0.5 * (arr == x).sum()) / len(arr) * 100)


def _auc(pos, neg):
    """pos가 neg보다 클 확률 (0.5 = 구분 못 함, 1.0 = 완벽히 구분)."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if len(pos) == 0 or len(neg) == 0:
        return None
    gt = (pos[:, None] > neg[None, :]).sum()
    eq = (pos[:, None] == neg[None, :]).sum()
    return float((gt + 0.5 * eq) / (len(pos) * len(neg)))


def _r(x, d=3):
    return None if x is None else round(float(x), d)


class TopicReference:
    """한 주제의 합격작 기준. 새 그림을 이 합격작들에 비춰 판정한다."""

    def __init__(self, feats: Features, info=None, q=0.1, k=3, exclude_attrs=()):
        if len(feats) < 3:
            raise ValueError(f"기준 합격작이 {len(feats)}장. 최소 3장 필요 (권장 8장 이상)")
        self.feats = feats
        self.info = dict(info or {})
        self.q, self.k = float(q), int(k)
        self.exclude_attrs = tuple(exclude_attrs)
        n = len(feats)
        self.kk = min(self.k, n - 1)
        self._E = _l2(feats.emb)
        S = self._E @ self._E.T
        np.fill_diagonal(S, -np.inf)
        self.ref_sim = -np.sort(-S, axis=1)[:, : self.kk].mean(axis=1)  # 합격작끼리의 유사도
        self.ref_total = feats.scores[:, 0].astype(float)
        self.thr_total = float(np.quantile(self.ref_total, self.q))
        self.thr_sim = float(np.quantile(self.ref_sim, self.q))

    def __len__(self):
        return len(self.feats)

    def summary(self):
        return {
            "info": self.info,
            "n_reference": len(self),
            "q": self.q,
            "k": self.kk,
            "threshold_total": _r(self.thr_total, 2),
            "threshold_similarity": _r(self.thr_sim, 4),
            "reference_total_median": _r(np.median(self.ref_total), 2),
            "reference_similarity_median": _r(np.median(self.ref_sim), 4),
        }

    def judge(self, feats: Features):
        """Features(1장 이상) → 그림마다 판정 dict 리스트 (json.dumps 가능)."""
        E = _l2(feats.emb)
        S = E @ self._E.T
        order = np.argsort(-S, axis=1)
        out = []
        for r in range(len(feats)):
            sim = float(S[r, order[r, : self.kk]].mean())
            total = float(feats.scores[r, 0])
            ok_total, ok_sim = total >= self.thr_total, sim >= self.thr_sim
            verdict = (
                VERDICTS[0]
                if ok_total and ok_sim
                else VERDICTS[1]
                if ok_total or ok_sim
                else VERDICTS[2]
            )
            t_pct, s_pct = _pct(total, self.ref_total), _pct(sim, self.ref_sim)
            attrs = {}
            for j, key in enumerate(ATTR_KEYS):
                col = self.feats.scores[:, j]
                if key in self.exclude_attrs or np.isnan(feats.scores[r, j]) or np.isnan(col).any():
                    continue
                attrs[key] = {
                    "label": LABEL[key],
                    "score": _r(feats.scores[r, j], 2),
                    "percentile": _r(_pct(feats.scores[r, j], col), 1),
                    "reference_median": _r(np.median(col), 2),
                }
            sub = [(k, v) for k, v in attrs.items() if k != "total"]
            strengths = sorted(
                [kv for kv in sub if kv[1]["percentile"] >= 50], key=lambda kv: -kv[1]["percentile"]
            )[:3]
            weaknesses = sorted(
                [kv for kv in sub if kv[1]["percentile"] < 20], key=lambda kv: kv[1]["percentile"]
            )[:3]
            res = {
                "id": feats.ids[r],
                "verdict": verdict,
                "index": _r((t_pct + s_pct) / 2, 1),
                "pass_total": bool(ok_total),
                "pass_similarity": bool(ok_sim),
                "total": _r(total, 2),
                "total_percentile": _r(t_pct, 1),
                "similarity": _r(sim, 4),
                "similarity_percentile": _r(s_pct, 1),
                "thresholds": {"total": _r(self.thr_total, 2), "similarity": _r(self.thr_sim, 4)},
                "attributes": attrs,
                # 화면의 '주요 유사 특징' / '보완할 점' 용: 속성 점수가 합격작 중앙값 이상 / 하위 20% 미만인 항목
                "strengths": [
                    {"key": k, "label": v["label"], "percentile": v["percentile"]}
                    for k, v in strengths
                ],
                "weaknesses": [
                    {"key": k, "label": v["label"], "percentile": v["percentile"]}
                    for k, v in weaknesses
                ],
                "nearest": [
                    {"id": self.feats.ids[j], "similarity": _r(S[r, j], 4)}
                    for j in order[r, : min(3, len(self))]
                ],
                "n_reference": len(self),
                "topic": self.info,
            }
            if S[r, order[r, 0]] > 0.995:
                res["warning"] = (
                    f"기준 합격작 '{self.feats.ids[order[r, 0]]}'와 사실상 같은 그림 (테스트라면 기준에서 빼야 함)"
                )
            out.append(res)
        return out

    def without(self, i):
        """i번째 합격작을 뺀 기준."""
        keep = [j for j in range(len(self)) if j != i]
        return TopicReference(self.feats.take(keep), self.info, self.q, self.k, self.exclude_attrs)

    def leave_one_out(self):
        """합격작을 한 장씩 빼서 '학생 그림'으로 보고, 나머지로 판정 (팀 테스트를 모든 장에 대해 반복)."""
        if len(self) < 4:
            raise ValueError(f"leave-one-out은 합격작 4장 이상 필요 (지금 {len(self)}장)")
        return [self.without(i).judge(self.feats.take([i]))[0] for i in range(len(self))]

    def evaluate(self, negatives: Features = None):
        """합격작(leave-one-out) vs 비교 그림(불합격작·연습작 등) 판정 비율과 구분력(AUC)."""
        pos = self.leave_one_out()
        neg = self.judge(negatives) if negatives is not None and len(negatives) else []

        def rates(rows):
            n = max(len(rows), 1)
            return {v: round(sum(r["verdict"] == v for r in rows) / n, 3) for v in VERDICTS}

        out = {"n_positive": len(pos), "positive_rates": rates(pos), "positives": pos}
        if neg:
            out.update(
                {
                    "n_negative": len(neg),
                    "negative_rates": rates(neg),
                    "negatives": neg,
                    "auc": {
                        "index": _r(_auc([p["index"] for p in pos], [x["index"] for x in neg])),
                        "total": _r(_auc([p["total"] for p in pos], [x["total"] for x in neg])),
                        "similarity": _r(
                            _auc([p["similarity"] for p in pos], [x["similarity"] for x in neg])
                        ),
                    },
                }
            )
        return out

    def save(self, path):
        params = {
            "q": self.q,
            "k": self.k,
            "exclude_attrs": list(self.exclude_attrs),
            "attr_keys": ATTR_KEYS,
            "version": 1,
        }
        np.savez(
            path,
            ids=np.array(self.feats.ids, dtype=str),
            scores=self.feats.scores,
            emb=self.feats.emb,
            info=np.array(json.dumps(self.info, ensure_ascii=False)),
            params=np.array(json.dumps(params)),
        )

    @classmethod
    def load(cls, path):
        z = np.load(path, allow_pickle=False)
        params = json.loads(str(z["params"]))
        if params.get("attr_keys") != ATTR_KEYS:
            raise ValueError("저장 파일의 속성 순서가 현재 모듈과 다름")
        feats = Features([str(s) for s in z["ids"]], z["scores"], z["emb"])
        return cls(
            feats, json.loads(str(z["info"])), params["q"], params["k"], params["exclude_attrs"]
        )


def flatten(result):
    """판정 dict → 표 한 줄 (DataFrame/CSV용)."""
    row = {
        k: result[k]
        for k in (
            "id",
            "verdict",
            "index",
            "total",
            "total_percentile",
            "similarity",
            "similarity_percentile",
        )
    }
    row.update(
        {v["label"]: v["score"] for v in result["attributes"].values() if v["label"] != "총점"}
    )
    row["가장 비슷한 합격작"] = result["nearest"][0]["id"] if result["nearest"] else ""
    return row


# ----------------------------------------------------------------------------- 명령줄
def _print_table(rows):
    cols = [
        "id",
        "verdict",
        "index",
        "total",
        "total_percentile",
        "similarity",
        "similarity_percentile",
    ]
    print("  ".join(f"{c:>12}" for c in cols))
    for r in rows:
        print("  ".join(f"{str(r[c])[:12]:>12}" for c in cols))


def main(argv=None):
    ap = argparse.ArgumentParser(description="ArtCLIP 주제별 합격권 판정")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("loo", "build", "judge"):
        p = sub.add_parser(name)
        p.add_argument("--weights", required=True, help="ArtCLIP 체크포인트 폴더")
        p.add_argument("--device", default=None)
        p.add_argument("--exclude", nargs="*", default=[], help="제외할 속성 키 (소묘: color)")
        p.add_argument("--q", type=float, default=0.1)
        p.add_argument("--k", type=int, default=3)
        if name in ("loo", "build"):
            p.add_argument("--images", required=True, help="한 주제의 합격작 폴더")
            p.add_argument("--info", default="{}", help="주제 정보 JSON")
        if name == "loo":
            p.add_argument("--neg", default=None, help="같은 주제 불합격작·연습작 폴더 (선택)")
        if name == "build":
            p.add_argument("--out", required=True)
        if name == "judge":
            p.add_argument("--ref", required=True)
            p.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    scorer = ArtClipScorer(a.weights, device=a.device)
    if a.cmd == "judge":
        ref = TopicReference.load(a.ref)
        for r in ref.judge(scorer.extract(a.files)):
            print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    paths = list_images(a.images)
    ref = TopicReference(
        scorer.extract(paths, skip_errors=True), json.loads(a.info), a.q, a.k, a.exclude
    )
    if a.cmd == "build":
        ref.save(a.out)
        print(json.dumps(ref.summary(), ensure_ascii=False, indent=1))
        return
    neg = scorer.extract(list_images(a.neg), skip_errors=True) if a.neg else None
    ev = ref.evaluate(neg)
    print("[합격작 leave-one-out]")
    _print_table(ev["positives"])
    print("판정 비율:", ev["positive_rates"])
    if "negatives" in ev:
        print("\n[비교 그림]")
        _print_table(ev["negatives"])
        print("판정 비율:", ev["negative_rates"], "\nAUC:", ev["auc"])


if __name__ == "__main__":
    main()
