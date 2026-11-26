import { api } from '../../../lib/api'

// v1.3 AI 수정본 API. 조회·비교는 이미지 수정 AI를 부르지 않는다 (생성 요청만 부름)

let featuresCache = null
/** AI 수정본 기능 상태 (GET /meta/ai-features의 ai_revision_status). 실패하면 null */
export function getRevisionFeature() {
  if (!featuresCache) {
    featuresCache = api('/meta/ai-features')
      .then((f) => f?.ai_revision_status ?? 'DISABLED')
      .catch(() => {
        featuresCache = null
        return null
      })
  }
  return featuresCache
}

/** 단계별 수정본 수 { artwork_id, stages: [{ stage_id, count, in_progress }] } */
export const getRevisionSummary = (artworkId) => api(`/artworks/${artworkId}/ai-revisions/summary`)

// 아카이브 상세의 단계마다 버튼이 같은 요약을 쓰므로 잠깐 공유 (요청 1번)
const summaryCache = new Map()
export function getRevisionSummaryShared(artworkId, maxAgeMs = 5000) {
  const hit = summaryCache.get(artworkId)
  if (hit && Date.now() - hit.at < maxAgeMs) return hit.promise
  const promise = getRevisionSummary(artworkId).catch((error) => {
    summaryCache.delete(artworkId)
    throw error
  })
  summaryCache.set(artworkId, { at: Date.now(), promise })
  return promise
}

/** 단계의 수정본 전부 (최신 먼저) + 교체 전 원본 사진 목록 */
export const getStageRevisions = (artworkId, stageId) =>
  api(`/artworks/${artworkId}/stages/${stageId}/ai-revisions`)

/** 사진의 개선사항 후보·한도·동의·최근 수정본 */
export const getRevisionCandidates = (artworkId, photoId) =>
  api(`/artworks/${artworkId}/photos/${photoId}/ai-revision-candidates`)

/** 생성 요청. 같은 요청이면 서버가 기존 수정본을 돌려줌 (200) */
export const createRevision = (artworkId, photoId, selectedKeys) =>
  api(`/artworks/${artworkId}/photos/${photoId}/ai-revisions`, {
    method: 'POST',
    body: { selected_keys: selectedKeys },
  })

export const getRevision = (revisionId) => api(`/ai-revisions/${revisionId}`)
export const retryRevision = (revisionId) =>
  api(`/ai-revisions/${revisionId}/retry`, { method: 'POST' })
export const deleteRevision = (revisionId) =>
  api(`/ai-revisions/${revisionId}`, { method: 'DELETE' })
