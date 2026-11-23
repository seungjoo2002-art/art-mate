// v1.2 홈 브리핑·아카이브 분석 리포트 화면 계산 (docs/feedback-archive-v1.2.md §8)
// 원칙: 서버가 준 문장·숫자만 보여 준다. 점수·성장률·백분율을 화면에서 만들지 않는다.

/** 브리핑 status → 카드 라벨·이동 버튼. headline·lines는 서버 문장을 그대로 쓴다 */
const BRIEFING_CTA = {
  NO_RECORDS: { label: '새 작품 기록하기', to: '/artworks/new' },
  NO_FEEDBACK: { label: '내 작품에서 첨삭 기록하기', to: '/archive' },
  PROCESSING: null,
  NEEDS_CONFIRMATION: { label: '작품에서 정리 결과 확인하기', to: '/archive' },
  INSUFFICIENT_DATA: { label: '분석 리포트 보기', to: '/archive?tab=report' },
  READY: { label: '분석 리포트 보기', to: '/archive?tab=report' },
}

const BRIEFING_META = {
  NO_RECORDS: '아직 기록 없음',
  NO_FEEDBACK: '확정한 첨삭 없음',
  PROCESSING: '첨삭 정리 중',
  NEEDS_CONFIRMATION: '확정 대기',
  INSUFFICIENT_DATA: '기록 쌓는 중',
}

export function briefingView(briefing) {
  const { status, counts } = briefing
  return {
    title: briefing.headline,
    lines: briefing.lines ?? [],
    meta:
      BRIEFING_META[status] ??
      `확정 첨삭 ${counts.instructor_feedback_count}건 · 작품 ${counts.analyzed_artwork_count}개 기준`,
    cta: BRIEFING_CTA[status] ?? null,
  }
}

/**
 * 저장된 AI 설명문 상태 → 표시 여부·안내. 내용이 없으면 null (카드에 아무것도 안 붙임)
 * READY: 현재 데이터 기준 / STALE·FAILED: 이전 설명문 (최신 첨삭 반영 전) / PENDING: 갱신 중
 */
export function aiCommentView(ai) {
  if (!ai) return null
  const text = ai.overview || null
  switch (ai.status) {
    case 'READY':
      return text ? { label: 'AI 코멘트', text, note: null, pending: false } : null
    case 'STALE':
      return text
        ? { label: '이전 AI 코멘트', text, note: '최근 확정한 첨삭이 반영되기 전 내용이에요.', pending: false }
        : null
    case 'PENDING':
      return {
        label: 'AI 코멘트',
        text,
        note: text
          ? '새 첨삭으로 코멘트를 다시 정리하는 중이에요. 지금은 이전 내용이에요.'
          : '새 첨삭으로 AI 코멘트를 정리하는 중이에요.',
        pending: true,
      }
    case 'FAILED':
      return text
        ? { label: '이전 AI 코멘트', text, note: '코멘트를 새로 정리하지 못해 이전 내용을 보여 드려요.', pending: false }
        : null
    default:
      return null // NOT_AVAILABLE · NONE
  }
}

/** 다시 조회할 상태 (조회만 — 서버가 AI를 새로 부르지 않음) */
export const briefingNeedsPolling = (briefing) =>
  briefing?.status === 'PROCESSING' || briefing?.ai_comment?.status === 'PENDING'

// ------------------------------------------------------------------ 분석 리포트

export const PROGRESS_LABELS = {
  IMPROVING: '개선 추세',
  NEEDS_WORK: '개선 필요',
  CONSISTENT_STRENGTH: '꾸준한 강점',
  INSUFFICIENT: '판단 보류',
}

export const POLARITY_LABELS = { NEG: '지적', POS: '칭찬', MIXED: '칭찬+지적' }

/** 리포트 status → 맨 위 안내 (응원 문구) */
export function reportIntro(report) {
  const { status, counts } = report
  if (status === 'READY') {
    return {
      title: '기록이 차곡차곡 쌓이고 있어요!',
      text: `확정한 강사 첨삭 ${counts.instructor_feedback_count}건(작품 ${counts.analyzed_artwork_count}개)을 근거로 정리했어요.`,
    }
  }
  if (status === 'INSUFFICIENT_DATA') {
    return {
      title: '첨삭이 조금 더 쌓이면 분석할 수 있어요',
      text: report.message,
    }
  }
  if (status === 'NEEDS_CONFIRMATION') {
    return { title: '확정을 기다리는 첨삭이 있어요', text: report.message }
  }
  return {
    title: counts.artwork_count ? '첨삭을 기록해 보세요' : '작품 하나부터 차근차근 시작해 보세요!',
    text: report.message,
  }
}

/** 반복 실수 한 줄 설명 (서버 숫자·날짜만) */
export function repeatedLine(tag, formatDate) {
  const last = tag.last_issue_date ? ` · 마지막 지적 ${formatDate(tag.last_issue_date)}` : ''
  return `작품 ${tag.issue_artwork_count}개에서 지적${last}`
}

export function strengthLine(tag, formatDate) {
  const last = tag.last_positive_date ? ` · 최근 ${formatDate(tag.last_positive_date)}` : ''
  return `작품 ${tag.positive_artwork_count}개에서 긍정 평가${last}`
}

/** 개선 추세 설명: 첫 지적 → 이후 긍정 (확인 여부) */
export function improvingLine(tag, formatDate) {
  const from = tag.first_issue_date ? `${formatDate(tag.first_issue_date)} 지적 이후 ` : '지적 이후 '
  return tag.improvement_confirmed
    ? `${from}작품 ${tag.positive_since_last_issue}개에서 연속으로 긍정 평가`
    : `${from}최근 작품에서 긍정 평가 (아직 1개 작품이라 더 지켜봐야 해요)`
}

/** 작업일 순 사건 (오래된 것 먼저) — 서버가 이미 정렬해서 준다 */
export const trendSteps = (tag) =>
  (tag.events ?? []).map((e) => ({
    key: `${e.artwork_id}-${e.work_date}`,
    date: e.work_date,
    polarity: e.polarity,
    label: POLARITY_LABELS[e.polarity] ?? e.polarity,
  }))
