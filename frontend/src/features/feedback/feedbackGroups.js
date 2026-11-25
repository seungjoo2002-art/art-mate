// 작품 피드백(녹음·글 첨삭)을 단계·사진별로 나누기 (아카이브 상세 → 단계별 피드백 화면)

/** 오래된 순 (문자열 비교는 시간대 표기가 섞이면 틀리므로 시각으로 비교) */
export const byTime = (a, b) => Date.parse(a.time) - Date.parse(b.time)

/**
 * 피드백이 속한 단계. 숨긴 단계(목록에 없는 단계)·단계 없는 피드백은 null = 작품 전체
 * (예전 타임라인과 같은 기준: 잃어버리지 않게 전체 피드백 쪽에 보여 줌)
 */
export const feedbackStage = (item, stageIds) =>
  item.stageId && stageIds.has(item.stageId) ? item.stageId : null

/** 피드백 기준 사진이 지금 가리키는 사진 id들 (교체된 사진은 교체한 사진 자리로) */
export const refPhotoIds = (item) =>
  (item.imageRefs?.photos ?? []).map((p) => p.current_photo_id ?? p.photo_id)

/** 단계별 피드백 개수 (단계 id → 개수, 작품 전체는 null 키) */
export function countByStage(items, stageIds) {
  const counts = new Map()
  for (const item of items) {
    const key = feedbackStage(item, stageIds)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return counts
}

/**
 * 한 단계의 피드백을 사진별로: 기준 사진이 이 단계 사진이면 그 사진 아래 (여러 장이면 각 사진에),
 * 이 단계 사진과 연결되지 않은 피드백(사진 없음·삭제된 사진·다른 단계 사진)은 단계 공통.
 * stageId가 null이면 작품 전체 피드백을 모두 common으로
 * → { byPhoto: Map(photoId → items), common: items, total }
 */
export function groupStageFeedback(items, { stageId, stageIds, photoIds }) {
  const mine = items.filter((item) => feedbackStage(item, stageIds) === stageId).sort(byTime)
  const byPhoto = new Map(photoIds.map((id) => [id, []]))
  const common = []
  for (const item of mine) {
    const linked = stageId ? [...new Set(refPhotoIds(item))].filter((id) => byPhoto.has(id)) : []
    if (!linked.length) common.push(item)
    for (const id of linked) byPhoto.get(id).push(item)
  }
  return { byPhoto, common, total: mine.length }
}
