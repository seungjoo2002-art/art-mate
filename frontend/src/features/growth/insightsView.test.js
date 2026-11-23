import { describe, expect, it } from 'vitest'
import briefingReady from './__fixtures__/briefing-ready.json'
import reportReady from './__fixtures__/report-ready.json'
import {
  aiCommentView,
  briefingNeedsPolling,
  briefingView,
  improvingLine,
  repeatedLine,
  reportIntro,
  trendSteps,
} from './insightsView'

// 픽스처는 백엔드 Pydantic 스키마(Briefing·AnalysisReport)로 검증한 실제 응답 형태
const fmt = (iso) => iso.slice(5).replace('-', '/')
const withStatus = (status, extra = {}) => ({ ...briefingReady, status, ...extra })

describe('홈 브리핑 상태', () => {
  it('정상: 서버 문장을 그대로 쓰고 분석 리포트로 이동', () => {
    const view = briefingView(briefingReady)
    expect(view.title).toBe(briefingReady.headline)
    expect(view.lines).toEqual(briefingReady.lines)
    expect(view.meta).toBe('확정 첨삭 6건 · 작품 6개 기준')
    expect(view.cta.to).toBe('/archive?tab=report')
  })

  it.each([
    ['NO_RECORDS', '아직 기록 없음', '/artworks/new'],
    ['NO_FEEDBACK', '확정한 첨삭 없음', '/archive'],
    ['NEEDS_CONFIRMATION', '확정 대기', '/archive'],
    ['INSUFFICIENT_DATA', '기록 쌓는 중', '/archive?tab=report'],
  ])('%s', (status, meta, to) => {
    const view = briefingView(withStatus(status))
    expect(view.meta).toBe(meta)
    expect(view.cta.to).toBe(to)
  })

  it('정리 중에는 이동 버튼 없이 다시 조회', () => {
    const processing = withStatus('PROCESSING')
    expect(briefingView(processing).cta).toBeNull()
    expect(briefingNeedsPolling(processing)).toBe(true)
    expect(briefingNeedsPolling(briefingReady)).toBe(false)
  })

  it('화면 문장에 점수·백분율을 만들지 않는다', () => {
    const view = briefingView(briefingReady)
    expect([view.title, view.meta, ...view.lines].join(' ')).not.toMatch(/%|점수/)
  })
})

describe('AI 코멘트 상태', () => {
  const ai = briefingReady.ai_comment

  it('READY는 현재 데이터 기준 코멘트', () => {
    expect(aiCommentView({ ...ai, status: 'READY', based_on_current_data: true })).toMatchObject({
      label: 'AI 코멘트',
      text: ai.overview,
      note: null,
    })
  })

  it('STALE은 이전 코멘트임을 알린다', () => {
    const view = aiCommentView(ai)
    expect(view.label).toBe('이전 AI 코멘트')
    expect(view.note).toMatch(/반영되기 전/)
  })

  it('PENDING은 갱신 중 + 이전 내용이 있으면 함께, 다시 조회', () => {
    expect(aiCommentView({ ...ai, status: 'PENDING' })).toMatchObject({ pending: true, text: ai.overview })
    expect(aiCommentView({ ...ai, status: 'PENDING', overview: null }).text).toBeNull()
    expect(briefingNeedsPolling({ ...briefingReady, ai_comment: { ...ai, status: 'PENDING' } })).toBe(true)
  })

  it('실패는 이전 내용이 있을 때만, 꺼짐·없음은 표시 안 함', () => {
    expect(aiCommentView({ ...ai, status: 'FAILED' }).note).toMatch(/새로 정리하지 못해/)
    expect(aiCommentView({ ...ai, status: 'FAILED', overview: null })).toBeNull()
    expect(aiCommentView({ ...ai, status: 'NOT_AVAILABLE', overview: null })).toBeNull()
    expect(aiCommentView({ ...ai, status: 'NONE', overview: null })).toBeNull()
  })
})

describe('분석 리포트', () => {
  it('상태별 안내 (데이터 부족은 서버 안내 문구)', () => {
    expect(reportIntro(reportReady).text).toMatch(/강사 첨삭 6건\(작품 6개\)/)
    const insufficient = { ...reportReady, status: 'INSUFFICIENT_DATA', message: '아직 성장 추세를…' }
    expect(reportIntro(insufficient).text).toBe('아직 성장 추세를…')
    const empty = { ...reportReady, status: 'NO_FEEDBACK', counts: { ...reportReady.counts, artwork_count: 0 } }
    expect(reportIntro(empty).title).toMatch(/작품 하나부터/)
  })

  it('반복 실수는 작품 수와 마지막 지적일', () => {
    expect(repeatedLine(reportReady.repeated_mistakes[0], fmt)).toBe('작품 3개에서 지적 · 마지막 지적 11/15')
  })

  it('개선 추세: 확인됨 / 초기 신호를 구분하고 시간 순서대로', () => {
    const value = reportReady.improving[0]
    expect(improvingLine(value, fmt)).toBe('11/01 지적 이후 작품 2개에서 연속으로 긍정 평가')
    expect(improvingLine({ ...value, improvement_confirmed: false, positive_since_last_issue: 1 }, fmt)).toMatch(
      /더 지켜봐야/,
    )
    expect(trendSteps(value).map((s) => [s.date, s.label])).toEqual([
      ['2026-11-01', '지적'],
      ['2026-11-10', '칭찬'],
      ['2026-11-18', '칭찬'],
    ])
  })
})
