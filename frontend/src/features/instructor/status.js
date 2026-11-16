// v1.0 강사 화면 표시용 (순수 함수)

export const FEEDBACK_STATUS = {
  DRAFT: { label: 'AI 초안', tone: 'todo' },
  IN_REVIEW: { label: '검토 중', tone: 'todo' },
  APPROVED: { label: '승인됨', tone: 'done' },
  REJECTED: { label: '반려됨', tone: 'danger' },
  SUPERSEDED: { label: '대체됨', tone: 'plain' },
}

export const TRANSCRIPTION_STATUS = {
  NOT_REQUESTED: { label: '전사 전', tone: 'plain' },
  PENDING: { label: '전사 대기', tone: 'todo' },
  PROCESSING: { label: '전사 중', tone: 'todo' },
  COMPLETED: { label: '전사 완료', tone: 'done' },
  FAILED: { label: '전사 실패', tone: 'danger' },
}

const pad = (n) => String(n).padStart(2, '0')

export function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatClock(ms) {
  const total = Math.max(0, Math.floor((ms ?? 0) / 1000))
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`
}
