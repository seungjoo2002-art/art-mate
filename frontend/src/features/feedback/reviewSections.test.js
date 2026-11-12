import { describe, expect, it } from 'vitest'
import { repeatedWeaknesses } from './reviewSections'

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
