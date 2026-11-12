import { describe, expect, it } from 'vitest'
import { SERVER_DELAY_MS, recordingCardState } from './aiStatus'

const NOW = Date.parse('2026-11-11T10:00:00Z')
const at = (msAgo) => new Date(NOW - msAgo).toISOString()
const job = (status, extra = {}) => ({
  status,
  attempts: 0,
  error_code: null,
  retryable: true,
  created_at: at(60_000),
  ...extra,
})
const ON = { ai_summary: true, server_transcription: true }
const card = (args) => recordingCardState({ features: ON, now: NOW, ...args })

describe('recordingCardState', () => {
  it('idle before transcription', () => {
    expect(card({ transcription: { transcription_status: 'NOT_REQUESTED', job: null } })).toMatchObject({
      kind: 'idle',
      hasTranscript: false,
    })
  })

  it('device transcription in progress', () => {
    const state = card({
      transcription: { transcription_status: 'NOT_REQUESTED', job: null },
      devicePhase: 'transcribing',
    })
    expect(state.kind).toBe('deviceTranscribing')
  })

  it('server queued vs running, delayed after the threshold', () => {
    const queued = card({ transcription: { transcription_status: 'PENDING', job: job('QUEUED') } })
    expect(queued).toMatchObject({ kind: 'serverQueued', delayed: false })
    const late = card({
      transcription: {
        transcription_status: 'PENDING',
        job: job('QUEUED', { created_at: at(SERVER_DELAY_MS + 1000) }),
      },
    })
    expect(late.delayed).toBe(true)
    const running = card({ transcription: { transcription_status: 'PROCESSING', job: job('RUNNING') } })
    expect(running.kind).toBe('serverRunning')
  })

  it('transcribed shows transcript and AI availability', () => {
    const t = { transcription_status: 'COMPLETED', job: job('SUCCEEDED') }
    expect(card({ transcription: t })).toMatchObject({ kind: 'transcribed', hasTranscript: true, aiAvailable: true })
    const off = recordingCardState({
      transcription: t,
      features: { ai_summary: false, server_transcription: false },
      now: NOW,
    })
    expect(off).toMatchObject({ kind: 'transcribed', aiAvailable: false, serverAvailable: false })
  })

  it('summarizing, ready and failed keep the transcript link', () => {
    const t = { transcription_status: 'COMPLETED', job: job('SUCCEEDED') }
    expect(card({ transcription: t, summary: { job: job('QUEUED') } })).toMatchObject({
      kind: 'summarizing',
      hasTranscript: true,
    })
    expect(
      card({ transcription: t, summary: { feedback_id: 'f1', feedback_status: 'DRAFT', job: job('SUCCEEDED') } }),
    ).toMatchObject({ kind: 'ready', feedbackId: 'f1', hasTranscript: true })
    const failed = card({
      transcription: t,
      summary: { job: job('FAILED', { error_code: 'LLM_RATE_LIMITED' }) },
    })
    expect(failed).toMatchObject({ kind: 'failed', retry: 'summary', hasTranscript: true })
  })

  it('server failure is retryable, browser replacement is not a failure', () => {
    const failed = card({
      transcription: { transcription_status: 'FAILED', job: job('FAILED', { error_code: 'SOURCE_URL_EXPIRED' }) },
    })
    expect(failed).toMatchObject({ kind: 'failed', retry: 'transcription', hasTranscript: false })
    const replaced = card({
      transcription: {
        transcription_status: 'COMPLETED',
        job: job('CANCELLED', { error_code: 'BROWSER_TRANSCRIBED' }),
      },
    })
    expect(replaced.kind).toBe('transcribed')
  })

  it('treats missing feature info as available (older backend)', () => {
    const state = recordingCardState({
      transcription: { transcription_status: 'COMPLETED', job: null },
      features: null,
      now: NOW,
    })
    expect(state.aiAvailable).toBe(true)
  })

  it('device job phases (queued/preparing/saving) count as device transcription', () => {
    for (const devicePhase of ['queued', 'preparing', 'saving']) {
      expect(card({ transcription: { transcription_status: 'PENDING', job: null }, devicePhase }).kind).toBe(
        'deviceTranscribing',
      )
    }
    // 이미 전사가 있으면 기기 작업 상태와 관계없이 대본을 보여 줌
    expect(card({ transcription: { transcription_status: 'COMPLETED' }, devicePhase: 'saving' }).kind).toBe(
      'transcribed',
    )
  })

  it('deferred backup job waits for the device and shows when the server takes over', () => {
    const later = new Date(NOW + 15 * 60_000).toISOString()
    const transcription = {
      transcription_status: 'PENDING',
      job: job('QUEUED', { next_attempt_at: later }),
    }
    expect(card({ transcription })).toMatchObject({ kind: 'serverDeferred', deferredUntil: later })
    // 앞당겨진(지금 처리) 작업은 일반 대기
    const due = { transcription_status: 'PENDING', job: job('QUEUED', { next_attempt_at: at(1000) }) }
    expect(card({ transcription: due }).kind).toBe('serverQueued')
  })

  it('interrupted device transcription offers resume (with or without a backup job)', () => {
    const interrupted = { done: 3, total: 11, crashed: true, device: 'webgpu' }
    const idle = card({ transcription: { transcription_status: 'NONE', job: null }, interrupted })
    expect(idle).toMatchObject({ kind: 'interrupted', interrupted, deferredUntil: null })
    const later = new Date(NOW + 60_000).toISOString()
    const withBackup = card({
      transcription: { transcription_status: 'PENDING', job: job('QUEUED', { next_attempt_at: later }) },
      interrupted,
    })
    expect(withBackup).toMatchObject({ kind: 'interrupted', deferredUntil: later })
    // 서버가 이미 끝냈으면 중단 안내 대신 결과
    const done = card({ transcription: { transcription_status: 'COMPLETED' }, interrupted })
    expect(done.kind).toBe('transcribed')
  })
})
