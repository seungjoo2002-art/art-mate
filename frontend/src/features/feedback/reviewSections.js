// AI 정리 결과 화면의 반복 약점 계산 (순수 함수, 화면과 분리해 테스트)

/**
 * 이번 첨삭에서 지적된 약점 중 이전 확정 첨삭에서도 반복된 것.
 * growth: GET /growth/me/summary (없거나 실패면 null)
 * 반환: { status: 'unknown' | 'insufficient' | 'none' | 'found', items: [{ category, label, artworkCount }] }
 */
export function repeatedWeaknesses(feedback, growth) {
  if (!growth) return { status: 'unknown', items: [] }
  const mentioned = new Set([
    ...(feedback.categories ?? []),
    ...[...(feedback.weaknesses ?? []), ...(feedback.fixes ?? [])]
      .map((item) => item.category)
      .filter(Boolean),
  ])
  const items = (growth.top_weaknesses ?? [])
    .filter((stat) => mentioned.has(stat.category) && stat.artwork_count >= 2)
    .map((stat) => ({ category: stat.category, label: stat.label, artworkCount: stat.artwork_count }))
  if (items.length) return { status: 'found', items }
  if (growth.status === 'INSUFFICIENT_DATA') return { status: 'insufficient', items: [] }
  return { status: 'none', items: [] }
}

/**
 * v0.9.9 첨삭 분류 태그 (요약 아래 칩). 서버 tags(9개 묶음)를 쓰고,
 * tags가 없는 응답(이전 서버)이면 기존 약점 카테고리로 대신한다.
 * 반환: [{ key, label, needsWork }]
 */
export function displayTags(feedback, categoryLabel = (code) => code) {
  if (Array.isArray(feedback?.tags)) {
    return feedback.tags.map((tag) => ({ key: tag.code, label: tag.label, needsWork: Boolean(tag.needs_work) }))
  }
  return (feedback?.categories ?? []).map((code) => ({ key: code, label: categoryLabel(code), needsWork: true }))
}
