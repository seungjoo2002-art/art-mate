import { describe, expect, it } from 'vitest'
import corrected from '../growth/__fixtures__/transcript-corrected.json'
import { correctionView } from './transcriptView'

// 픽스처는 백엔드 TranscriptRead 스키마로 검증한 실제 응답 형태
describe('STT 원문·AI 보정 비교', () => {
  it('AI 보정본: 바뀐 구간과 STT 원문, 안내 문구', () => {
    const view = correctionView(corrected)
    expect([...view.aiChanged]).toEqual([1, 2])
    expect(view.hasOriginal).toBe(true)
    expect(view.originalText(1)).toBe('오른쪽 사과의 명함이 너무 약해.')
    expect(view.originalText(0)).toBeNull() // 바뀌지 않은 구간은 원문 비교를 띄우지 않음
    expect(view.notice).toMatch(/다시 듣고 확인한 것은 아니에요/)
  })

  it('학생이 AI 보정본을 다시 고친 경우: 원문 비교는 학생 수정까지, AI 표시는 AI가 바꾼 것만', () => {
    const edited = {
      ...corrected,
      origin: 'EDITED',
      stt_original: { ...corrected.stt_original, differs_from_current: [1, 2, 0] },
    }
    const view = correctionView(edited)
    expect([...view.differs].sort()).toEqual([0, 1, 2])
    expect([...view.aiChanged]).toEqual([1, 2])
    expect(view.originalText(0)).toBe('전체적으로 구도는 안정적이야.')
  })

  it('보정 실패·보정 없음: 원문 그대로 (비교 UI 없음)', () => {
    const plain = { ...corrected, origin: 'BROWSER', stt_original: null, ai_correction: null }
    const view = correctionView(plain)
    expect(view.hasOriginal).toBe(false)
    expect(view.aiChanged.size).toBe(0)
    expect(view.notice).toBeNull()
    expect(view.originalText(1)).toBeNull()
  })

  it('이전 서버 응답(필드 없음)도 그대로 동작', () => {
    const { stt_original, ai_correction, ...legacy } = corrected
    expect(stt_original && ai_correction).toBeTruthy()
    expect(correctionView(legacy).hasOriginal).toBe(false)
  })
})
