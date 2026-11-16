import { describe, expect, it } from 'vitest'
import { summaryLine } from './nextPractice'

describe('summaryLine (한 줄 요약)', () => {
  it('9개 태그 기준: 가장 많이 반복된 개선할 점 + 가장 많이 언급된 잘한 점', () => {
    const analysis = {
      status: 'READY',
      top_tags: ['FORM_PROPORTION'],
      tags: [
        { tag: 'FORM_PROPORTION', label: '형태·비례', strength_artwork_count: 0 },
        { tag: 'COMPOSITION', label: '구도', strength_artwork_count: 3 },
        { tag: 'VALUE', label: '명암', strength_artwork_count: 1 },
      ],
      weaknesses: [],
      top_weaknesses: [],
    }
    expect(summaryLine(analysis)).toBe(
      "최근 첨삭에서 '형태·비례'이(가) 가장 자주 언급됐어요, '구도'은(는) 긍정적으로 언급됐어요.",
    )
  })

  it('tags가 없는 이전 응답은 기존 카테고리', () => {
    const analysis = {
      status: 'READY',
      top_weaknesses: ['VALUE'],
      weaknesses: [{ category: 'VALUE', label: '명암' }],
      strengths: [],
    }
    expect(summaryLine(analysis)).toBe("최근 첨삭에서 '명암'이(가) 가장 자주 언급됐어요.")
  })

  it('데이터 부족·반복 없음', () => {
    expect(summaryLine({ status: 'INSUFFICIENT_DATA' })).toMatch('기록이 쌓이면')
    expect(summaryLine({ status: 'READY', tags: [], top_tags: [] })).toBe('아직 반복해서 언급된 항목이 없어요.')
  })
})
