import { describe, expect, it } from 'vitest'
import {
  compareRows,
  lastActivity,
  mentionBars,
  mistakeRows,
  percent,
  periodCounts,
  tipState,
} from './growthView'

const win = (n, hit) => ({ analyzed_artwork_count: n, artwork_count: hit, ratio: n ? hit / n : null })
const tag = (code, label, weak, strong, extra = {}) => ({
  tag: code,
  label,
  weakness_artwork_count: weak,
  weakness_ratio: weak / 4,
  strength_artwork_count: strong,
  recent: win(2, Math.min(weak, 2)),
  previous: null,
  trend: 'INSUFFICIENT_DATA',
  repeated: weak >= 2,
  ...extra,
})

describe('v1.0 성장 분석 화면 계산', () => {
  const analysis = {
    tags: [
      tag('FORM_PROPORTION', '형태·비례', 3, 0, { previous: win(2, 2), trend: 'SIMILAR' }),
      tag('COMPOSITION', '구도', 0, 2),
      tag('VALUE', '명암', 1, 1),
    ],
    weaknesses: [{ category: 'PROPORTION', label: '비례', artwork_count: 3 }],
    timeline_bucket: 'month',
    timeline: [
      { bucket_start: '2026-10-01', analyzed_artwork_count: 2, feedback_count: 3 },
      { bucket_start: '2026-11-01', analyzed_artwork_count: 1 },
    ],
  }

  it('반복 실수는 9개 태그 기준, 강점만 있는 태그는 빼고', () => {
    const rows = mistakeRows(analysis)
    expect(rows.map((r) => [r.label, r.count, r.repeated])).toEqual([
      ['형태·비례', 3, true],
      ['명암', 1, false],
    ])
  })

  it('tags가 없는 이전 응답은 기존 카테고리로', () => {
    const rows = mistakeRows({ weaknesses: [{ category: 'PROPORTION', label: '비례', artwork_count: 3, repeated: true }] })
    expect(rows).toMatchObject([{ key: 'PROPORTION', label: '비례', count: 3, repeated: true }])
    expect(mistakeRows(null)).toEqual([])
  })

  it('비교는 이전 구간이 있는 항목만', () => {
    expect(compareRows(analysis).map((r) => r.key)).toEqual(['FORM_PROPORTION'])
  })

  it('강점·약점 언급 막대', () => {
    const { rows, max } = mentionBars(analysis)
    expect(max).toBe(3)
    expect(rows.find((r) => r.key === 'COMPOSITION')).toEqual({ key: 'COMPOSITION', label: '구도', weak: 0, strong: 2 })
    expect(mentionBars({}).rows).toEqual([])
  })

  it('기간별 첨삭 횟수 (이전 응답이면 작품 수)', () => {
    expect(periodCounts(analysis)).toEqual([
      { key: '2026-10-01', label: '26.10월', count: 3, artworks: 2 },
      { key: '2026-11-01', label: '26.11월', count: 1, artworks: 1 },
    ])
    expect(periodCounts({ timeline_bucket: 'week', timeline: [{ bucket_start: '2026-11-09', analyzed_artwork_count: 1, feedback_count: 2 }] })[0].label).toBe('11/9주')
  })

  it('최근 활동과 연습 과제 상태', () => {
    expect(lastActivity([{ artwork_id: 'a', title: '정물', work_date: '2026-11-16', feedbacks: [{}, {}] }])).toEqual({
      artworkId: 'a',
      title: '정물',
      workDate: '2026-11-16',
      feedbackCount: 2,
    })
    expect(lastActivity([])).toBeNull()
    expect(tipState({ task: null })).toBe('add')
    expect(tipState({ task: { status: 'ADOPTED' } })).toBe('todo')
    expect(tipState({ task: { status: 'COMPLETED' } })).toBe('done')
    expect(percent(0.4)).toBe('40%')
    expect(percent(null)).toBe('-')
  })
})
