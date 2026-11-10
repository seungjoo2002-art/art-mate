// 실기시험 모드 (모의시험 작품 + 제한 시간)
export const EXAM_LIMITS = [180, 240, 300, 360] // 분
export const DEFAULT_EXAM_MINUTES = 300 // 5시간

/** 200 → "3시간 20분" */
export function formatMinutes(minutes) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (!h) return `${m}분`
  return m ? `${h}시간 ${m}분` : `${h}시간`
}
