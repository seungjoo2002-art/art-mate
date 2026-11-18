// v1.1 원본 제시물·시험 조건·표현 의도 (순수 함수, 화면과 분리해 테스트)
import { checkImageFile } from './api'

export const DEFAULT_MAX_REFERENCE_PHOTOS = 5

/** 표현 방식 (서버 /meta/options expression_methods와 같은 순서·라벨, 옵션을 못 받을 때 대신 사용) */
export const EXPRESSION_METHODS = [
  { code: 'SCALE', label: '확대·축소' },
  { code: 'ROTATE', label: '회전·기울이기' },
  { code: 'REPEAT', label: '반복·중첩' },
  { code: 'CUT', label: '절단·분해' },
  { code: 'DISTORT', label: '형태 과장·왜곡' },
  { code: 'REARRANGE', label: '재배치' },
  { code: 'OTHER', label: '기타' },
]

export const PAPER_SIZES = ['2절', '3절', '4절', '8절']

/**
 * 고른 파일 중 올릴 수 있는 것만 (남은 장수·형식·크기).
 * 반환: { accepted: File[], rejected: [{ name, message }] }
 */
export function acceptFiles(files, remaining) {
  const accepted = []
  const rejected = []
  for (const file of files) {
    try {
      checkImageFile(file)
    } catch (err) {
      rejected.push({ name: file.name, message: err.userMessage })
      continue
    }
    if (accepted.length >= remaining) {
      rejected.push({
        name: file.name,
        message: '원본 사진을 더 올릴 수 없어요 (최대 장수).',
      })
      continue
    }
    accepted.push(file)
  }
  return { accepted, rejected }
}

/** 표현 방식 다중 선택 토글 (정의 순서 유지) */
export function toggleMethod(selected, code) {
  const next = selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code]
  const order = EXPRESSION_METHODS.map((m) => m.code)
  return next.sort((a, b) => order.indexOf(a) - order.indexOf(b))
}

/** 작품 상세에 보여 줄 시험 조건·의도 (값이 있는 것만) */
export function artworkConditions(artwork, methodLabel = (code) => code) {
  const rows = [
    ['실기 주제', artwork.topic],
    ['제시물', artwork.exam_materials],
    ['시험 시간', artwork.time_limit_minutes ? `${artwork.time_limit_minutes}분` : null],
    ['화지', artwork.paper_size],
    ['시험 조건', artwork.exam_conditions],
    ['표현 방식', (artwork.expression_methods ?? []).map(methodLabel).join(' · ') || null],
    ['표현 의도', artwork.expression_intent],
    ['메모', artwork.description],
  ]
  return rows.filter(([, value]) => value).map(([label, value]) => ({ label, value }))
}

/** 작품 사진 중 비교에 쓸 대표 사진: 가장 늦은 단계의 대표 사진 → 없으면 가장 최근 사진 */
export function latestArtworkPhoto(artwork) {
  const photos = (artwork?.photos ?? []).filter((p) => p.status === 'ACTIVE' && p.url)
  if (!photos.length) return null
  const cover = photos.find((p) => p.id === artwork.cover_photo_id)
  if (cover) return cover
  return [...photos].sort((a, b) =>
    (b.uploaded_at ?? b.created_at).localeCompare(a.uploaded_at ?? a.created_at),
  )[0]
}

/** 작품 정보 → 폼 값 (기존 작품은 새 필드가 없어도 빈 값) */
export const examIntentFromArtwork = (artwork = {}) => ({
  time_limit_minutes: artwork.time_limit_minutes ?? '',
  paper_size: artwork.paper_size ?? '',
  exam_conditions: artwork.exam_conditions ?? '',
  description: artwork.description ?? '',
  expression_methods: artwork.expression_methods ?? [],
  expression_intent: artwork.expression_intent ?? '',
})

/** 폼 값 → API (빈 값은 null, 표현 방식은 []) */
export const examIntentPayload = (v) => ({
  paper_size: v.paper_size.trim() || null,
  exam_conditions: v.exam_conditions.trim() || null,
  description: v.description.trim() || null,
  expression_methods: v.expression_methods,
  expression_intent: v.expression_intent.trim() || null,
})
