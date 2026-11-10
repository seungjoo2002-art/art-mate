import { api } from '../../lib/api'

export const getMe = () => api('/users/me')

/** 멱등: 이미 있으면 200 + 기존 프로필. 학생 전용 서비스라 항상 STUDENT로 만듦 */
export const createMe = ({ displayName }) =>
  api('/users/me', { method: 'POST', body: { display_name: displayName, user_type: 'STUDENT' } })
