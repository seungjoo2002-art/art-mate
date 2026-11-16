import { describe, expect, it } from 'vitest'
import { displayTags, repeatedWeaknesses } from './reviewSections'

const feedback = {
  categories: ['PROPORTION'],
  weaknesses: [{ category: 'VALUE' }],
  fixes: [{ category: null }],
}
const stat = (category, artwork_count) => ({ category, label: category, artwork_count })

describe('repeatedWeaknesses', () => {
  it('unknown without growth data', () => {
    expect(repeatedWeaknesses(feedback, null).status).toBe('unknown')
  })

  it('finds weaknesses repeated across artworks', () => {
    const growth = {
      status: 'READY',
      top_weaknesses: [stat('VALUE', 3), stat('PROPORTION', 1), stat('COLOR', 4)],
    }
    expect(repeatedWeaknesses(feedback, growth)).toEqual({
      status: 'found',
      items: [{ category: 'VALUE', label: 'VALUE', artworkCount: 3 }],
    })
  })

  it('insufficient data vs nothing repeated', () => {
    expect(repeatedWeaknesses(feedback, { status: 'INSUFFICIENT_DATA', top_weaknesses: [] }).status).toBe(
      'insufficient',
    )
    expect(repeatedWeaknesses(feedback, { status: 'READY', top_weaknesses: [stat('COLOR', 5)] }).status).toBe(
      'none',
    )
  })
})

describe('displayTags (v0.9.9 첨삭 분류 태그)', () => {
  it('서버 tags를 순서대로, 개선할 점 여부와 함께 쓴다', () => {
    const feedback = {
      categories: ['VALUE'],
      tags: [
        { code: 'COMPOSITION', label: '구도', needs_work: false },
        { code: 'VALUE', label: '명암', needs_work: true },
      ],
    }
    expect(displayTags(feedback)).toEqual([
      { key: 'COMPOSITION', label: '구도', needsWork: false },
      { key: 'VALUE', label: '명암', needsWork: true },
    ])
  })

  it('내용이 부족한 첨삭처럼 태그가 없으면 빈 목록 (약점 카테고리로 채우지 않음)', () => {
    expect(displayTags({ categories: [], tags: [] })).toEqual([])
  })

  it('tags가 없는 이전 응답이면 기존 약점 카테고리로 대신한다', () => {
    const label = (code) => ({ VALUE: '명암' })[code] ?? code
    expect(displayTags({ categories: ['VALUE'] }, label)).toEqual([{ key: 'VALUE', label: '명암', needsWork: true }])
    expect(displayTags(null)).toEqual([])
  })
})
