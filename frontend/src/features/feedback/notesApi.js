import { api } from '../../lib/api'

// v0.9 F-3 텍스트 첨삭 (docs/frontend-integration-v0.9.md §3). 원문은 문장 단위(segments)로 나뉘어 AI 근거 번호가 됨

/** source: INSTRUCTOR(강사 첨삭을 받아 적음) | SELF_NOTE(자기 메모) | PEER(다른 학생 의견) */
export const createNote = (artworkId, { source, body, feedbackDate, requestSummary }) =>
  api(`/artworks/${artworkId}/feedback-notes`, {
    method: 'POST',
    body: {
      source,
      body,
      ...(feedbackDate ? { feedback_date: feedbackDate } : {}),
      request_summary: requestSummary,
    },
  })

/** 이 API는 배열을 그대로 돌려줌 */
export const listNotes = (artworkId) => api(`/artworks/${artworkId}/feedback-notes`)

export const getNote = (noteId) => api(`/feedback-notes/${noteId}`)

export const updateNote = (noteId, { version, source, body, feedbackDate }) =>
  api(`/feedback-notes/${noteId}`, {
    method: 'PATCH',
    body: { version, source, body, feedback_date: feedbackDate },
  })

export const deleteNote = (noteId) => api(`/feedback-notes/${noteId}`, { method: 'DELETE' })

/** AI 요약 요청. 이미 초안이 있으면 regenerate로 다시 만듦 */
export const requestNoteSummary = (noteId, { regenerate = false } = {}) =>
  api(`/feedback-notes/${noteId}/summary`, { method: 'POST', body: { regenerate } })
