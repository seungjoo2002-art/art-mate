import { api } from '../../lib/api'
import { supabase } from '../../lib/supabase'

/** workCategory: MOCK_EXAM | PERSONAL_PRACTICE | CLASS_WORK (v0.5.1 목록 필터) */
export const listArtworks = ({ limit = 100, offset = 0, workCategory } = {}) =>
  api(
    `/artworks?limit=${limit}&offset=${offset}${workCategory ? `&work_category=${workCategory}` : ''}`,
  )

export const getArtwork = (artworkId) => api(`/artworks/${artworkId}?include_urls=true`)

/**
 * recommendationId: 맞춤 연습 과제의 수행 작품으로 연결 (v0.9)
 * workCategory·timeLimitMinutes: 실기시험 모드면 MOCK_EXAM + 제한 시간(분) (v0.5.1, v0.9 F-2)
 */
export const createArtwork = ({
  title,
  description,
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
      ...(recommendationId ? { recommendation_id: recommendationId } : {}),
      ...(practicalType ? { practical_type: practicalType } : {}),
      ...(workCategory ? { work_category: workCategory } : {}),
      ...(timeLimitMinutes ? { time_limit_minutes: timeLimitMinutes } : {}),
    },
  })

export const deleteArtwork = (artworkId) => api(`/artworks/${artworkId}`, { method: 'DELETE' })

export const deletePhoto = (artworkId, photoId) =>
  api(`/artworks/${artworkId}/photos/${photoId}`, { method: 'DELETE' })

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
