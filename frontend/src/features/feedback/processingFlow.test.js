import { describe, expect, it } from 'vitest'
import { SLOW_MS, processingState, processingText } from './processingFlow'

const NOW = Date.parse('2026-11-24T10:00:00Z')
const ago = (ms) => new Date(NOW - ms).toISOString()
const job = (status, extra = {}) => ({
  id: 'j1',
  status,
  attempts: 0,
  error_code: null,
  retryable: false,
  next_attempt_at: null,
  created_at: ago(30_000),
  ...extra,
})
const state = (goal, transcription, summary = null) =>
  processingState({ goal, transcription, summary, now: NOW })

const NONE = { transcription_status: 'NOT_REQUESTED', job: null, transcript: null }
const DONE = { transcription_status: 'COMPLETED', job: job('SUCCEEDED'), transcript: { id: 't1' } }

describe('글로 변환하기', () => {
  it('전사 작업이 없으면 바로 요청 (중간 단계 없음)', () => {
    expect(state('transcript', NONE).step).toBe('startTranscription')
    // 요청 직후에도 상태를 다시 읽는다 (반영 안 되면 끝없이 돌지 않게)
    expect(state('transcript', NONE).poll).toBe(4_000)
    expect(state('summary', DONE, null).poll).toBe(4_000)
  })

  it('서버 처리 중이면 기다리며 확인, 끝나면 대본으로', () => {
    const running = state('transcript', { transcription_status: 'PROCESSING', job: job('RUNNING') })
    expect(running).toMatchObject({ step: 'transcribing', slow: false, poll: 4_000 })
    expect(state('transcript', DONE).step).toBe('done')
  })

  it('오래 걸려도 실패로 단정하지 않고 천천히 계속 확인', () => {
    const slow = state('transcript', {
      transcription_status: 'PENDING',
      job: job('QUEUED', { created_at: ago(SLOW_MS + 1_000) }),
    })
    expect(slow).toMatchObject({ step: 'transcribing', slow: true, poll: 10_000 })
  })

  it('예전 기기 변환이 남긴 미뤄 둔 서버 작업은 지금 처리하도록 앞당김', () => {
    const deferred = job('QUEUED', { next_attempt_at: new Date(NOW + 10 * 60_000).toISOString() })
    expect(state('transcript', { transcription_status: 'PENDING', job: deferred }).step).toBe('advance')
  })

  it('실패 후 서버 자동 재시도 대기는 기다림 (앞당기지 않음)', () => {
    const retrying = job('QUEUED', {
      attempts: 1,
      error_code: 'STT_TIMEOUT',
      next_attempt_at: new Date(NOW + 60_000).toISOString(),
    })
    expect(state('transcript', { transcription_status: 'PENDING', job: retrying })).toMatchObject({
      step: 'transcribing',
      retrying: true,
    })
  })

  it('STT 실패: 이유와 재시도 가능 여부', () => {
    const failed = state('transcript', {
      transcription_status: 'FAILED',
      job: job('FAILED', { error_code: 'STT_TIMEOUT', retryable: true }),
    })
    expect(failed).toMatchObject({ step: 'failed', stage: 'transcription', canRetry: true })
    const empty = state('transcript', {
      transcription_status: 'FAILED',
      job: job('FAILED', { error_code: 'EMPTY_TRANSCRIPT', retryable: false }),
    })
    expect(empty.message).toMatch(/말소리를 찾지 못했어요/)
    expect(empty.canRetry).toBe(false)
  })

  it('기기 전사로 대체되어 취소된 예전 작업은 실패가 아님', () => {
    const replaced = job('CANCELLED', { error_code: 'BROWSER_TRANSCRIBED' })
    expect(state('transcript', { transcription_status: 'PENDING', job: replaced }).step).toBe(
      'startTranscription',
    )
  })
})

describe('AI로 정리하기', () => {
  it('대본이 없으면 전사부터 (전사가 끝나야 정리)', () => {
    expect(state('summary', NONE).step).toBe('startTranscription')
    const running = { transcription_status: 'PROCESSING', job: job('RUNNING') }
    expect(state('summary', running, { job: null, feedback_id: null }).step).toBe('transcribing')
  })

  it('대본은 있는데 정리 작업이 없으면 정리 요청 (전사와 함께 요청되지 않은 경우 포함)', () => {
    expect(state('summary', DONE, { job: null, feedback_id: null }).step).toBe('startSummary')
    expect(state('summary', DONE, null).step).toBe('startSummary')
  })

  it('정리 중 → 결과가 생기면 정리 화면으로', () => {
    expect(state('summary', DONE, { job: job('RUNNING'), feedback_id: null }).step).toBe('summarizing')
    expect(state('summary', DONE, { job: job('SUCCEEDED'), feedback_id: 'f1' })).toMatchObject({
      step: 'done',
      feedbackId: 'f1',
    })
  })

  it('AI 정리 실패 후 재시도 / 대본 수정으로 취소된 정리는 다시 요청', () => {
    const failed = state('summary', DONE, {
      job: job('FAILED', { error_code: 'LLM_TIMEOUT', retryable: true }),
      feedback_id: null,
    })
    expect(failed).toMatchObject({ step: 'failed', stage: 'summary', canRetry: true })
    const cancelled = state('summary', DONE, {
      job: job('CANCELLED', { error_code: 'TRANSCRIPT_EDITED' }),
      feedback_id: null,
    })
    expect(cancelled.step).toBe('startSummary')
  })
})

describe('진행 문구', () => {
  it('글로 바꾸는 중 / 정리하는 중', () => {
    expect(processingText({ step: 'transcribing' }, 'transcript').title).toBe('글로 바꾸고 있어요…')
    expect(processingText({ step: 'transcribing' }, 'summary').detail).toMatch(/이어서 아트메이트가/)
    expect(processingText({ step: 'summarizing' }, 'summary').title).toBe('첨삭을 정리하고 있어요…')
  })
})
