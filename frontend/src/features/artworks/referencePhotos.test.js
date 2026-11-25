import { describe, expect, it } from 'vitest'
import { acceptFiles, artworkConditions, latestArtworkPhoto, toggleMethod } from './referencePhotos'

const file = (name, type = 'image/png', size = 1000) => ({ name, type, size })

describe('v1.1 원본 제시물·표현 의도 화면 계산', () => {
  it('남은 장수·형식·크기 안에서만 받는다', () => {
    const { accepted, rejected } = acceptFiles(
      [
        file('a.png'),
        file('b.gif', 'image/gif'),
        file('c.jpg', 'image/jpeg'),
        file('d.webp', 'image/webp'),
        file('e.png', 'image/png', 20 * 1024 * 1024),
      ],
      2,
    )
    expect(accepted.map((f) => f.name)).toEqual(['a.png', 'c.jpg'])
    expect(rejected.map((r) => r.name)).toEqual(['b.gif', 'd.webp', 'e.png'])
    expect(rejected[0].message).toMatch('JPG·JPEG·PNG·WEBP·HEIC·HEIF')
    expect(rejected[1].message).toMatch('최대 장수')
    expect(rejected[2].message).toMatch('10MB')
    // HEIC·HEIF는 고를 때 prepareImageFiles가 JPEG로 바꾼 뒤 여기로 온다 (변환 전 원본은 받지 않음)
    expect(acceptFiles([file('h.heic', 'image/heic')], 5).accepted).toEqual([])
  })

  it('표현 방식 토글은 정의 순서 유지', () => {
    expect(toggleMethod([], 'REARRANGE')).toEqual(['REARRANGE'])
    expect(toggleMethod(['REARRANGE'], 'SCALE')).toEqual(['SCALE', 'REARRANGE'])
    expect(toggleMethod(['SCALE', 'REARRANGE'], 'SCALE')).toEqual(['REARRANGE'])
  })

  it('작품 상세 조건은 값이 있는 것만, 기존 작품(새 필드 없음)도 그대로', () => {
    const rows = artworkConditions(
      {
        topic: '유리컵',
        time_limit_minutes: 240,
        paper_size: '4절',
        expression_methods: ['SCALE', 'ROTATE'],
        expression_intent: '기울여서 역동적으로',
      },
      (c) => ({ SCALE: '확대·축소', ROTATE: '회전·기울이기' })[c],
    )
    expect(rows.map((r) => [r.label, r.value])).toEqual([
      ['실기 주제', '유리컵'],
      ['시험 시간', '240분'],
      ['화지', '4절'],
      ['표현 방식', '확대·축소 · 회전·기울이기'],
      ['표현 의도', '기울여서 역동적으로'],
    ])
    expect(artworkConditions({ title: '예전 작품' })).toEqual([])
  })

  it('비교용 작품 사진: 대표 사진 우선, 없으면 최근', () => {
    const photos = [
      {
        id: 'a',
        status: 'ACTIVE',
        url: 'u1',
        uploaded_at: '2026-11-01T00:00:00Z',
      },
      {
        id: 'b',
        status: 'ACTIVE',
        url: 'u2',
        uploaded_at: '2026-11-03T00:00:00Z',
      },
      {
        id: 'c',
        status: 'PENDING',
        url: null,
        uploaded_at: null,
        created_at: '2026-11-04T00:00:00Z',
      },
    ]
    expect(latestArtworkPhoto({ photos, cover_photo_id: 'a' }).id).toBe('a')
    expect(latestArtworkPhoto({ photos, cover_photo_id: null }).id).toBe('b')
    expect(latestArtworkPhoto({ photos: [] })).toBeNull()
  })
})
