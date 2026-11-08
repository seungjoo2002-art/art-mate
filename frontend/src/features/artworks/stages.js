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
    return { ...stage, photo, uploadedAt: summary?.last_uploaded_at ?? null }
  })
}

export const isCompleted = (artwork) => artwork.progress === 'FINAL'
