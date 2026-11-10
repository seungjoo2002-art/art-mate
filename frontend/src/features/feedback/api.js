import { api } from '../../lib/api'
import { supabase } from '../../lib/supabase'

export const getConsent = () => api('/recording-consents/me')

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
  { blob, mimeType, durationMs, recordedAt, fileName },
) {
  const ticket = await api(`/artworks/${artworkId}/recordings`, {
    method: 'POST',
    body: {
      content_type: mimeType,
      file_size: blob.size,
      duration_ms: durationMs,
      recorded_at: recordedAt, // 저장한 시각이 아니라 녹음을 시작한 시각
      ...(fileName ? { file_name: fileName } : {}), // 파일 업로드면 확장자 검증용 (서버에 저장 안 됨)
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
