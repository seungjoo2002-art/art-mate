// 녹음 → 글로 변환 → (선택) AI 정리 진행 화면의 상태 (순수 함수)
//
// 서버 작업 구조는 그대로다: 전사(TRANSCRIBE, faster-whisper)·요약(SUMMARIZE) 작업을 큐에 넣고 Worker가 처리.
// 화면은 서버 상태만 보고 "지금 무엇을 해야 하는지"를 정한다 → 화면을 나갔다 와도 같은 상태로 이어진다.
//
// goal: 'transcript' (글로 변환) | 'summary' (AI로 정리, 전사가 없으면 전사부터)

const ACTIVE = ['QUEUED', 'RUNNING']
const ENDED = ['FAILED', 'CANCELLED']

// 서버 처리는 보통 1~2분. 이보다 오래 걸리면 "오래 걸리고 있어요" 안내 (실패로 단정하지 않음)
export const SLOW_MS = 3 * 60 * 1000

// 같은 녹음으로 다시 해도 소용없는 실패의 안내 (그 밖은 다시 시도 가능)
const FAILURE_MESSAGES = {
  EMPTY_TRANSCRIPT: '녹음에서 말소리를 찾지 못했어요. 다시 녹음하거나 직접 글로 적어 주세요.',
  AUDIO_DECODE_FAILED: '이 녹음 파일은 글로 바꿀 수 없어요.',
  AUDIO_NOT_FOUND: '녹음 파일을 찾지 못했어요.',
  AUDIO_TOO_LARGE: '녹음 파일이 너무 커서 글로 바꿀 수 없어요.',
  AUDIO_TOO_LONG: '녹음이 너무 길어서 글로 바꿀 수 없어요.',
  SOURCE_URL_EXPIRED: '처리 대기 시간이 길어졌어요. 다시 시도해 주세요.',
  STT_NOT_CONFIGURED: '서버 음성 변환이 아직 설정되지 않았어요.',
  TRANSCRIPT_TOO_LONG: '대본이 너무 길어 아트메이트가 정리할 수 없어요.',
  LLM_OUTPUT_TRUNCATED: '아트메이트가 정리할 수 없는 녹음이에요.',
  LLM_BLOCKED: '아트메이트가 정리할 수 없는 녹음이에요.',
  LLM_QUOTA_EXCEEDED: '지금은 AI 정리를 사용할 수 없어요.',
  AI_NOT_CONFIGURED: 'AI 정리 기능이 아직 설정되지 않았어요.',
  RECORDING_CONSENT_REVOKED: '녹음 동의가 철회되어 취소됐어요.',
  AI_CONSENT_REVOKED: 'AI 정리 동의가 철회되어 취소됐어요.',
}

const failureMessage = (job, fallback) => FAILURE_MESSAGES[job?.error_code] ?? fallback

const isSlow = (job, now) => Boolean(job?.created_at) && now - Date.parse(job.created_at) > SLOW_MS

/**
 * → { step, ... }
 *  - startTranscription  전사 작업이 없음 → 요청한다 (summary면 끝나고 AI 정리까지)
 *  - advance             예전 기기 변환용 '미뤄 둔' 서버 작업이 대기 중 → 지금 처리하도록 다시 요청
 *  - transcribing        서버가 글로 바꾸는 중 (slow: 오래 걸림 안내)
 *  - startSummary        대본은 있고 AI 정리 작업이 없음 → 요청한다
 *  - summarizing         AI가 정리하는 중 (slow)
 *  - done                끝 → target 화면으로 이동 (feedbackId: 정리 결과)
 *  - failed              실패 (stage: transcription | summary, message, canRetry)
 * poll: 다시 확인할 간격(ms). 요청을 보낸 직후(start·advance)에도 확인한다 (요청이 반영됐는지). 끝·실패면 null
 */
export function processingState({ goal, transcription, summary, now = Date.now() }) {
  const tJob = transcription?.job ?? null
  const sJob = summary?.job ?? null
  const hasTranscript =
    transcription?.transcription_status === 'COMPLETED' || Boolean(transcription?.transcript)

  if (goal === 'summary' && summary?.feedback_id) {
    return { step: 'done', feedbackId: summary.feedback_id, poll: null }
  }
  if (goal === 'transcript' && hasTranscript) return { step: 'done', poll: null }

  if (!hasTranscript) {
    if (tJob && ACTIVE.includes(tJob.status)) {
      const deferred =
        tJob.status === 'QUEUED' &&
        tJob.next_attempt_at &&
        Date.parse(tJob.next_attempt_at) > now + 5_000 &&
        !tJob.error_code // 실패 후 자동 재시도 대기는 서버가 알아서 다시 함
      if (deferred) return { step: 'advance', poll: 4_000 }
      const slow = isSlow(tJob, now)
      return {
        step: 'transcribing',
        slow,
        retrying: tJob.attempts > 0 && Boolean(tJob.error_code),
        poll: slow ? 10_000 : 4_000,
      }
    }
    // 기기 전사로 대체되며 취소된 작업은 실패가 아님 (예전 흐름의 기록)
    if (tJob && ENDED.includes(tJob.status) && tJob.error_code !== 'BROWSER_TRANSCRIBED') {
      return {
        step: 'failed',
        stage: 'transcription',
        message: failureMessage(tJob, '글로 바꾸지 못했어요.'),
        canRetry: Boolean(tJob.retryable),
        poll: null,
      }
    }
    return { step: 'startTranscription', poll: 4_000 }
  }

  // 대본 있음 + AI 정리 목표
  if (sJob && ACTIVE.includes(sJob.status)) {
    const slow = isSlow(sJob, now)
    return {
      step: 'summarizing',
      slow,
      retrying: sJob.attempts > 0 && Boolean(sJob.error_code),
      poll: slow ? 10_000 : 4_000,
    }
  }
  if (sJob?.status === 'FAILED') {
    return {
      step: 'failed',
      stage: 'summary',
      message: failureMessage(sJob, '아트메이트가 첨삭을 정리하지 못했어요.'),
      canRetry: Boolean(sJob.retryable),
      poll: null,
    }
  }
  // 작업 없음·취소(대본 수정 등)·전사와 함께 요청되지 않음 → AI 정리 요청
  return { step: 'startSummary', poll: 4_000 }
}

/** 진행 화면 문구 */
export function processingText(state, goal) {
  switch (state.step) {
    case 'startTranscription':
    case 'advance':
    case 'transcribing':
      return {
        title: state.retrying ? '다시 시도하고 있어요…' : '글로 바꾸고 있어요…',
        detail:
          goal === 'summary'
            ? '글로 바꾼 뒤 이어서 아트메이트가 첨삭을 정리해요. 보통 1~2분 걸려요.'
            : '보통 1~2분 걸려요.',
      }
    case 'startSummary':
    case 'summarizing':
      return {
        title: state.retrying ? '다시 시도하고 있어요…' : '첨삭을 정리하고 있어요…',
        detail: '잘한 점·개선할 점·다음 연습으로 나눠 정리해요.',
      }
    case 'failed':
      return { title: state.stage === 'summary' ? 'AI 정리에 실패했어요' : '글로 바꾸지 못했어요', detail: state.message }
    default:
      return { title: '거의 다 됐어요', detail: null }
  }
}

export const processingPath = (artworkId, recordingId, goal) =>
  `/artworks/${artworkId}/recordings/${recordingId}/processing?goal=${goal}`
