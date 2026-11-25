// 작품 피드백(녹음·글 첨삭)을 단계·사진별로 나누기 (아카이브 상세 → 단계별 피드백 화면)

/** 오래된 순 (문자열 비교는 시간대 표기가 섞이면 틀리므로 시각으로 비교) */
export const byTime = (a, b) => Date.parse(a.time) - Date.parse(b.time)

/**
 * 피드백이 속한 단계. 숨긴 단계(목록에 없는 단계)·단계 없는 피드백은 null = 작품 전체
 * (예전 타임라인과 같은 기준: 잃어버리지 않게 전체 피드백 쪽에 보여 줌)
 */
export const feedbackStage = (item, stageIds) =>
  item.stageId && stageIds.has(item.stageId) ? item.stageId : null

/**
 * 피드백 기준 사진 → { direct: 지금 있는 기준 사진 id들, replaced: 교체된 기준 사진이 있던 자리(지금 사진) id들 }.
 * 교체 전 사진을 보고 받은 피드백은 새 사진의 피드백이 아니므로 direct에 넣지 않는다
 */
export function linkedPhotos(item) {
  const direct = new Set()
  const replaced = new Set()
  for (const ref of item.imageRefs?.photos ?? []) {
    if (ref.photo_status === 'ACTIVE') direct.add(ref.photo_id)
    else if (ref.replaced && ref.current_photo_id) replaced.add(ref.current_photo_id)
  }
  for (const id of direct) replaced.delete(id)
  return { direct: [...direct], replaced: [...replaced] }
}

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
 * 한 단계의 피드백을 사진별로 (섞이지 않게):
 * - byPhoto: 기준 사진이 지금 이 단계 사진인 피드백 (여러 장이면 각 사진에)
 * - beforeReplace: 그 자리의 사진을 교체하기 전 사진을 보고 받은 피드백 (새 사진 피드백으로 세지 않음)
 * - common: 이 단계 사진과 연결되지 않은 피드백 (사진 없음·삭제된 사진·다른 단계 사진)
 * stageId가 null이면 작품 전체 피드백을 모두 common으로. total = 이 단계 피드백 수 (한 번씩)
 */
export function groupStageFeedback(items, { stageId, stageIds, photoIds }) {
  const mine = items.filter((item) => feedbackStage(item, stageIds) === stageId).sort(byTime)
  const byPhoto = new Map(photoIds.map((id) => [id, []]))
  const beforeReplace = new Map(photoIds.map((id) => [id, []]))
  const common = []
  for (const item of mine) {
    const { direct, replaced } = stageId ? linkedPhotos(item) : { direct: [], replaced: [] }
    const here = direct.filter((id) => byPhoto.has(id))
    const old = replaced.filter((id) => beforeReplace.has(id))
    if (!here.length && !old.length) common.push(item)
    for (const id of here) byPhoto.get(id).push(item)
    for (const id of old) beforeReplace.get(id).push(item)
  }
  return { byPhoto, beforeReplace, common, total: mine.length }
}
