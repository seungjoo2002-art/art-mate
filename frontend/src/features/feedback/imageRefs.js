// 피드백 기준 이미지 (v0.9.8): 피드백을 받을 때 실제로 본 작품 사진

export const photoTime = (p) => Date.parse(p.uploaded_at ?? p.created_at)

/** 고르지 않았을 때 제안: 고른 단계(없으면 작품 전체)의 가장 최근 사진 */
export function suggestPhoto(photos, stageId) {
  const pool = photos.filter((p) => p.status === 'ACTIVE' && (!stageId || p.stage_id === stageId))
  return [...pool].sort((a, b) => photoTime(b) - photoTime(a))[0]?.id ?? null
}

export const EMPTY_REFS = { photoIds: [], confirmed: false, touched: false }

/**
 * 작품 화면 슬라이드에서 보던 사진을 기본 기준 사진으로 (?photo=). 확인 전이라 '제안'으로 저장되고,
 * 학생이 확인 체크하거나 다른 사진을 고를 수 있다. 없으면 예전처럼 최신 사진 제안
 */
export const presetRefs = (photoId) =>
  photoId ? { photoIds: [photoId], confirmed: false, touched: true, preset: true } : EMPTY_REFS

/** 저장된 기준 이미지 → 고르기 상태 (수정 화면) */
export const refsFromRead = (imageRefs) =>
  imageRefs && (imageRefs.status === 'CONFIRMED' || imageRefs.photos?.length)
    ? {
        photoIds: imageRefs.photos.map((p) => p.photo_id),
        confirmed: imageRefs.status === 'CONFIRMED',
        touched: true,
      }
    : EMPTY_REFS

/** 생성 요청 본문: 직접 고르거나 확인한 경우에만 보냄 (아니면 서버가 최신 사진을 제안으로 연결) */
export const referenceBody = (value) =>
  value.touched
    ? { reference_photo_ids: value.photoIds, reference_confirmed: value.confirmed }
    : {}
