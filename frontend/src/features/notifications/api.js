import { api } from '../../lib/api'

// v0.9 F-9 앱 내부 알림 (docs/frontend-integration-v0.9.md §9). 푸시·이메일 없음, 목록 조회 때 서버가 다시 계산

/** 응답에 unread_count 포함 */
export const listNotifications = ({ limit = 30 } = {}) => api(`/notifications?limit=${limit}`)

export const markRead = (id) => api(`/notifications/${id}/read`, { method: 'POST' })

export const markAllRead = () => api('/notifications/read-all', { method: 'POST' })

export const deleteNotification = (id) => api(`/notifications/${id}`, { method: 'DELETE' })

/** 알림 종류별 이동할 화면 */
export function notificationLink(n) {
  if (n.type === 'REPORT_READY' && n.report_id) return `/growth/reports/${n.report_id}`
  if (n.recommendation_id) return `/growth/recommendations/${n.recommendation_id}`
  if (n.type === 'GOAL_CHECK') return '/my/edit'
  return null
}
