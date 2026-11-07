import { api } from '../../lib/api'

export const getMe = () => api('/users/me')

/** 멱등: 이미 있으면 200 + 기존 프로필. user_type은 'STUDENT' | 'INSTRUCTOR' */
export const createMe = ({ displayName, userType }) =>
  api('/users/me', { method: 'POST', body: { display_name: displayName, user_type: userType } })
