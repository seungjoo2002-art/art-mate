import { describe, expect, it } from 'vitest'
import {
  clampPercent,
  defaultRevision,
  groupImprovements,
  hasImage,
  isPending,
  ordinal,
  pageTitle,
  percentAt,
  quotaText,
  revisionErrorMessage,
  revisionsByPhoto,
  statusText,
} from './revisionView'

const rev = (id, photoId, status = 'SUCCEEDED', extra = {}) => ({
  id,
  photo_id: photoId,
  status,
  url: status === 'SUCCEEDED' ? `https://x/${id}` : null,
  source_photo: { photo_id: photoId, replaced: false, current_photo_id: null },
  ...extra,
})

describe('AI 수정본 화면 계산 (v1.3)', () => {
  it('groups revisions per photo and keeps pre-replacement ones separate', () => {
    const photos = [{ id: 'p1' }, { id: 'p2' }, { id: 'p3' }]
    const revisions = [
      rev('r4', 'p1'),
      rev('r3', 'p2', 'RUNNING'),
      // 교체 전 사진 old1(지금 자리는 p1)의 수정본 → p1의 '이전' 이력 (p1 수정본으로 세지 않음)
      rev('r2', 'old1', 'SUCCEEDED', {
        source_photo: { photo_id: 'old1', replaced: true, current_photo_id: 'p1' },
      }),
      rev('r1', 'p1', 'FAILED'),
      // 지금 단계에 없는 사진 (삭제된 자리)은 어디에도 넣지 않음
      rev('r0', 'gone'),
    ]
    const map = revisionsByPhoto(photos, revisions)
    expect(map.get('p1').current.map((r) => r.id)).toEqual(['r4', 'r1'])
    expect(map.get('p1').previous.map((r) => r.id)).toEqual(['r2'])
    expect(map.get('p2').current.map((r) => r.id)).toEqual(['r3'])
    // 수정본이 없는 사진도 목록에 그대로 (슬라이드에서 빼지 않음)
    expect(map.get('p3')).toEqual({ current: [], previous: [] })
  })

  it('shows the newest finished revision first, else the latest request', () => {
    expect(defaultRevision([rev('a', 'p', 'RUNNING'), rev('b', 'p')]).id).toBe('b')
    expect(defaultRevision([rev('a', 'p', 'FAILED')]).id).toBe('a')
    expect(defaultRevision([])).toBeNull()
  })

  it('reports real states only (no fake progress)', () => {
    expect(isPending(rev('a', 'p', 'QUEUED'))).toBe(true)
    expect(isPending(rev('a', 'p', 'STORING'))).toBe(true)
    expect(isPending(rev('a', 'p'))).toBe(false)
    expect(hasImage(rev('a', 'p'))).toBe(true)
    expect(hasImage({ status: 'SUCCEEDED', url: null })).toBe(false)
    expect(statusText(rev('a', 'p', 'RUNNING')).title).toBe('강사 피드백을 그림에 반영하고 있어요.')
    expect(statusText(rev('a', 'p', 'RUNNING')).sub).toContain('스타일과 작업 단계를 유지하며')
    expect(statusText(rev('a', 'p', 'QUEUED')).title).toContain('대기')
    expect(statusText(rev('a', 'p'))).toBeNull()
    const failed = statusText({ status: 'FAILED', error_code: 'IMAGE_RESULT_UNKNOWN' })
    expect(failed.sub).toContain('자동으로 다시 만들지 않았어요')
    expect(revisionErrorMessage('IMAGE_AUTH_FAILED')).toContain('운영자')
    expect(revisionErrorMessage('???')).toContain('다시 시도')
  })

  it('groups requested improvements by category in order', () => {
    const groups = groupImprovements([
      { key: '1', category: 'FORM', category_label: '형태', kind_label: '부족한 점', text: 'a' },
      { key: '2', category: 'VALUE', category_label: '명암', kind_label: '부족한 점', text: 'b' },
      { key: '3', category: 'FORM', category_label: '형태', kind_label: '수정 방법', text: 'c' },
    ])
    expect(groups.map((g) => [g.label, g.items.map((i) => i.key)])).toEqual([
      ['형태', ['1', '3']],
      ['명암', ['2']],
    ])
    expect(ordinal(0)).toBe('01')
    expect(ordinal(11)).toBe('12')
  })

  it('maps pointer position to the compare split and clamps it', () => {
    const rect = { left: 100, width: 200 }
    expect(percentAt(200, rect)).toBe(50)
    expect(percentAt(50, rect)).toBe(0)
    expect(percentAt(400, rect)).toBe(100)
    expect(percentAt(10, { left: 0, width: 0 })).toBe(50)
    expect(clampPercent(-5)).toBe(0)
    expect(clampPercent(105)).toBe(100)
  })

  it('explains limits and titles the page by stage', () => {
    expect(quotaText({ blocked_scope: 'DAILY', daily_limit: 3 })).toContain('오늘')
    expect(quotaText({ blocked_scope: 'MONTHLY', monthly_limit: 20 })).toContain('20개')
    expect(quotaText({ blocked_scope: 'SERVICE' })).toContain('찼어요')
    expect(quotaText({ blocked_scope: null, daily_limit: 3, daily_used: 1 })).toBe(
      '오늘 1/3개 만들었어요.',
    )
    expect(quotaText({ blocked_scope: null, daily_limit: 0 })).toBeNull()
    expect(pageTitle('스케치')).toBe('스케치 AI 수정본')
    expect(pageTitle('중간 작업')).toBe('중간 작업 AI 수정본')
  })
})
