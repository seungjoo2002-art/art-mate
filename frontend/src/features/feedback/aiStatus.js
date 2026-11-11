// 녹음의 전사·요약 상태를 화면 상태 하나로 정리 (docs/frontend-integration-v0.6.md §6)

const ACTIVE = ['QUEUED', 'RUNNING']

// 같은 파일로 다시 해도 소용없는 실패
const PERMANENT_ERRORS = {
  EMPTY_TRANSCRIPT: '녹음에서 말소리를 찾지 못했어요.',
  AUDIO_DECODE_FAILED: '이 녹음은 글로 바꿀 수 없어요.',
  AUDIO_NOT_FOUND: '이 녹음은 글로 바꿀 수 없어요.',
  AUDIO_TOO_LARGE: '이 녹음은 글로 바꿀 수 없어요.',
  AUDIO_TOO_LONG: '이 녹음은 글로 바꿀 수 없어요.',
  TRANSCRIPT_TOO_LONG: 'AI가 정리할 수 없는 녹음이에요.',
  LLM_OUTPUT_TRUNCATED: 'AI가 정리할 수 없는 녹음이에요.',
  LLM_BLOCKED: 'AI가 정리할 수 없는 녹음이에요.',
  LLM_AUTH_FAILED: 'AI 정리 기능에 문제가 있어요. 잠시 후 이용해 주세요.',
  LLM_BAD_REQUEST: 'AI 정리 기능에 문제가 있어요. 잠시 후 이용해 주세요.',
  STT_NOT_CONFIGURED: 'AI 정리 기능은 아직 준비 중이에요.',
  AI_NOT_CONFIGURED: 'AI 정리 기능은 아직 준비 중이에요.',
  RECORDING_CONSENT_REVOKED: '녹음 동의가 철회되어 취소됐어요.',
  AI_CONSENT_REVOKED: 'AI 정리 동의가 철회되어 취소됐어요.',
}

function jobMessage(job) {
  return PERMANENT_ERRORS[job.error_code] ?? '잠시 후 다시 시도해 주세요.'
}

/**
 * phase:
 *  - idle          아직 요청 안 함 → "AI로 정리하기"
 *  - transcribing  글로 바꾸는 중 (polling)
 *  - summarizing   AI가 정리하는 중 (polling)
 *  - needsSummary  전사는 끝났는데 요약이 없음 → "AI 요약 만들기"
 *  - failed        실패 (retry: 'transcription' | 'summary' | null)
 *  - ready         정리 결과 있음 (feedbackId, feedbackStatus)
 */
export function aiPhase(transcription, summary) {
  const tJob = transcription?.job
  const sJob = summary?.job

  if (summary?.feedback_id) {
    return {
      phase: 'ready',
      feedbackId: summary.feedback_id,
      feedbackStatus: summary.feedback_status,
    }
  }
  if (sJob && ACTIVE.includes(sJob.status)) {
    return { phase: 'summarizing', retrying: sJob.attempts > 0 && Boolean(sJob.error_code) }
  }
  if (tJob && ACTIVE.includes(tJob.status)) {
    return { phase: 'transcribing', retrying: tJob.attempts > 0 && Boolean(tJob.error_code) }
  }
  if (sJob && ['FAILED', 'CANCELLED'].includes(sJob.status)) {
    return { phase: 'failed', message: jobMessage(sJob), retry: sJob.retryable ? 'summary' : null }
  }
  if (tJob && ['FAILED', 'CANCELLED'].includes(tJob.status)) {
    return {
      phase: 'failed',
      message: jobMessage(tJob),
      retry: tJob.retryable ? 'transcription' : null,
    }
  }
  if (transcription?.transcription_status === 'COMPLETED') return { phase: 'needsSummary' }
  return { phase: 'idle' }
}

/** 상태를 다시 확인할 간격(ms). 진행 중이 아니면 null */
export function pollDelay(state) {
  if (!['transcribing', 'summarizing'].includes(state.phase)) return null
  return state.retrying ? 10_000 : 5_000
}
