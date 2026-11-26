import { describe, expect, it } from 'vitest'
import { consentCopy, consentReasonMessage, guardianLink } from './consentCopy'

describe('consentCopy (v0.9.6)', () => {
  it('names the current provider and the cross-border / retention terms', () => {
    const copy = consentCopy('FEEDBACK_SUMMARY', 'OPENAI')
    const text = JSON.stringify(copy)
    expect(copy.agree).toContain('OpenAI')
    expect(text).toContain('국외')
    expect(text).toContain('30일')
    expect(text).toContain('만 14세 미만')
    expect(text).toContain('틀릴 수 있어요')
    expect(text).not.toContain('Gemini')
    expect(consentCopy('GROWTH_COACHING', 'GOOGLE_GEMINI').agree).toContain('Google Gemini')
    expect(consentCopy('FEEDBACK_SUMMARY', undefined).agree).toContain('OpenAI')
  })

  it('v1.3 visual critique consent covers images, purpose, retention and refusal', () => {
    const copy = consentCopy('VISUAL_CRITIQUE', 'GOOGLE_GEMINI')
    const text = JSON.stringify(copy)
    // 요약 제공자와 무관하게 작품 이미지는 OpenAI로만
    expect(copy.agree).toContain('OpenAI')
    expect(text).not.toContain('Gemini')
    expect(text).toContain('작품 사진')
    expect(text).toContain('실력 평가 결과가 아니에요')
    expect(text).toContain('30일')
    expect(text).toContain('ZDR')
    expect(text).toContain('그대로 쓸 수 있어요')
    expect(text).toContain('위치 정보')
  })

  it('explains why consent is not valid yet', () => {
    expect(consentReasonMessage('GUARDIAN_PENDING')).toContain('보호자')
    expect(consentReasonMessage('UNDER_14_BLOCKED')).toContain('만 14세 미만')
    expect(consentReasonMessage('TEEN_NOT_ENABLED')).toContain('준비 중')
    expect(consentReasonMessage('NOT_CONSENTED')).toBeNull()
  })

  it('builds the guardian link from the token', () => {
    // 토큰은 서버로 전송되지 않는 URL 조각(#)에
    expect(guardianLink('abc', 'https://app.example')).toBe(
      'https://app.example/guardian-consent#abc',
    )
  })
})
