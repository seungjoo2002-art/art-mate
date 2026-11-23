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
      title: '기록이 차곡차곡 쌓이는 중이에요',
      text: '작품이 조금 더 쌓이면 변화도 함께 살펴볼게요.',
    }
  }
  if (status === 'NEEDS_CONFIRMATION') {
    return {
      title: `확인할 첨삭이 ${counts.pending_review_count}개 있어요`,
      text: '정리된 첨삭을 확인하고 확정하면 여기에 담겨요.',
    }
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

// ------------------------------------------------------------------ 홈 브리핑 요약 (v1.2 UI)
// 서버의 구조화 필드(focus·highlight·practice·counts)로 짧고 친근한 문장을 만든다.
// - 영역 이름은 서버가 준 라벨(예: 형태·비례, 타원·원통형 형태)만 쓴다
// - '오늘의 연습'은 실제 첨삭 항목 문장을 그대로 인용한다. 없으면 만들지 않는다
// - 서버 headline·lines·AI 코멘트 원문은 '자세히 보기'에 그대로 둔다 (자르지 않음)

/** 받침 유무로 조사 고르기 (한글이 아니면 받침 없음으로 봄) */
export function josa(word, withBatchim, withoutBatchim) {
  const last = word.trim().at(-1) ?? ''
  const code = last.charCodeAt(0) - 0xac00
  const hasBatchim = code >= 0 && code <= 11171 && code % 28 !== 0
  return `${word}${hasBatchim ? withBatchim : withoutBatchim}`
}

const isGeneric = (focus) => focus?.tag === 'OTHER' && !focus.theme_label

function focusLines(focus) {
  const subject = focus.theme_label || focus.label
  if (isGeneric(focus)) {
    return {
      title: '오늘은 최근 첨삭을 다시 살펴볼까요? 🎨',
      text: '최근 첨삭에서 다듬어 보라는 이야기가 있었어요.',
    }
  }
  return {
    title: `오늘은 ${josa(subject, '을', '를')} 조금 더 신경 써 볼까요? 🎨`,
    text:
      focus.reason === 'REPEATED'
        ? `최근 작품 ${focus.artwork_count}개의 첨삭에서 ${subject} 이야기가 이어졌어요.`
        : `최근 첨삭에서 ${subject} 이야기가 있었어요.`,
  }
}

function highlightText(highlight) {
  const label = josa(highlight.label, '은', '는')
  if (highlight.kind === 'IMPROVING') return `${label} 지난번보다 좋아졌다는 첨삭이 있었어요.`
  if (highlight.kind === 'STRENGTH') {
    return `${label} 작품 ${highlight.artwork_count}개에서 칭찬을 받았어요.`
  }
  return `최근 첨삭에서 ${highlight.label} 칭찬이 있었어요.`
}

const SHORT_BY_STATUS = {
  NO_RECORDS: {
    title: '첫 작품을 기록해 볼까요? 🎨',
    text: '작품과 선생님 첨삭을 남기면 오늘 연습할 거리를 함께 골라 드릴게요.',
  },
  NO_FEEDBACK: {
    title: '선생님 첨삭을 남겨 볼까요?',
    text: '첨삭을 기록하고 확정하면 오늘의 브리핑이 시작돼요.',
  },
  PROCESSING: {
    title: '첨삭을 정리하고 있어요',
    text: '조금만 기다려 주세요. 정리가 끝나면 여기에 알려 드릴게요.',
  },
}

/**
 * 홈 브리핑 카드에 보여 줄 짧은 요약
 * 반환: { title, text, practice(첨삭 항목 Evidence|null), notes: [보조 안내], highlight: 문장|null }
 */
export function briefingSummary(briefing) {
  const { status, counts, focus, highlight, practice } = briefing
  const pending = counts.pending_review_count
  const notes = []
  if (status === 'NEEDS_CONFIRMATION') {
    return {
      title: `확인할 첨삭이 ${pending}개 있어요`,
      text: '내용을 확인하고 확정하면 오늘의 브리핑에 바로 반영돼요.',
      practice: null,
      highlight: null,
      notes,
    }
  }
  if (SHORT_BY_STATUS[status]) {
    return { ...SHORT_BY_STATUS[status], practice: null, highlight: null, notes }
  }

  // READY · INSUFFICIENT_DATA
  let title
  let text = null
  if (focus) {
    ;({ title, text } = focusLines(focus))
  } else if (highlight) {
    title = '최근 첨삭에 반가운 이야기가 있었어요 🎨'
    text = highlightText(highlight)
  } else {
    title = briefing.headline // 서버 문장 그대로 (드문 경우)
  }
  const praise = highlight && focus ? highlightText(highlight) : null
  if (status === 'INSUFFICIENT_DATA') notes.push('작품이 조금 더 쌓이면 변화도 함께 살펴볼게요.')
  if (pending) notes.push(`확인할 첨삭이 ${pending}개 있어요.`)
  return { title, text, practice: practice ?? null, highlight: praise, notes }
}
