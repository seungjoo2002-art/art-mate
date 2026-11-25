import { api } from '../../lib/api'
import { IMAGE_ERRORS, MAX_IMAGE_BYTES, prepareImageFile } from '../../lib/imageFile'
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
  stages,
  examMaterials,
  paperSize,
  examConditions,
  expressionMethods,
  expressionIntent,
}) =>
  api('/artworks', {
    method: 'POST',
    body: {
      title,
      description: description || null,
      ...(topic ? { topic } : {}), // 주제·소재 (v0.9 F-2)
      ...(examMaterials ? { exam_materials: examMaterials } : {}), // 시험 제시물 (v0.9.8)
      ...(recommendationId ? { recommendation_id: recommendationId } : {}),
      ...(practicalType ? { practical_type: practicalType } : {}),
      ...(workCategory ? { work_category: workCategory } : {}),
      ...(timeLimitMinutes ? { time_limit_minutes: timeLimitMinutes } : {}),
      ...(stages?.length ? { stages } : {}), // v0.9.7 [{ name, target_minutes? }]
      // v1.1 시험 조건·표현 의도 (모두 선택)
      ...(paperSize ? { paper_size: paperSize } : {}),
      ...(examConditions ? { exam_conditions: examConditions } : {}),
      ...(expressionMethods?.length ? { expression_methods: expressionMethods } : {}),
      ...(expressionIntent ? { expression_intent: expressionIntent } : {}),
    },
  })

/** 작품 단계 (v0.9.7): 활성 단계 순서대로, 그 뒤에 숨긴 단계(archived=true) */
export const listStages = (artworkId) => api(`/artworks/${artworkId}/stages`)

/**
 * 단계 목록 전체를 순서대로 보냄 ([{ id?, name, target_minutes? }]). 기존 단계는 id 포함.
 * 빠진 단계에 사진·피드백이 있으면 지우지 않고 숨김 (archived_stage_ids), id를 다시 넣으면 복원
 */
export const replaceStages = (artworkId, stages) =>
  api(`/artworks/${artworkId}/stages`, { method: 'PUT', body: { stages } })

export const deleteArtwork = (artworkId) => api(`/artworks/${artworkId}`, { method: 'DELETE' })

/**
 * 피드백 기준 이미지 저장 (v0.9.8). feedback: { type: 'NOTE' | 'RECORDING', id }
 * photoIds 빈 배열 + confirmed = 사진 없이 받은 피드백이라고 확인
 */
export const saveFeedbackImageRefs = (artworkId, feedback, photoIds, confirmed = true) =>
  api(
    feedback.type === 'NOTE'
      ? `/feedback-notes/${feedback.id}/image-refs`
      : `/artworks/${artworkId}/recordings/${feedback.id}/image-refs`,
    { method: 'PUT', body: { photo_ids: photoIds, confirmed } },
  )

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

/** 작업 다시 시작: 다시 사진을 올리거나 바꿀 수 있게 */
export const reopenArtwork = (artworkId) => api(`/artworks/${artworkId}/reopen`, { method: 'POST' })

/** 작품 타이머 (v0.9 F-2): 서버는 이벤트 기록·계산만, 화면이 초를 셈 */
export const getTimer = (artworkId) => api(`/artworks/${artworkId}/timer`)

/** event: START | PAUSE | RESUME | STOP | RESET. STOP하면 actual_minutes 저장 */
export const sendTimerEvent = (artworkId, event) =>
  api(`/artworks/${artworkId}/timer/events`, {
    method: 'POST',
    body: { event },
  })

/** VER.2 실기시험 단계 (서버 저장, 다른 기기에서도 같은 값) */
export const getExam = (artworkId) => api(`/artworks/${artworkId}/exam`)

/** stages: [{ stage: IDEA|SKETCH|COLOR|FINISH, target_minutes }] · 합계가 작품 제한 시간이 됨 */
export const putExamPlan = (artworkId, stages) =>
  api(`/artworks/${artworkId}/exam/plan`, { method: 'PUT', body: { stages } })

/** 현재 단계를 끝내고 다음 단계 시작. 마지막 단계면 409 EXAM_LAST_STAGE (타이머 STOP으로 끝냄) */
export const nextExamStage = (artworkId, currentStage) =>
  api(`/artworks/${artworkId}/exam/next`, {
    method: 'POST',
    body: { current_stage: currentStage },
  })

/** 내 기본 단계 목표 시간 (모든 기기 공통). 저장한 적 없으면 source=DEFAULT */
export const getExamDefaults = () => api('/users/me/exam-defaults')
export const putExamDefaults = (stages) =>
  api('/users/me/exam-defaults', { method: 'PUT', body: { stages } })

export const getPhotoUrl = (artworkId, photoId) =>
  api(`/artworks/${artworkId}/photos/${photoId}/url`)

// 서버·Storage가 저장하는 형식 (HEIC·HEIF는 prepareImageFile이 JPEG로 바꾼 뒤 올림)
const UPLOAD_TYPES = ['image/jpeg', 'image/png', 'image/webp']

const LEGACY_STAGES = ['SKETCH', 'PROGRESS', 'FINAL']

/**
 * 브라우저 → Storage 직접 업로드 (docs/frontend-integration-v0.4.md §3)
 * stage: 작품 단계 id (v0.9.7) 또는 예전 SKETCH | PROGRESS | FINAL
 * kind REVISION: 피드백을 반영한 수정 사진 → feedbackNoteId 또는 feedbackRecordingId 1개 필수
 */
/**
 * prepareImageFile로 준비한 파일의 형식·크기 확인 (서버가 다시 검증). 문제가 있으면 { userMessage }.
 * 휴대폰에서 고른 원래 파일은 먼저 prepareImageFile(s)로 준비할 것 (HEIC 변환·형식 판별)
 */
export function checkImageFile(file) {
  if (!UPLOAD_TYPES.includes(file.type)) throw { userMessage: IMAGE_ERRORS.UNSUPPORTED }
  if (file.size > MAX_IMAGE_BYTES) throw { userMessage: IMAGE_ERRORS.TOO_LARGE }
}

export async function uploadStagePhoto(
  artworkId,
  stage,
  file,
  { replacesPhotoId, kind = 'STAGE', feedbackNoteId, feedbackRecordingId } = {},
) {
  // 실제 내용으로 형식 판별, HEIC·HEIF는 JPEG로 변환 (MIME이 비었거나 틀려도 됨)
  file = await prepareImageFile(file)

  // 1) 업로드 요청 → PENDING 사진 + Signed upload URL
  const ticket = await api(`/artworks/${artworkId}/photos`, {
    method: 'POST',
    body: {
      ...(LEGACY_STAGES.includes(stage) ? { stage } : { stage_id: stage }),
      kind,
      ...(feedbackNoteId ? { feedback_note_id: feedbackNoteId } : {}),
      ...(feedbackRecordingId ? { feedback_recording_id: feedbackRecordingId } : {}),
      content_type: file.type,
      file_size: file.size,
      file_name: file.name,
      replaces_photo_id: replacesPhotoId ?? null,
    },
  })

  // 2) Storage 업로드
  const { error } = await supabase.storage
    .from(ticket.upload.bucket)
    .uploadToSignedUrl(ticket.upload.path, ticket.upload.token, file, {
      contentType: file.type,
    })
  if (error) throw { userMessage: '사진을 올리지 못했어요. 다시 시도해 주세요.' }

  // 3) 완료 처리 (멱등)
  return api(`/artworks/${artworkId}/photos/${ticket.photo.id}/complete`, {
    method: 'POST',
  })
}

// ---------------------------------------------------------------- v1.1 원본 제시물 사진

/** 업로드된 원본 사진 (순서대로) + 최대 장수. includeUrls면 짧은 만료 미리보기 URL 포함 */
export const listReferencePhotos = (artworkId, { includeUrls = true } = {}) =>
  api(`/artworks/${artworkId}/reference-photos${includeUrls ? '?include_urls=true' : ''}`)

/** 원본 사진 1장 올리기 (요청 → Storage 직접 업로드 → 완료). replacesPhotoId면 그 자리 교체 */
export async function uploadReferencePhoto(artworkId, file, { replacesPhotoId } = {}) {
  file = await prepareImageFile(file)
  checkImageFile(file)
  const ticket = await api(`/artworks/${artworkId}/reference-photos`, {
    method: 'POST',
    body: {
      content_type: file.type,
      file_size: file.size,
      file_name: file.name,
      replaces_photo_id: replacesPhotoId ?? null,
    },
  })
  const { error } = await supabase.storage
    .from(ticket.upload.bucket)
    .uploadToSignedUrl(ticket.upload.path, ticket.upload.token, file, {
      contentType: file.type,
    })
  if (error) throw { userMessage: '사진을 올리지 못했어요. 다시 시도해 주세요.' }
  return api(`/artworks/${artworkId}/reference-photos/${ticket.photo.id}/complete`, {
    method: 'POST',
  })
}

export const deleteReferencePhoto = (artworkId, photoId) =>
  api(`/artworks/${artworkId}/reference-photos/${photoId}`, {
    method: 'DELETE',
  })
