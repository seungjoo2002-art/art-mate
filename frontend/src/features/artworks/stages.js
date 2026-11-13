// 작품 제작 단계 (v0.9.7): 학생이 개수·이름·순서를 정한다 (기본: 스케치 · 채색 · 완성)
// 서버 응답의 stage_plan을 쓰고, 예전 응답(stage_plan 없음)은 이전 고정 3단계로 보여 준다.

export const DEFAULT_STAGE_NAMES = ['스케치', '채색', '완성']
export const MAX_STAGES = 10 // 서버 제한 (1~10개)
export const MAX_STAGE_NAME = 30 // 서버 제한 (1~30자)

/** 예전 고정 3단계 (stage_plan이 없는 응답용) */
export const STAGES = [
  { key: 'SKETCH', label: '스케치', photoLabel: '스케치 사진' },
  { key: 'PROGRESS', label: '중간 작업', photoLabel: '중간 작업 사진' },
  { key: 'FINAL', label: '완성', photoLabel: '완성 사진' },
]

/**
 * 작품의 단계마다 대표 사진을 붙여서 돌려줌.
 * { key, id(단계 id, 예전 응답이면 null), legacy, label, photoLabel, photo, uploadedAt, targetMinutes }
 */
export function stagesWithPhotos(artwork) {
  const plan = artwork.stage_plan ?? []
  if (!plan.length) {
    return STAGES.map((stage) => {
      const summary = artwork.stages?.find((s) => s.stage === stage.key)
      const photo = artwork.photos.find((p) => p.id === summary?.representative_photo_id) ?? null
      return {
        ...stage,
        id: null,
        legacy: stage.key,
        photo,
        // 타임라인 시각은 이 사진을 올린 시각 (단계의 last_uploaded_at은 추가 사진 시각일 수 있음)
        uploadedAt: photo ? (photo.uploaded_at ?? photo.created_at) : null,
        targetMinutes: null,
      }
    })
  }
  return plan.map((stage) => {
    // v0.9.8: 피드백 뒤에 올린 사진도 같은 단계 사진 (대표 지정 가능)
    const photos = artwork.photos.filter((p) => p.stage_id === stage.id)
    const photo = photos.find((p) => p.is_representative) ?? photos[0] ?? null
    return {
      key: stage.id,
      id: stage.id,
      legacy: stage.legacy_stage,
      label: stage.name,
      photoLabel: `${stage.name} 사진`,
      photo,
      uploadedAt: photo ? (photo.uploaded_at ?? photo.created_at) : null,
      targetMinutes: stage.target_minutes ?? null,
    }
  })
}

/** 사진을 올린 시각 (타임라인 정렬) */
export const photoTime = (photo) => photo.uploaded_at ?? photo.created_at

/**
 * 단계의 사진 전부 (v0.9.8 타임라인): 올린 시각 순. 피드백 뒤에 올린 사진(예전 수정 사진 포함)도
 * 일반 단계 사진과 같게 보여 준다. stageId가 없으면(예전 응답) 작품의 모든 사진
 */
export const stagePhotos = (artwork, stageId) =>
  artwork.photos
    .filter((p) => p.status === 'ACTIVE' && (stageId == null || p.stage_id === stageId))
    .sort((a, b) => Date.parse(photoTime(a)) - Date.parse(photoTime(b)))

let seq = 0
/** 단계 편집 목록의 한 줄. id는 서버 단계 id (새 단계면 없음), key는 화면용 */
export const newStageRow = (name = '', extra = {}) => ({ key: `new-${++seq}`, name, ...extra })

/** 단계 편집 목록 검사. 문제가 없으면 '' */
export function stageListError(stages, { withMinutes = false } = {}) {
  if (!stages.length) return '단계를 1개 이상 만들어 주세요.'
  if (stages.length > MAX_STAGES) return `단계는 ${MAX_STAGES}개까지 만들 수 있어요.`
  if (stages.some((s) => !s.name.trim())) return '단계 이름을 입력해 주세요.'
  if (stages.some((s) => s.name.trim().length > MAX_STAGE_NAME)) {
    return `단계 이름은 ${MAX_STAGE_NAME}자까지 쓸 수 있어요.`
  }
  if (withMinutes && stages.some((s) => !(s.minutes >= 1))) return '단계 목표 시간을 정해 주세요.'
  return ''
}

/** 편집 목록 → API 요청 본문 */
export const toStageSpecs = (stages, { withMinutes = false } = {}) =>
  stages.map((s) => ({
    ...(s.id ? { id: s.id } : {}),
    name: s.name.trim(),
    ...(withMinutes ? { target_minutes: s.minutes } : {}),
  }))

/** 학생이 직접 "작품 완료하기"를 누른 작품 (v0.5.1 work_status). 완성 사진이 있다고 완료는 아님 */
export const isCompleted = (artwork) => artwork.work_status === 'COMPLETED'

/** 마지막 단계 사진이 있음 → 작품 완료 가능 (커뮤니티 공유는 VER.2부터 사진 1장이면 가능) */
export const hasFinalPhoto = (artwork) => artwork.progress === 'FINAL'
