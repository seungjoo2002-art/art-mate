import { describe, expect, it } from 'vitest'
import { aiPhase } from './aiStatus'

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
