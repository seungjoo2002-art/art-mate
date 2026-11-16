// v1.0 학원·반·강사 화면 API (모두 기존 백엔드 API, docs/frontend-integration-v0.3.md 이후)
import { api } from '../../lib/api'

const qs = (params) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  return entries.length ? `?${new URLSearchParams(entries)}` : ''
}
const A = (academyId) => `/academies/${academyId}`

// --- 학원 ------------------------------------------------------------------
/** 내가 소속된 학원과 내 역할 (승인 대기 학원 포함: 신청자는 OWNER) */
export const listMyAcademies = () => api(`/academies${qs({ mine: true, limit: 50 })}`)
/** 승인된 학원 찾기 (이름 검색) */
export const searchAcademies = (q) => api(`/academies${qs({ q, limit: 20 })}`)
export const getAcademy = (academyId) => api(A(academyId))
export const registerAcademy = ({ name, description }) =>
  api('/academies', { method: 'POST', body: { name, description: description || null } })

// --- 소속 신청 ------------------------------------------------------------
export const requestJoin = (academyId, message) =>
  api(`${A(academyId)}/join-requests`, { method: 'POST', body: { message: message || null } })
export const listMyJoinRequests = () => api(`/users/me/join-requests${qs({ limit: 50 })}`)
export const listJoinRequests = (academyId, status = 'PENDING') =>
  api(`${A(academyId)}/join-requests${qs({ status, limit: 100 })}`)
export const reviewJoinRequest = (academyId, requestId, decision, note) =>
  api(`${A(academyId)}/join-requests/${requestId}`, {
    method: 'PATCH',
    body: { decision, note: note || null },
  })

// --- 멤버 -------------------------------------------------------------------
export const listMembers = (academyId, { role } = {}) =>
  api(`${A(academyId)}/members${qs({ role, limit: 100 })}`)
export const setMemberRole = (academyId, membershipId, role) =>
  api(`${A(academyId)}/members/${membershipId}`, { method: 'PATCH', body: { role } })
export const removeMember = (academyId, membershipId) =>
  api(`${A(academyId)}/members/${membershipId}`, { method: 'DELETE' })

// --- 반 ---------------------------------------------------------------------
/** 강사 이상: 학원 전체 (mine=true: 담당 반), 학생: 배정된 반 */
export const listClasses = (academyId, { mine, status = 'ACTIVE' } = {}) =>
  api(`${A(academyId)}/classes${qs({ mine: mine || undefined, status, limit: 100 })}`)
export const getClass = (academyId, classId) => api(`${A(academyId)}/classes/${classId}`)
export const createClass = (academyId, { name, subject, description }) =>
  api(`${A(academyId)}/classes`, {
    method: 'POST',
    body: { name, subject: subject || null, description: description || null },
  })
export const updateClass = (academyId, classId, patch) =>
  api(`${A(academyId)}/classes/${classId}`, { method: 'PATCH', body: patch })
export const listClassMembers = (academyId, classId) =>
  api(`${A(academyId)}/classes/${classId}/members${qs({ limit: 100 })}`)
/** 학생 배정 / 담당 강사 지정 (멤버의 학원 역할로 정해짐) */
export const addClassMember = (academyId, classId, membershipId) =>
  api(`${A(academyId)}/classes/${classId}/members`, {
    method: 'POST',
    body: { membership_id: membershipId },
  })
export const removeClassMember = (academyId, classId, classMemberId) =>
  api(`${A(academyId)}/classes/${classId}/members/${classMemberId}`, { method: 'DELETE' })

// --- 담당 학생 작품 (강사 이상) ---------------------------------------------
export const listStaffArtworks = (academyId, { studentMembershipId, limit = 50, offset } = {}) =>
  api(
    `${A(academyId)}/artworks${qs({ student_membership_id: studentMembershipId, limit, offset })}`,
  )
export const getStaffArtwork = (academyId, artworkId) =>
  api(`${A(academyId)}/artworks/${artworkId}${qs({ include_urls: true })}`)
export const listStaffRecordings = (academyId, artworkId) =>
  api(`${A(academyId)}/artworks/${artworkId}/recordings`)
export const getStaffRecordingUrl = (academyId, artworkId, recordingId) =>
  api(`${A(academyId)}/artworks/${artworkId}/recordings/${recordingId}/url`)

const R = (academyId, artworkId, recordingId) =>
  `${A(academyId)}/artworks/${artworkId}/recordings/${recordingId}`
export const getStaffTranscription = (academyId, artworkId, recordingId) =>
  api(`${R(academyId, artworkId, recordingId)}/transcription`)
export const requestStaffTranscription = (academyId, artworkId, recordingId) =>
  api(`${R(academyId, artworkId, recordingId)}/transcription`, { method: 'POST' })
export const getStaffTranscript = (academyId, artworkId, recordingId) =>
  api(`${R(academyId, artworkId, recordingId)}/transcript`)
export const getStaffSummary = (academyId, artworkId, recordingId) =>
  api(`${R(academyId, artworkId, recordingId)}/summary`)
export const requestStaffSummary = (academyId, artworkId, recordingId) =>
  api(`${R(academyId, artworkId, recordingId)}/summary`, { method: 'POST' })

// --- 첨삭 검토 (담당 강사) -------------------------------------------------
/** 기본: 검토 대기(DRAFT·IN_REVIEW) 오래된 순. status='APPROVED'로 확정 목록 */
export const listReviewQueue = (academyId, { status, studentMembershipId, limit = 50 } = {}) =>
  api(
    `${A(academyId)}/feedbacks${qs({ status, student_membership_id: studentMembershipId, limit })}`,
  )
export const getStaffFeedback = (academyId, feedbackId) =>
  api(`${A(academyId)}/feedbacks/${feedbackId}`)
export const updateStaffFeedback = (academyId, feedbackId, body) =>
  api(`${A(academyId)}/feedbacks/${feedbackId}`, { method: 'PATCH', body })
export const approveStaffFeedback = (academyId, feedbackId, version, note) =>
  api(`${A(academyId)}/feedbacks/${feedbackId}/approve`, {
    method: 'POST',
    body: { version, note: note || null },
  })
export const rejectStaffFeedback = (academyId, feedbackId, version, reason) =>
  api(`${A(academyId)}/feedbacks/${feedbackId}/reject`, {
    method: 'POST',
    body: { version, reason },
  })
export const reopenStaffFeedback = (academyId, feedbackId, version) =>
  api(`${A(academyId)}/feedbacks/${feedbackId}/reopen`, {
    method: 'POST',
    body: { version, note: null },
  })

// --- 시스템 관리자 (ADMIN) --------------------------------------------------
export const listAcademiesForReview = (status = 'PENDING_APPROVAL') =>
  api(`/admin/academies${qs({ status, limit: 100 })}`)
export const reviewAcademy = (academyId, decision, note) =>
  api(`/admin/academies/${academyId}`, {
    method: 'PATCH',
    body: { decision, note: note || null },
  })
