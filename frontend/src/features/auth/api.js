import { api } from '../../lib/api'

export const getMe = () => api('/users/me')

/** 학년·실기 유형·학습 목표 등. 보낸 필드만 바뀜 (null이면 미선택으로) */
export const updateMe = (patch) => api('/users/me', { method: 'PATCH', body: patch })

/** 목표 대학·학과 (v0.9 F-1). 지금은 한 줄 입력을 대학 이름 칸에 그대로 저장 */
export const addTargetUniversity = (universityName) =>
  api('/users/me/target-universities', {
    method: 'POST',
    body: { university_name: universityName },
  })

/** 멱등: 이미 있으면 200 + 기존 프로필. 학생 전용 서비스라 항상 STUDENT로 만듦 */
export const createMe = ({ displayName }) =>
  api('/users/me', { method: 'POST', body: { display_name: displayName, user_type: 'STUDENT' } })
