import { api } from '../../lib/api'

// v0.6 AI 첨삭 (docs/frontend-integration-v0.6.md). 개인 작품은 학생 본인이 검토·확정(review_mode SELF)

export const getAiConsent = () => api('/ai-processing-consents/me')

export const revokeAiConsent = () => api('/ai-processing-consents/me', { method: 'DELETE' })

export const saveAiConsent = ({ policyVersion, grantedBy }) =>
  api('/ai-processing-consents', {
    method: 'POST',
    body: { policy_version: policyVersion, agreed: true, granted_by: grantedBy },
  })

const recordingPath = (artworkId, recordingId) =>
  `/artworks/${artworkId}/recordings/${recordingId}`

/** 전사(STT) 요청. autoSummarize면 전사가 끝난 뒤 AI 요약까지 자동으로 이어짐 */
export const requestTranscription = (artworkId, recordingId, { autoSummarize = true } = {}) =>
  api(`${recordingPath(artworkId, recordingId)}/transcription`, {
    method: 'POST',
    body: { auto_summarize: autoSummarize },
  })

export const retryTranscription = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/transcription/retry`, { method: 'POST' })

export const getTranscriptionStatus = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/transcription`)

export const requestSummary = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/summary`, { method: 'POST' })

export const regenerateSummary = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/summary/regenerate`, { method: 'POST' })

export const getSummaryStatus = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/summary`)

/**
 * "AI로 정리하기": 전사 + 자동 요약 요청. 이미 전사된 녹음이면 요약만 요청
 * AI 전송 동의가 없으면 아무것도 요청하지 않고 { needsConsent: true }
 */
export async function startAiSummary(artworkId, recordingId) {
  const consent = await getAiConsent()
  if (!consent.is_valid) return { needsConsent: true }
  try {
    await requestTranscription(artworkId, recordingId, { autoSummarize: true })
  } catch (err) {
    if (err.code !== 'TRANSCRIPTION_ALREADY_DONE') throw err
    await requestSummary(artworkId, recordingId)
  }
  return { needsConsent: false }
}

export const getFeedback = (feedbackId) => api(`/feedbacks/${feedbackId}`)

/** 전체 교체: 보낸 items가 최종 상태 (기존 항목은 id 포함, 빠지면 삭제) */
export const updateFeedback = (feedbackId, body) =>
  api(`/feedbacks/${feedbackId}`, { method: 'PATCH', body })

export const approveFeedback = (feedbackId, version) =>
  api(`/feedbacks/${feedbackId}/approve`, { method: 'POST', body: { version } })

export const reopenFeedback = (feedbackId, version) =>
  api(`/feedbacks/${feedbackId}/reopen`, { method: 'POST', body: { version } })
