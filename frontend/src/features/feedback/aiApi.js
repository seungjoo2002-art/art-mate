import { api } from '../../lib/api'

// v0.6 AI 첨삭 (docs/frontend-integration-v0.6.md). 개인 작품은 학생 본인이 검토·확정(review_mode SELF)

// 동의 목적: FEEDBACK_SUMMARY(첨삭 요약, v0.6) / GROWTH_COACHING(성장 리포트 설명·AI 연습 과제, v0.7). 서로 별개
export const getAiConsent = (purpose = 'FEEDBACK_SUMMARY') =>
  api(`/ai-processing-consents/me?purpose=${purpose}`)

export const revokeAiConsent = (purpose = 'FEEDBACK_SUMMARY') => {
  consentCache = null
  return api(`/ai-processing-consents/me?purpose=${purpose}`, { method: 'DELETE' })
}

/**
 * AI 전송 동의 (v0.9.6). birthYearMonth 'YYYY-MM'은 서버가 나이 구간 계산에만 쓰고 저장하지 않는다.
 * 만 18세 미만이면 응답에 guardian_token(한 번만) → 보호자 확인 링크로 보낸다
 */
export const saveAiConsent = ({ purpose = 'FEEDBACK_SUMMARY', policyVersion, birthYearMonth }) => {
  consentCache = null
  return api('/ai-processing-consents', {
    method: 'POST',
    body: { purpose, policy_version: policyVersion, agreed: true, birth_year_month: birthYearMonth },
  })
}

/** 보호자 확인 링크 다시 만들기 (이전 링크는 무효) */
export const renewGuardianLink = (purpose = 'FEEDBACK_SUMMARY') =>
  api(`/ai-processing-consents/me/guardian-link?purpose=${purpose}`, { method: 'POST' })

// 보호자 확인 (로그인 없이 링크 토큰으로)
export const getGuardianConsent = (token) => api(`/guardian-consents/${encodeURIComponent(token)}`)

export const confirmGuardianConsent = (token, { guardianName, relationship }) =>
  api(`/guardian-consents/${encodeURIComponent(token)}`, {
    method: 'POST',
    body: { guardian_name: guardianName, relationship, agreed: true },
  })

let consentCache = null // { at, promise } — 녹음 카드 여러 개가 같은 요청을 반복하지 않도록

/** 첨삭 요약 동의 상태 (30초 캐시, 동의·철회하면 비움). 실패하면 null (모름) */
export function getAiConsentCached() {
  if (!consentCache || Date.now() - consentCache.at > 30_000) {
    const promise = getAiConsent().catch(() => {
      consentCache = null
      return null
    })
    consentCache = { at: Date.now(), promise }
  }
  return consentCache.promise
}

let featuresCache = null

/**
 * AI·음성 변환 기능 사용 가능 여부 (GET /meta/ai-features, 인증 불필요).
 * 이 API가 없는 이전 서버이거나 실패하면 null → 화면은 "사용 가능"으로 보고 요청 시 오류로 안내
 */
export function getAiFeatures() {
  if (!featuresCache) {
    featuresCache = api('/meta/ai-features').catch(() => {
      featuresCache = null
      return null
    })
  }
  return featuresCache
}

const recordingPath = (artworkId, recordingId) => `/artworks/${artworkId}/recordings/${recordingId}`

/** 전사(STT) 요청. autoSummarize면 전사가 끝난 뒤 AI 요약까지 자동으로 이어짐 */
/**
 * deferSeconds(v0.9.3): 기기에서 변환하는 동안 만들어 두는 백업 서버 작업 — 그 시간 뒤에 서버가 처리.
 * 기기 전사가 저장되면 자동 취소된다. 0(기본)으로 다시 부르면 대기 중인 백업을 바로 처리하도록 앞당김.
 * (0일 때는 필드를 보내지 않아 이전 서버와도 호환)
 */
export const requestTranscription = (
  artworkId,
  recordingId,
  { autoSummarize = true, deferSeconds = 0 } = {},
) =>
  api(`${recordingPath(artworkId, recordingId)}/transcription`, {
    method: 'POST',
    body: { auto_summarize: autoSummarize, ...(deferSeconds > 0 ? { defer_seconds: deferSeconds } : {}) },
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
