import { describe, expect, it } from 'vitest'
import { countByStage, feedbackStage, groupStageFeedback, linkedPhotos } from './feedbackGroups'

const ref = (photo_id, extra = {}) => ({ photo_id, photo_status: 'ACTIVE', ...extra })
const item = (key, stageId, refs = [], time = '2026-11-20T10:00:00Z') => ({
  key,
  stageId,
  time,
  imageRefs: { status: 'CONFIRMED', photos: refs },
})
const stageIds = new Set(['s1', 's2'])

describe('feedbackStage', () => {
  it('숨긴 단계·단계 없는 피드백은 작품 전체', () => {
    expect(feedbackStage(item('a', 's1'), stageIds)).toBe('s1')
    expect(feedbackStage(item('b', 'gone'), stageIds)).toBeNull()
    expect(feedbackStage(item('c', null), stageIds)).toBeNull()
  })
})

describe('linkedPhotos', () => {
  it('교체된 기준 사진은 지금 사진이 아니라 "교체 전" 자리로', () => {
    const it1 = item('a', 's1', [
      ref('old', { photo_status: 'DELETED', replaced: true, current_photo_id: 'new' }),
      ref('p2'),
      ref('gone', { photo_status: 'DELETED', replaced: false, current_photo_id: null }),
    ])
    expect(linkedPhotos(it1)).toEqual({ direct: ['p2'], replaced: ['new'] })
  })
  it('교체 전·후 사진을 둘 다 고른 피드백은 지금 사진 피드백', () => {
    const it1 = item('a', 's1', [
      ref('old', { photo_status: 'DELETED', replaced: true, current_photo_id: 'new' }),
      ref('new'),
    ])
    expect(linkedPhotos(it1)).toEqual({ direct: ['new'], replaced: [] })
  })
  it('기준 사진이 없으면 빈 목록', () => {
    expect(linkedPhotos({ imageRefs: null })).toEqual({ direct: [], replaced: [] })
  })
})

describe('countByStage', () => {
  it('단계마다, 작품 전체는 null', () => {
    const counts = countByStage(
      [item('a', 's1'), item('b', 's1'), item('c', 's2'), item('d', null), item('e', 'gone')],
      stageIds,
    )
    expect(counts.get('s1')).toBe(2)
    expect(counts.get('s2')).toBe(1)
    expect(counts.get(null)).toBe(2)
  })
})

describe('groupStageFeedback', () => {
  const items = [
    item('late', 's1', [ref('p1')], '2026-11-20T12:00:00Z'),
    item('early', 's1', [ref('p1')], '2026-11-20T09:00:00Z'),
    item('both', 's1', [ref('p1'), ref('p2')]),
    item('none', 's1'),
    item('deleted', 's1', [ref('x', { photo_status: 'DELETED', current_photo_id: null })]),
    item('otherStagePhoto', 's1', [ref('q1')]),
    item('replaced', 's1', [
      ref('old', { photo_status: 'DELETED', current_photo_id: 'p2', replaced: true }),
    ]),
    item('replacedGone', 's1', [
      ref('old2', { photo_status: 'DELETED', current_photo_id: null, replaced: true }),
    ]),
    item('s2', 's2', [ref('p1')]),
    item('overall', null, [ref('p1')]),
  ]

  it('사진별로 나누고 섞지 않음, 연결 안 된 건 단계 공통', () => {
    const { byPhoto, beforeReplace, common, total } = groupStageFeedback(items, {
      stageId: 's1',
      stageIds,
      photoIds: ['p1', 'p2'],
    })
    expect(byPhoto.get('p1').map((i) => i.key)).toEqual(['early', 'both', 'late'])
    // 교체 전 사진 피드백은 새 사진(p2) 피드백으로 세지 않고 따로
    expect(byPhoto.get('p2').map((i) => i.key)).toEqual(['both'])
    expect(beforeReplace.get('p2').map((i) => i.key)).toEqual(['replaced'])
    expect(beforeReplace.get('p1')).toEqual([])
    // 교체한 사진까지 지워진 자리는 단계 공통 (누락 없음)
    expect(common.map((i) => i.key).sort()).toEqual([
      'deleted',
      'none',
      'otherStagePhoto',
      'replacedGone',
    ])
    expect(total).toBe(8)
  })

  it('사진이 없는 단계: 모두 단계 공통', () => {
    const { byPhoto, common } = groupStageFeedback(items, {
      stageId: 's2',
      stageIds,
      photoIds: [],
    })
    expect(byPhoto.size).toBe(0)
    expect(common.map((i) => i.key)).toEqual(['s2'])
  })

  it('작품 전체: 사진과 상관없이 모두 한 목록', () => {
    const { common, total } = groupStageFeedback(items, {
      stageId: null,
      stageIds,
      photoIds: [],
    })
    expect(common.map((i) => i.key)).toEqual(['overall'])
    expect(total).toBe(1)
  })
})
