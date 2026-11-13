import { describe, expect, it } from 'vitest'
import { EMPTY_REFS, referenceBody, refsFromRead, suggestPhoto } from './imageRefs'

const p = (id, extra) => ({ id, status: 'ACTIVE', uploaded_at: '2026-11-13T01:00:00Z', ...extra })

describe('feedback reference images', () => {
  const photos = [
    p('a', { stage_id: 's1', uploaded_at: '2026-11-13T01:00:00Z' }),
    p('b', { stage_id: 's1', uploaded_at: '2026-11-13T03:00:00Z' }),
    p('c', { stage_id: 's2', uploaded_at: '2026-11-13T04:00:00Z' }),
    p('d', { stage_id: 's1', uploaded_at: '2026-11-13T05:00:00Z', status: 'DELETED' }),
  ]

  it('suggests the latest active photo of the stage, or of the artwork', () => {
    expect(suggestPhoto(photos, 's1')).toBe('b')
    expect(suggestPhoto(photos, '')).toBe('c')
    expect(suggestPhoto([], 's1')).toBeNull()
  })

  it('sends references only when the user picked or confirmed', () => {
    expect(referenceBody(EMPTY_REFS)).toEqual({})
    expect(referenceBody({ photoIds: ['a', 'c'], confirmed: true, touched: true })).toEqual({
      reference_photo_ids: ['a', 'c'],
      reference_confirmed: true,
    })
    expect(referenceBody({ photoIds: [], confirmed: true, touched: true })).toEqual({
      reference_photo_ids: [],
      reference_confirmed: true,
    })
  })

  it('restores the saved link on the edit screen', () => {
    expect(
      refsFromRead({ status: 'SUGGESTED', photos: [{ photo_id: 'a' }] }),
    ).toEqual({ photoIds: ['a'], confirmed: false, touched: true })
    expect(refsFromRead({ status: 'CONFIRMED', photos: [] })).toEqual({
      photoIds: [],
      confirmed: true,
      touched: true,
    })
    expect(refsFromRead({ status: 'NONE', photos: [] })).toEqual(EMPTY_REFS)
    expect(refsFromRead(undefined)).toEqual(EMPTY_REFS)
  })
})
