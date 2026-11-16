import { describe, expect, it } from 'vitest'
import { aiPhase, noteSummaryState } from './aiStatus'

const job = (status, extra = {}) => ({ status, attempts: 1, error_code: null, retryable: true, ...extra })

describe('aiPhase', () => {
  it('treats a server job replaced by a browser transcript as done, not failed', () => {
    const transcription = {
      transcription_status: 'COMPLETED',
      job: job('CANCELLED', { error_code: 'BROWSER_TRANSCRIBED' }),
    }
    expect(aiPhase(transcription, null)).toEqual({ phase: 'needsSummary' })
    expect(aiPhase(transcription, { job: job('QUEUED', { attempts: 0 }) }).phase).toBe('summarizing')
  })

  it('keeps server failures retryable', () => {
    const transcription = { transcription_status: 'FAILED', job: job('FAILED', { error_code: 'SOURCE_URL_EXPIRED' }) }
    expect(aiPhase(transcription, null)).toMatchObject({ phase: 'failed', retry: 'transcription' })
    const cancelled = { transcription_status: 'FAILED', job: job('CANCELLED', { error_code: 'RECORDING_CONSENT_REVOKED' }) }
    expect(aiPhase(cancelled, null).phase).toBe('failed')
  })

  it('shows server transcription in progress and the idle state', () => {
    expect(aiPhase({ job: job('QUEUED', { attempts: 0 }) }, null).phase).toBe('transcribing')
    expect(aiPhase({ transcription_status: 'NOT_REQUESTED', job: null }, null).phase).toBe('idle')
  })
})

describe('noteSummaryState (텍스트 첨삭 AI 요약, 무한 로딩 방지)', () => {
  const now = Date.parse('2026-11-16T13:50:00Z')
  const sjob = (status, extra = {}) => ({
    status,
    attempts: 0,
    error_code: null,
    retryable: true,
    next_attempt_at: null,
    created_at: '2026-11-16T13:45:53Z',
    ...extra,
  })
  const note = (summary_job, extra = {}) => ({ feedback_id: null, summary_job, ...extra })

  it('요청 전이면 idle, 결과가 있으면 ready (폴링 없음)', () => {
    expect(noteSummaryState(note(null), now)).toEqual({ kind: 'idle', pollMs: null })
    expect(noteSummaryState(note(sjob('SUCCEEDED'), { feedback_id: 'f1' }), now).kind).toBe('ready')
  })

  it('첫 시도 대기·진행 중이면 working + 5초 폴링', () => {
    expect(noteSummaryState(note(sjob('QUEUED')), now)).toEqual({ kind: 'working', pollMs: 5_000 })
    expect(noteSummaryState(note(sjob('RUNNING')), now).kind).toBe('working')
  })

  it('OpenAI 429 뒤 자동 재시도 대기는 이유와 다음 시도 시각을 보여 준다 (스피너 아님)', () => {
    const state = noteSummaryState(
      note(sjob('QUEUED', { attempts: 1, error_code: 'LLM_RATE_LIMITED', next_attempt_at: '2026-11-16T13:51:00Z' })),
      now,
    )
    expect(state.kind).toBe('retrying')
    expect(state.reason).toMatch('요청이 몰려')
    expect(state.retryAt).toBe('2026-11-16T13:51:00Z')
    expect(state.pollMs).toBe(15_000)
    // 다음 시도 시각이 지났으면 시각은 숨김
    const due = noteSummaryState(
      note(sjob('QUEUED', { attempts: 2, error_code: 'LLM_RATE_LIMITED', next_attempt_at: '2026-11-16T13:49:00Z' })),
      now,
    )
    expect(due.retryAt).toBeNull()
  })

  it('10분 넘게 끝나지 않으면 stalled로 바꾸고 천천히(30초) 확인', () => {
    const old = sjob('QUEUED', { attempts: 2, error_code: 'LLM_RATE_LIMITED', created_at: '2026-11-16T13:30:00Z' })
    expect(noteSummaryState(note(old), now)).toEqual({ kind: 'stalled', pollMs: 30_000 })
  })

  it('최종 실패는 이유를 보여 주고, 재시도해도 소용없는 실패는 다시 시도 버튼을 숨긴다 (중복 과금 방지)', () => {
    const quota = noteSummaryState(note(sjob('FAILED', { attempts: 1, error_code: 'LLM_QUOTA_EXCEEDED', retryable: false })), now)
    expect(quota).toMatchObject({ kind: 'failed', canRetry: false, pollMs: null })
    expect(quota.message).toMatch('운영자')
    const rate = noteSummaryState(note(sjob('FAILED', { attempts: 3, error_code: 'LLM_RATE_LIMITED' })), now)
    expect(rate).toMatchObject({ kind: 'failed', canRetry: true, message: '잠시 후 다시 시도해 주세요.' })
  })
})
