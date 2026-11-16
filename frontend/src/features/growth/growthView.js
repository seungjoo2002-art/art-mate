// v1.0 개인 성장 분석 화면 계산 (순수 함수). 규칙 기반 통계만 쓰며 AI 채점·실력 판정이 아님.

/** 9개 첨삭 태그 (백엔드 FeedbackTag와 같은 순서·라벨) */
export const TAG_LABELS = {
  COMPOSITION: '구도',
  FORM_PROPORTION: '형태·비례',
  VALUE: '명암',
  COLOR: '색채',
  PERSPECTIVE_SPACE: '원근·공간감',
  TEXTURE_EXPRESSION: '질감·표현',
  FINISH: '완성도',
  TIME_MANAGEMENT: '시간 관리',
  OTHER: '기타',
}

/**
 * 반복 실수 목록 (9개 태그 기준). tags가 없는 이전 서버 응답이면 기존 11개 카테고리로 대신한다.
 * 반환: [{ key, label, count, ratio, repeated, recent, previous, trend, strength }]
 */
export function mistakeRows(analysis) {
  if (Array.isArray(analysis?.tags)) {
    return analysis.tags
      .filter((t) => t.weakness_artwork_count > 0)
      .map((t) => ({
        key: t.tag,
        label: t.label,
        count: t.weakness_artwork_count,
        ratio: t.weakness_ratio,
        repeated: t.repeated,
        recent: t.recent,
        previous: t.previous,
        trend: t.trend,
        strength: t.strength_artwork_count,
      }))
  }
  return (analysis?.weaknesses ?? []).map((w) => ({
    key: w.category,
    label: w.label,
    count: w.artwork_count,
    ratio: w.artwork_ratio,
    repeated: w.repeated,
    recent: w.recent,
    previous: w.previous,
    trend: w.trend,
    strength: 0,
  }))
}

/** 최근·이전 구간을 비교할 수 있는 항목만 */
export const compareRows = (analysis) =>
  mistakeRows(analysis).filter((r) => r.previous && r.trend !== 'INSUFFICIENT_DATA')

/** 항목별 강점·약점 언급 막대 (작품 수). max는 막대 길이 기준 */
export function mentionBars(analysis) {
  const rows = (analysis?.tags ?? [])
    .map((t) => ({
      key: t.tag,
      label: t.label,
      weak: t.weakness_artwork_count,
      strong: t.strength_artwork_count,
    }))
    .filter((r) => r.weak + r.strong > 0)
  const max = Math.max(1, ...rows.map((r) => Math.max(r.weak, r.strong)))
  return { rows, max }
}

/** 기간별 첨삭 횟수 (월·주 버킷). feedback_count가 없는 이전 응답이면 첨삭이 있는 작품 수 */
export function periodCounts(analysis) {
  const week = analysis?.timeline_bucket === 'week'
  return (analysis?.timeline ?? []).map((b) => {
    const [y, m, d] = b.bucket_start.split('-').map(Number)
    return {
      key: b.bucket_start,
      label: week ? `${m}/${d}주` : `${String(y).slice(2)}.${m}월`,
      count: b.feedback_count ?? b.analyzed_artwork_count,
      artworks: b.analyzed_artwork_count,
    }
  })
}

/** 최근 활동: 타임라인(최근 작업일순) 첫 항목 */
export function lastActivity(items = []) {
  const latest = items[0]
  if (!latest) return null
  return {
    artworkId: latest.artwork_id,
    title: latest.title,
    workDate: latest.work_date,
    feedbackCount: latest.feedbacks?.length ?? 0,
  }
}

/** 최근 연습 과제의 상태: 담기 전(add) · 진행 중(todo) · 완료(done) */
export function tipState(tip) {
  if (!tip?.task) return 'add'
  return tip.task.status === 'COMPLETED' ? 'done' : 'todo'
}

/** 0~1 비율 → '40%' */
export const percent = (ratio) => (ratio == null ? '-' : `${Math.round(ratio * 100)}%`)
