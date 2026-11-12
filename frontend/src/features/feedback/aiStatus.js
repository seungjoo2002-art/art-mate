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
  STT_NOT_CONFIGURED: '서버 음성 변환이 아직 설정되지 않았어요.',
  AI_NOT_CONFIGURED: 'AI 정리 기능이 아직 설정되지 않았어요.',
  SOURCE_URL_EXPIRED: '변환 대기 시간이 길어 다시 요청이 필요해요.',
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
  // 기기(브라우저) 전사가 저장되며 취소된 서버 작업은 실패가 아님 (v0.9.2)
  const replacedByBrowser = tJob?.error_code === 'BROWSER_TRANSCRIBED'
  if (tJob && !replacedByBrowser && ['FAILED', 'CANCELLED'].includes(tJob.status)) {
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

// 서버 작업이 이 시간 넘게 대기하면 "늦어지고 있어요" 안내 + 이 기기에서 바로 바꾸기 제안
// (Worker 즉시 실행 요청이 켜져 있으면 보통 몇 분, 꺼져 있으면 GitHub 예약 실행에 따라 몇 시간)
export const SERVER_DELAY_MS = 10 * 60 * 1000

const DEVICE_BUSY = ['queued', 'preparing', 'transcribing', 'saving']

/**
 * 녹음 카드 화면 상태 (v0.9.3). aiPhase에 기기 변환·기능 설정·대기 지연을 더한다
 * kind:
 *  - idle               아직 글로 바꾸지 않음 → "녹음을 글로 바꾸기"
 *  - deviceTranscribing 이 기기에서 모델 준비·변환·저장 중 (devicePhase)
 *  - interrupted        이 기기 변환이 중간에 끊김 (새로고침·탭 종료) → 이어서 변환 / 서버에서 변환
 *  - serverDeferred     기기 변환용 백업 서버 작업이 대기 중 (deferredUntil 이후 서버가 처리)
 *  - serverQueued       서버 변환 대기 중 (delayed면 늦어짐 안내)
 *  - serverRunning      서버에서 변환 중
 *  - transcribed        전사 완료 → 대본 보기 + AI 정리 (aiAvailable일 때)
 *  - summarizing        AI 정리 중 (delayed면 늦어짐 안내)
 *  - ready              AI 정리 완료 → 결과 보기 + 대본 보기
 *  - failed             실패 (retry: 'transcription' | 'summary' | null)
 * hasTranscript: 대본 보기 버튼 표시, aiAvailable: AI 정리 기능 설정 여부
 * devicePhase: deviceJobs 작업 phase, interrupted: deviceJobs.getInterrupted 결과
 */
export function recordingCardState({
  transcription,
  summary,
  features,
  devicePhase,
  interrupted = null,
  now = Date.now(),
}) {
  const base = aiPhase(transcription, summary)
  const hasTranscript = transcription?.transcription_status === 'COMPLETED' || Boolean(transcription?.transcript)
  const aiAvailable = features ? features.ai_summary !== false : true
  const serverAvailable = features ? features.server_transcription !== false : true
  const common = { hasTranscript, aiAvailable, serverAvailable }
  const delayed = (job) =>
    Boolean(job?.created_at) && now - Date.parse(job.created_at) > SERVER_DELAY_MS

  if (DEVICE_BUSY.includes(devicePhase) && !hasTranscript) {
    return { ...common, kind: 'deviceTranscribing' }
  }
  const tJob = transcription?.job
  const deferredUntil =
    tJob?.status === 'QUEUED' && tJob.next_attempt_at && Date.parse(tJob.next_attempt_at) > now
      ? tJob.next_attempt_at
      : null
  if (interrupted && !hasTranscript && (base.phase === 'idle' || deferredUntil)) {
    return { ...common, kind: 'interrupted', interrupted, deferredUntil }
  }
  switch (base.phase) {
    case 'transcribing': {
      if (deferredUntil) return { ...common, kind: 'serverDeferred', deferredUntil }
      return tJob.status === 'RUNNING'
        ? { ...common, kind: 'serverRunning', retrying: base.retrying }
        : { ...common, kind: 'serverQueued', retrying: base.retrying, delayed: delayed(tJob) }
    }
    case 'summarizing':
      return { ...common, kind: 'summarizing', retrying: base.retrying, delayed: delayed(summary.job) }
    case 'needsSummary':
      return { ...common, kind: 'transcribed', hasTranscript: true }
    case 'ready':
      return { ...common, kind: 'ready', feedbackId: base.feedbackId, feedbackStatus: base.feedbackStatus }
    case 'failed':
      return { ...common, kind: 'failed', message: base.message, retry: base.retry }
    default:
      return { ...common, kind: 'idle' }
  }
}
