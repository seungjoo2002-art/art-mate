import { api } from '../../lib/api'

// v0.6 AI 첨삭 (docs/frontend-integration-v0.6.md). 개인 작품은 학생 본인이 검토·확정(review_mode SELF)

// 동의 목적: FEEDBACK_SUMMARY(첨삭 요약, v0.6) / GROWTH_COACHING(성장 리포트 설명·AI 연습 과제, v0.7). 서로 별개
export const getAiConsent = (purpose = 'FEEDBACK_SUMMARY') =>
  api(`/ai-processing-consents/me?purpose=${purpose}`)

export const revokeAiConsent = (purpose = 'FEEDBACK_SUMMARY') =>
  api(`/ai-processing-consents/me?purpose=${purpose}`, { method: 'DELETE' })

export const saveAiConsent = ({ purpose = 'FEEDBACK_SUMMARY', policyVersion, grantedBy }) =>
  api('/ai-processing-consents', {
    method: 'POST',
    body: { purpose, policy_version: policyVersion, agreed: true, granted_by: grantedBy },
  })

const recordingPath = (artworkId, recordingId) => `/artworks/${artworkId}/recordings/${recordingId}`

/** 전사(STT) 요청. autoSummarize면 전사가 끝난 뒤 AI 요약까지 자동으로 이어짐 */
export const requestTranscription = (artworkId, recordingId, { autoSummarize = true } = {}) =>
  api(`${recordingPath(artworkId, recordingId)}/transcription`, {
    method: 'POST',
    body: { auto_summarize: autoSummarize },
  })

/**
 * 기기(브라우저)에서 만든 전사 저장 (v0.9.2). 대기 중인 서버 전사는 취소된다
 * sttResult: browserStt.transcribeBlob 결과. autoSummarize면 AI 요약도 요청 (AI 동의가 있을 때만 생성)
 */
export const saveBrowserTranscript = (artworkId, recordingId, sttResult, { autoSummarize = false } = {}) =>
  api(`${recordingPath(artworkId, recordingId)}/transcript/browser`, {
    method: 'POST',
    body: {
      device: sttResult.device,
      model_name: sttResult.model,
      language: 'ko',
      segments: sttResult.segments,
      processing_ms: sttResult.timings.transcribeMs,
      auto_summarize: autoSummarize,
    },
  })

export const retryTranscription = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/transcription/retry`, { method: 'POST' })

export const getTranscriptionStatus = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/transcription`)

/** 전사 원문 (문장 구간 segments: index, start_ms, end_ms, text) */
export const getTranscript = (artworkId, recordingId) =>
  api(`${recordingPath(artworkId, recordingId)}/transcript`)

/**
 * 전사 수정 (v0.9 §3.2): 바꾼 구간 문장만. 원본은 보존되고 새 버전이 현재 전사가 됨.
 * 초안 요약은 대체되므로 다시 요약 요청 필요. 확정된 첨삭이 있으면 409 TRANSCRIPT_LOCKED
 */
export const updateTranscript = (artworkId, recordingId, { baseTranscriptId, segments }) =>
  api(`${recordingPath(artworkId, recordingId)}/transcript`, {
    method: 'PUT',
    body: { base_transcript_id: baseTranscriptId, segments },
  })

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
