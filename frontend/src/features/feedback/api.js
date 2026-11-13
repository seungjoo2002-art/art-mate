import { api } from '../../lib/api'
import { supabase } from '../../lib/supabase'

export const getConsent = () => api('/recording-consents/me')

/** 녹음 동의 철회 → 새 녹음·업로드 불가, 대기 중인 전사 취소 (이미 저장한 녹음은 유지) */
export const revokeConsent = () => api('/recording-consents/me', { method: 'DELETE' })

/** grantedBy: 'SELF' | 'GUARDIAN'(만 14세 미만) */
export const saveConsent = ({ policyVersion, grantedBy }) =>
  api('/recording-consents', {
    method: 'POST',
    body: { policy_version: policyVersion, agreed: true, granted_by: grantedBy },
  })

export const listRecordings = (artworkId) =>
  api(`/artworks/${artworkId}/recordings?include_urls=true`)

export const deleteRecording = (artworkId, recordingId) =>
  api(`/artworks/${artworkId}/recordings/${recordingId}`, { method: 'DELETE' })

export const getRecordingUrl = (artworkId, recordingId) =>
  api(`/artworks/${artworkId}/recordings/${recordingId}/url`)

/** 사진 업로드와 같은 절차: 업로드 요청 → Storage 업로드 → 완료 처리 (v0.5 문서 §2.1) */
export async function uploadRecording(
  artworkId,
  { blob, mimeType, durationMs, recordedAt, fileName, stageId, references = {} },
) {
  const ticket = await api(`/artworks/${artworkId}/recordings`, {
    method: 'POST',
    body: {
      content_type: mimeType,
      file_size: blob.size,
      duration_ms: durationMs,
      recorded_at: recordedAt, // 저장한 시각이 아니라 녹음을 시작한 시각
      ...(fileName ? { file_name: fileName } : {}), // 파일 업로드면 확장자 검증용 (서버에 저장 안 됨)
      ...(stageId ? { stage_id: stageId } : {}), // v0.9.7 단계 피드백 (없으면 작품 전체)
      ...references, // v0.9.8 기준 이미지 (reference_photo_ids, reference_confirmed)
      speaker_notice_confirmed: true, // 녹음 동의 화면에서 '선생님께 알리기'에 동의한 사용자만 녹음 가능
    },
  })

  const { error } = await supabase.storage
    .from(ticket.upload.bucket)
    .uploadToSignedUrl(ticket.upload.path, ticket.upload.token, blob, { contentType: mimeType })
  if (error) throw { userMessage: '녹음을 올리지 못했어요. 다시 시도해 주세요.' }

  return api(`/artworks/${artworkId}/recordings/${ticket.recording.id}/complete`, {
    method: 'POST',
  })
}

/** 작품 단계 (v0.9.7). 피드백을 붙일 단계 선택용 — 숨긴 단계(archived)는 고를 수 없음 */
export const listArtworkStages = (artworkId) => api(`/artworks/${artworkId}/stages`)

/** 녹음을 어느 단계의 피드백으로 볼지 바꿈. stageId null = 작품 전체 피드백 */
export const setRecordingStage = (artworkId, recordingId, stageId) =>
  api(`/artworks/${artworkId}/recordings/${recordingId}`, {
    method: 'PATCH',
    body: { stage_id: stageId },
  })

/** 작품 사진 (피드백 기준 이미지 고르기용, 숨긴 단계 제외, 미리보기 URL 포함) */
export const listArtworkPhotos = (artworkId) =>
  api(`/artworks/${artworkId}/photos?include_urls=true`)
