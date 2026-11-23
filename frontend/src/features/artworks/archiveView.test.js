import { describe, expect, it } from 'vitest'
import { archiveItems, archiveKind, archiveQuery, artworkCardView } from './archiveView'

const art = (id, extra = {}) => ({
  id,
  title: `작품 ${id}`,
  work_category: null,
  practical_type: 'BASIC_DESIGN',
  work_status: 'IN_PROGRESS',
  cover_photo_id: null,
  ...extra,
})

const items = [
  art('free'), // 자유 기록 (work_category 없음)
  art('exam', { work_category: 'MOCK_EXAM' }),
  art('personal', { work_category: 'PERSONAL_PRACTICE' }),
  art('class', { work_category: 'CLASS_WORK' }),
]

describe('아카이브 분류', () => {
  it('알 수 없는 값은 전체', () => {
    expect(archiveKind('exam')).toBe('exam')
    expect(archiveKind('BASIC_DESIGN')).toBe('') // 예전 실기 유형 주소(?type=)는 분류로 쓰지 않음
    expect(archiveKind(null)).toBe('')
  })

  it('실기시험은 서버 필터 MOCK_EXAM', () => {
    expect(archiveQuery('exam')).toEqual({ workCategory: 'MOCK_EXAM' })
    expect(archiveItems('exam', [items[1]]).map((a) => a.id)).toEqual(['exam'])
  })

  it('내 작품 기록 = 실기시험이 아닌 작품 (자유·개인 연습·수업)', () => {
    expect(archiveQuery('record')).toEqual({})
    expect(archiveItems('record', items).map((a) => a.id)).toEqual(['free', 'personal', 'class'])
  })

  it('실기 모의고사는 구분 필드가 없어 요청·분류하지 않음', () => {
    expect(archiveQuery('mock')).toBeNull()
  })

  it('전체는 그대로', () => {
    expect(archiveQuery('')).toEqual({})
    expect(archiveItems('', items)).toHaveLength(4)
  })
})

describe('작품 카드 문구', () => {
  it('진행 중 · 사진 없음', () => {
    expect(artworkCardView(art('a'))).toMatchObject({
      status: '그리는 중',
      done: false,
      hasPhoto: false,
      exam: false,
      emptyHint: '그리면서 사진을 남겨 보세요',
    })
  })

  it('완성 · 사진 없음 · 실기시험', () => {
    const view = artworkCardView(art('b', { work_status: 'COMPLETED', work_category: 'MOCK_EXAM' }))
    expect(view).toMatchObject({ status: '완성', done: true, exam: true })
    expect(view.emptyHint).toBe('작품 사진을 등록해 주세요')
  })

  it('사진 있음', () => {
    expect(artworkCardView(art('c', { cover_photo_id: 'p1' })).hasPhoto).toBe(true)
  })
})
