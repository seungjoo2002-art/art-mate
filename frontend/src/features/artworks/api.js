import { api } from '../../lib/api'
import { supabase } from '../../lib/supabase'

/** 목록 필터 (v0.5.1): workCategory MOCK_EXAM | PERSONAL_PRACTICE | CLASS_WORK, practicalType 실기 유형 */
export const listArtworks = ({ limit = 100, offset = 0, workCategory, practicalType } = {}) => {
  const params = new URLSearchParams({ limit, offset })
  if (workCategory) params.set('work_category', workCategory)
  if (practicalType) params.set('practical_type', practicalType)
  return api(`/artworks?${params}`)
}

export const getArtwork = (artworkId) => api(`/artworks/${artworkId}?include_urls=true`)

/**
 * recommendationId: 맞춤 연습 과제의 수행 작품으로 연결 (v0.9)
 * workCategory·timeLimitMinutes: 실기시험 모드면 MOCK_EXAM + 제한 시간(분) (v0.5.1, v0.9 F-2)
 */
export const createArtwork = ({
  title,
  description,
  topic,
  recommendationId,
  practicalType,
  workCategory,
  timeLimitMinutes,
}) =>
  api('/artworks', {
    method: 'POST',
    body: {
      title,
      description: description || null,
      ...(topic ? { topic } : {}), // 주제·소재 (v0.9 F-2)
      ...(recommendationId ? { recommendation_id: recommendationId } : {}),
      ...(practicalType ? { practical_type: practicalType } : {}),
      ...(workCategory ? { work_category: workCategory } : {}),
      ...(timeLimitMinutes ? { time_limit_minutes: timeLimitMinutes } : {}),
    },
  })

export const deleteArtwork = (artworkId) => api(`/artworks/${artworkId}`, { method: 'DELETE' })

export const deletePhoto = (artworkId, photoId) =>
  api(`/artworks/${artworkId}/photos/${photoId}`, { method: 'DELETE' })

/**
 * 작품 정보 수정: 보낸 필드만 바뀜. practical_type·work_category·actual_minutes·time_limit_minutes는
 * null이면 지움. actual_minutes를 직접 넣으면 time_source=MANUAL (v0.9 F-2)
 */
export const updateArtwork = (artworkId, patch) =>
  api(`/artworks/${artworkId}`, { method: 'PATCH', body: patch })

/** 작품 완료 (v0.5.1): 완성 사진이 1장 이상 필요. 완료하면 사진 편집이 막힘 (409 ARTWORK_COMPLETED) */
export const completeArtwork = (artworkId) =>
  api(`/artworks/${artworkId}/complete`, { method: 'POST' })

/** 작업 재개: 다시 사진을 올리거나 바꿀 수 있게 */
export const reopenArtwork = (artworkId) => api(`/artworks/${artworkId}/reopen`, { method: 'POST' })

/** 작품 타이머 (v0.9 F-2): 서버는 이벤트 기록·계산만, 화면이 초를 셈 */
export const getTimer = (artworkId) => api(`/artworks/${artworkId}/timer`)

/** event: START | PAUSE | RESUME | STOP | RESET. STOP하면 actual_minutes 저장 */
export const sendTimerEvent = (artworkId, event) =>
  api(`/artworks/${artworkId}/timer/events`, { method: 'POST', body: { event } })

/** VER.2 실기시험 단계 (서버 저장, 다른 기기에서도 같은 값) */
export const getExam = (artworkId) => api(`/artworks/${artworkId}/exam`)

/** stages: [{ stage: IDEA|SKETCH|COLOR|FINISH, target_minutes }] · 합계가 작품 제한 시간이 됨 */
export const putExamPlan = (artworkId, stages) =>
  api(`/artworks/${artworkId}/exam/plan`, { method: 'PUT', body: { stages } })

/** 현재 단계를 끝내고 다음 단계 시작. 마지막 단계면 409 EXAM_LAST_STAGE (타이머 STOP으로 끝냄) */
export const nextExamStage = (artworkId, currentStage) =>
  api(`/artworks/${artworkId}/exam/next`, { method: 'POST', body: { current_stage: currentStage } })

/** 내 기본 단계 목표 시간 (모든 기기 공통). 저장한 적 없으면 source=DEFAULT */
export const getExamDefaults = () => api('/users/me/exam-defaults')
export const putExamDefaults = (stages) =>
  api('/users/me/exam-defaults', { method: 'PUT', body: { stages } })

export const getPhotoUrl = (artworkId, photoId) =>
  api(`/artworks/${artworkId}/photos/${photoId}/url`)

const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_BYTES = 10 * 1024 * 1024

/** 브라우저 → Storage 직접 업로드 (docs/frontend-integration-v0.4.md §3) */
export async function uploadStagePhoto(artworkId, stage, file, { replacesPhotoId } = {}) {
  if (!ALLOWED_TYPES.includes(file.type)) {
    const isHeic = /heic|heif/i.test(file.type) || /\.hei[cf]$/i.test(file.name)
    throw {
      userMessage: isHeic
        ? '아이폰 HEIC 사진은 올릴 수 없어요. 설정 > 카메라 > 포맷에서 "높은 호환성"으로 바꿔 주세요.'
        : 'JPG, PNG, WEBP 사진만 올릴 수 있어요.',
    }
  }
  if (file.size > MAX_BYTES) throw { userMessage: '10MB 이하 사진만 올릴 수 있어요.' }

  // 1) 업로드 요청 → PENDING 사진 + Signed upload URL
  const ticket = await api(`/artworks/${artworkId}/photos`, {
    method: 'POST',
    body: {
      stage,
      content_type: file.type,
      file_size: file.size,
      file_name: file.name,
      replaces_photo_id: replacesPhotoId ?? null,
    },
  })

  // 2) Storage 업로드
  const { error } = await supabase.storage
    .from(ticket.upload.bucket)
    .uploadToSignedUrl(ticket.upload.path, ticket.upload.token, file, { contentType: file.type })
  if (error) throw { userMessage: '사진을 올리지 못했어요. 다시 시도해 주세요.' }

  // 3) 완료 처리 (멱등)
  return api(`/artworks/${artworkId}/photos/${ticket.photo.id}/complete`, { method: 'POST' })
}
