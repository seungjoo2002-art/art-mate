// v1.3 AI 수정본 화면 계산 (React 없이 테스트할 수 있게 분리)

export const IN_PROGRESS = ['QUEUED', 'RUNNING', 'STORING']

/** 완성 이미지를 볼 수 있는 수정본 */
export const hasImage = (revision) => revision?.status === 'SUCCEEDED' && Boolean(revision.url)

/** 아직 만드는 중 (결과를 기다리며 상태를 다시 확인해야 함) */
export const isPending = (revision) => IN_PROGRESS.includes(revision?.status)

/** 진행 상태 안내 (실제 처리 상태만, 가짜 진행률 없음) */
export function statusText(revision) {
  switch (revision?.status) {
    case 'QUEUED':
      return {
        title: '생성 대기 중이에요.',
        sub: '순서가 되면 바로 시작해요. 다른 화면으로 가도 계속 만들어져요.',
      }
    case 'RUNNING':
      return {
        title: '강사 피드백을 그림에 반영하고 있어요.',
        sub: '현재 작품의 스타일과 작업 단계를 유지하며 수정 예시를 만들고 있어요.',
      }
    case 'STORING':
      return { title: '수정본을 저장하고 있어요.', sub: '잠시만 기다려 주세요.' }
    case 'FAILED':
      return { title: '수정본을 만들지 못했어요.', sub: revisionErrorMessage(revision.error_code) }
    case 'CANCELLED':
      return {
        title: '수정본 만들기가 취소됐어요.',
        sub: revisionErrorMessage(revision.error_code),
      }
    default:
      return null
  }
}

const ERRORS = {
  IMAGE_RESULT_UNKNOWN:
    'AI 응답을 받지 못했어요. 같은 요청이 두 번 처리되지 않도록 자동으로 다시 만들지 않았어요.',
  IMAGE_BLOCKED: 'AI 서비스 정책 때문에 이 사진은 수정 예시를 만들 수 없었어요.',
  IMAGE_RATE_LIMITED: 'AI 서비스가 잠시 붐벼서 만들지 못했어요.',
  IMAGE_UNAVAILABLE: 'AI 서비스가 잠시 불안정해서 만들지 못했어요.',
  IMAGE_INVALID_RESPONSE: 'AI가 보낸 이미지를 읽을 수 없었어요.',
  IMAGE_EMPTY_RESPONSE: 'AI가 이미지를 보내지 않았어요.',
  SOURCE_URL_EXPIRED: '원본 사진을 가져오지 못했어요.',
  SOURCE_TOO_LARGE: '원본 사진이 너무 커요.',
  SOURCE_INVALID: '원본 사진을 읽을 수 없었어요.',
  SOURCE_CHANGED: '원본 사진이 바뀌어서 만들지 않았어요.',
  PHOTO_CHANGED: '원본 사진이 교체·삭제되어 만들지 않았어요.',
  PHOTO_DELETED: '원본 사진이 삭제되었어요.',
  AI_CONSENT_REVOKED: '외부 AI 이미지 처리 동의를 철회해서 취소됐어요.',
  AI_REVISION_DELETED: '수정본을 삭제했어요.',
  RESULT_EXPIRED: '오랫동안 확인하지 않아 결과가 정리됐어요.',
  STORAGE_UNAVAILABLE: '사진 저장소가 잠시 불안정했어요.',
}
const SETUP_CODES = [
  'IMAGE_QUOTA_EXCEEDED',
  'IMAGE_AUTH_FAILED',
  'IMAGE_MODEL_UNAVAILABLE',
  'IMAGE_NOT_CONFIGURED',
  'IMAGE_BAD_REQUEST',
]

export function revisionErrorMessage(code) {
  if (SETUP_CODES.includes(code))
    return '지금은 AI 수정본을 만들 수 없어요. 운영자가 설정을 확인할게요.'
  return ERRORS[code] ?? '잠시 후 다시 시도해 주세요.'
}

/** 개선사항을 카테고리별로 (처음 나온 순서) → [{ label, items }] */
export function groupImprovements(improvements = []) {
  const groups = []
  for (const item of improvements) {
    let group = groups.find((g) => g.category === item.category)
    if (!group) {
      group = { category: item.category, label: item.category_label, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
}

/** 숫자 두 자리 (01, 02 …) */
export const ordinal = (i) => String(i + 1).padStart(2, '0')

/**
 * 원본 사진별 수정본. photos: 지금 단계 사진(슬라이드 순서), revisions: 최신 먼저
 * → Map(photoId → { current: 이 사진의 수정본, previous: 교체 전 사진의 수정본 }) (각각 최신 먼저)
 */
export function revisionsByPhoto(photos, revisions = []) {
  const map = new Map(photos.map((p) => [p.id, { current: [], previous: [] }]))
  for (const revision of revisions) {
    if (map.has(revision.photo_id)) {
      map.get(revision.photo_id).current.push(revision)
      continue
    }
    const now = revision.source_photo?.current_photo_id
    if (revision.source_photo?.replaced && map.has(now)) map.get(now).previous.push(revision)
  }
  return map
}

/** 처음 보여 줄 수정본: 완성된 것 중 최신, 없으면 가장 최근 요청 */
export const defaultRevision = (list = []) => list.find(hasImage) ?? list[0] ?? null

/** 0~100 사이 비교 위치 */
export const clampPercent = (value) => Math.min(100, Math.max(0, value))

/** 포인터 x → 비교 위치(%) */
export const percentAt = (clientX, rect) =>
  rect.width ? clampPercent(((clientX - rect.left) / rect.width) * 100) : 50

/** 한도 안내 문장 (null = 안내 없음) */
export function quotaText(quota) {
  if (!quota) return null
  if (quota.blocked_scope === 'DAILY')
    return `오늘 만들 수 있는 ${quota.daily_limit}개를 모두 만들었어요.`
  if (quota.blocked_scope === 'MONTHLY')
    return `이번 달에 만들 수 있는 ${quota.monthly_limit}개를 모두 만들었어요.`
  if (quota.blocked_scope === 'SERVICE') return '지금은 AI 수정본을 만들 수 있는 양이 모두 찼어요.'
  if (quota.daily_limit) return `오늘 ${quota.daily_used}/${quota.daily_limit}개 만들었어요.`
  return null
}

/** 단계 이름 → 화면 제목 ('스케치 AI 수정본') */
export const pageTitle = (stageLabel) => `${stageLabel} AI 수정본`
