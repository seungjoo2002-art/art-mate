import { api } from '../../lib/api'

// v0.7 성장 코치 + v0.9 F-5/F-7/F-8 (docs/frontend-integration-v0.7.md, v0.9.md). 학생 화면만

export const getGrowthSummary = () => api('/growth/me/summary')
export const getWeaknesses = () => api('/growth/me/weaknesses')

/** 작품별 확정 첨삭 (최신순). feedbacks[].strengths / weaknesses는 문장 배열 */
export const getGrowthTimeline = ({ limit = 50 } = {}) => api(`/growth/me/timeline?limit=${limit}`)

/** period: WEEK | MONTH | ALL. 같은 데이터로 이미 만든 리포트면 기존 것을 돌려줌 */
export const createReport = ({ period, includeAi }) =>
  api('/growth/me/reports', {
    method: 'POST',
    body: { period, scope: 'ALL', include_ai_narrative: includeAi },
  })
export const listReports = () => api('/growth/me/reports?limit=50')
export const getReport = (reportId) => api(`/growth/me/reports/${reportId}`)
export const regenerateReport = (reportId, includeAi) =>
  api(`/growth/me/reports/${reportId}/regenerate`, {
    method: 'POST',
    body: { include_ai_narrative: includeAi },
  })

/** 개인 추천 과제 생성. useAi면 202 + job (폴링) */
export const generateRecommendations = ({ useAi }) =>
  api('/growth/me/recommendations', { method: 'POST', body: { scope: 'PERSONAL', use_ai: useAi } })
export const listRecommendations = () => api('/growth/me/recommendations?scope=PERSONAL&limit=50')
export const getRecommendation = (id) => api(`/growth/me/recommendations/${id}`)

const rec = (id, action) => `/growth/me/recommendations/${id}/${action}`
export const adoptRecommendation = (id, version) =>
  api(rec(id, 'adopt'), { method: 'POST', body: { version } })
export const rejectRecommendation = (id, version, reason) =>
  api(rec(id, 'reject'), { method: 'POST', body: { version, reason } })
export const startRecommendation = (id, version) =>
  api(rec(id, 'start'), { method: 'POST', body: { version } })
export const setRecommendationCompleted = (id, version, completed) =>
  api(rec(id, 'completion'), { method: 'PUT', body: { version, completed } })
export const listLinkedArtworks = (id) => api(rec(id, 'artworks'))
export const unlinkArtwork = (id, artworkId) =>
  api(`${rec(id, 'artworks')}/${artworkId}`, { method: 'DELETE' })
export const getFollowUp = (id) => api(rec(id, 'follow-up'))

export const getGrowthJob = (jobId) => api(`/growth/me/jobs/${jobId}`)

/** v1.0 첨삭의 '다음 작품 연습 과제'(NEXT_TIP)를 내 연습 과제로 담기 (AI 호출 없음, 이미 있으면 그 과제) */
export const createTipTask = (itemId) =>
  api(`/growth/me/practice-tips/${itemId}/task`, { method: 'POST' })

// v1.2 (docs/feedback-archive-v1.2.md §8). 조회만 — 서버가 LLM을 부르지 않고 저장된 분석을 돌려준다
/** 홈 오늘의 브리핑 */
export const getBriefing = () => api('/growth/me/briefing')
/** 아카이브 분석 리포트 (기록 수 + 반복 실수·강점·개선 추세·근거) */
export const getAnalysisReport = () => api('/growth/me/analysis-report')
