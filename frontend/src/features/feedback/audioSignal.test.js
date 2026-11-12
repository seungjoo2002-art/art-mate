import { describe, expect, it } from 'vitest'
import { playbackMessage } from './audioFile'
import { judgeSignal, signalStats } from './audioSignal'
import { recordingTypes } from './useAudioRecorder'
import { cer, termAccuracy } from './stt/sttMetrics'
import { dropHallucinations } from './stt/models'

const RATE = 16_000
function tone(sec, amp, { speechSec = sec } = {}) {
  const out = new Float32Array(Math.round(sec * RATE))
  for (let i = 0; i < Math.round(speechSec * RATE); i += 1) out[i] = amp * Math.sin(i / 5)
  return out
}

describe('signalStats / judgeSignal', () => {
  it('flags digital silence and near-silence', () => {
    expect(judgeSignal(signalStats(new Float32Array(RATE * 3), RATE))).toBe('silent')
    expect(judgeSignal(signalStats(tone(3, 0.004), RATE))).toBe('silent') // 피크 0.004
  })

  it('flags quiet or mostly empty recordings', () => {
    expect(judgeSignal(signalStats(tone(10, 0.03), RATE))).toBe('quiet')
    // 10초 중 0.5초만 소리 → 5%
    expect(judgeSignal(signalStats(tone(10, 0.5, { speechSec: 0.5 }), RATE))).toBe('quiet')
  })

  it('accepts normal speech levels and unknown stats', () => {
    const stats = signalStats(tone(5, 0.4), RATE)
    expect(stats.speechRatio).toBe(1)
    expect(stats.peak).toBeCloseTo(0.4, 2)
    expect(judgeSignal(stats)).toBe('ok')
    expect(judgeSignal(null)).toBe('ok') // 검사 못 함(긴 파일 등) → 경고 안 함
    expect(judgeSignal({ peak: 0.6, speechRatio: 0.4 })).toBe('ok') // 녹음 중 실시간 통계
  })
})

describe('recordingTypes', () => {
  it('prefers mp4 (AAC) on Safari and webm elsewhere', () => {
    const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_4 like Mac OS X) AppleWebKit/605.1.15 Version/18.4 Mobile/15E148 Safari/604.1'
    const chrome = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/157.0 Safari/537.36'
    const iosChrome = 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 CriOS/157.0 Mobile Safari/604.1'
    expect(recordingTypes(iphone)[0]).toBe('audio/mp4')
    expect(recordingTypes(chrome)[0]).toBe('audio/webm;codecs=opus')
    expect(recordingTypes(iosChrome)[0]).toBe('audio/webm;codecs=opus')
  })
})

describe('playbackMessage', () => {
  it('explains each media error', () => {
    expect(playbackMessage(4, 'audio/webm')).toContain('audio/webm')
    expect(playbackMessage(3)).toContain('손상')
    expect(playbackMessage(2)).toContain('인터넷')
  })
})

describe('dropHallucinations', () => {
  it('drops typical Whisper subtitle hallucinations only', () => {
    const segs = [
      { start_ms: 0, end_ms: 1, text: '명암을 더 눌러 줘.' },
      { start_ms: 1, end_ms: 2, text: '시청해 주셔서 감사합니다.' },
      { start_ms: 2, end_ms: 3, text: 'MBC 뉴스 김철수입니다.' },
      { start_ms: 3, end_ms: 4, text: '구독과 좋아요 부탁드립니다' },
      { start_ms: 4, end_ms: 5, text: '배경은 감사합니다 하고 넘어가지 말고 정리해.' },
    ]
    expect(dropHallucinations(segs).map((s) => s.text)).toEqual([
      '명암을 더 눌러 줘.',
      '배경은 감사합니다 하고 넘어가지 말고 정리해.',
    ])
  })
})

describe('sttMetrics', () => {
  it('computes CER ignoring spaces and punctuation', () => {
    expect(cer('명암을 더 줘.', '명암을더줘')).toBe(0)
    expect(cer('명암을 더 줘', '명함을 더 줘')).toBeCloseTo(1 / 5)
    expect(cer('', 'x')).toBeNull()
  })

  it('measures art term recall by occurrence', () => {
    const ref = '명암 대비가 약해. 명암을 다시 잡고 소실점을 맞춰.'
    const hyp = '명함 대비가 약해. 명암을 다시 잡고 소실점을 맞춰.'
    expect(termAccuracy(ref, hyp)).toEqual({ total: 4, matched: 3, ratio: 0.75, missed: ['명암'] })
    expect(termAccuracy('안녕', '안녕').ratio).toBeNull()
  })
})
