import { api } from '../../lib/api'

export const getMe = () => api('/users/me')

/** 학년·실기 유형·학습 목표 등. 보낸 필드만 바뀜 (null이면 미선택으로) */
export const updateMe = (patch) => api('/users/me', { method: 'PATCH', body: patch })

/** 목표 대학 목록 (1지망부터, 배열 그대로) */
export const listTargetUniversities = () => api('/users/me/target-universities')

/** 목표 대학 순서 변경: 내 목표 대학 전체 id를 1지망부터 */
export const reorderTargetUniversities = (ids) =>
  api('/users/me/target-universities/order', { method: 'PUT', body: { ids } })

export const updateTargetUniversity = (id, patch) =>
  api(`/users/me/target-universities/${id}`, { method: 'PATCH', body: patch })

export const deleteTargetUniversity = (id) =>
  api(`/users/me/target-universities/${id}`, { method: 'DELETE' })

/** 목표 대학·학과 (v0.9 F-1). 지금은 한 줄 입력을 대학 이름 칸에 그대로 저장 */
export const addTargetUniversity = (universityName) =>
  api('/users/me/target-universities', {
    method: 'POST',
    body: { university_name: universityName },
  })

/** 멱등: 이미 있으면 200 + 기존 프로필. 학생 전용 서비스라 항상 STUDENT로 만듦 */
/** realName: 실명 (선택, VER.2 P1). 본인 프로필 응답에만 있고 다른 사람에게는 닉네임만 보임 */
export const createMe = ({ displayName, realName }) =>
  api('/users/me', {
    method: 'POST',
    body: {
      display_name: displayName,
      user_type: 'STUDENT',
      ...(realName ? { real_name: realName } : {}),
    },
  })
