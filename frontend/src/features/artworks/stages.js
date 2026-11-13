export const STAGES = [
  { key: 'SKETCH', label: '스케치', photoLabel: '스케치 사진' },
  { key: 'PROGRESS', label: '중간 작업', photoLabel: '중간 작업 사진' },
  { key: 'FINAL', label: '완성', photoLabel: '완성 사진' },
]

/** 작품의 각 단계에 대표 사진을 붙여서 돌려줌 */
export function stagesWithPhotos(artwork) {
  return STAGES.map((stage) => {
    const summary = artwork.stages.find((s) => s.stage === stage.key)
    const photo = artwork.photos.find((p) => p.id === summary?.representative_photo_id) ?? null
    // 타임라인 시각은 이 사진을 올린 시각 (단계의 last_uploaded_at은 추가 사진 시각일 수 있음)
    return { ...stage, photo, uploadedAt: photo ? (photo.uploaded_at ?? photo.created_at) : null }
  })
}

/** 학생이 직접 "작품 완료하기"를 누른 작품 (v0.5.1 work_status). 완성 사진이 있다고 완료는 아님 */
export const isCompleted = (artwork) => artwork.work_status === 'COMPLETED'

/** 완성 단계 사진이 있음 → 작품 완료·커뮤니티 공유 가능 */
export const hasFinalPhoto = (artwork) => artwork.progress === 'FINAL'
