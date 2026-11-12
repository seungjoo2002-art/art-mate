import { describe, expect, it } from 'vitest'
import { isSafePath } from './returnPath'

describe('isSafePath (돌아갈 경로)', () => {
  it('allows in-app protected paths', () => {
    expect(isSafePath('/artworks/a1/recordings/new')).toBe(true)
    expect(isSafePath('/feedbacks/f1?tab=items')).toBe(true)
  })

  it('rejects external, protocol-relative and public paths', () => {
    expect(isSafePath('https://evil.example')).toBe(false)
    expect(isSafePath('//evil.example/x')).toBe(false)
    expect(isSafePath('/')).toBe(false)
    expect(isSafePath('/login?next=1')).toBe(false)
    expect(isSafePath(null)).toBe(false)
  })
})
