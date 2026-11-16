// v1.0 역할별 화면 분기 (순수 함수, 화면과 분리해 테스트)

export const USER_TYPES = {
  STUDENT: 'STUDENT',
  INSTRUCTOR: 'INSTRUCTOR',
  ADMIN: 'ADMIN',
}

/** 가입할 때 고를 수 있는 유형 (ADMIN은 API로 부여하지 않음) */
export const SIGNUP_TYPES = [
  { key: USER_TYPES.STUDENT, label: '학생' },
  { key: USER_TYPES.INSTRUCTOR, label: '강사·원장' },
]

/** 로그인 직후·잘못된 영역에 들어왔을 때 보낼 첫 화면 */
export function homePathFor(profile) {
  switch (profile?.user_type) {
    case USER_TYPES.INSTRUCTOR:
      return '/instructor'
    case USER_TYPES.ADMIN:
      return '/admin/academies'
    default:
      return '/home'
  }
}

const AREA_PREFIXES = [
  ['/instructor', USER_TYPES.INSTRUCTOR],
  ['/admin', USER_TYPES.ADMIN],
]

/** 경로가 속한 영역의 사용자 유형 (그 외는 학생 영역) */
export function areaOf(path) {
  const found = AREA_PREFIXES.find(([prefix]) => path === prefix || path?.startsWith(`${prefix}/`))
  return found ? found[1] : USER_TYPES.STUDENT
}

/** 로그인 전 기억해 둔 경로가 이 사용자 영역이면 그 경로, 아니면 역할별 첫 화면 */
export function landingPathFor(profile, rememberedPath) {
  if (rememberedPath && areaOf(rememberedPath) === (profile?.user_type ?? USER_TYPES.STUDENT)) {
    return rememberedPath
  }
  return homePathFor(profile)
}

/** 학원 역할 */
export const ACADEMY_ROLE_LABELS = {
  OWNER: '원장',
  MANAGER: '관리자',
  INSTRUCTOR: '강사',
  STUDENT: '학생',
}

export const isAcademyAdmin = (role) => role === 'OWNER' || role === 'MANAGER'
export const isAcademyStaff = (role) => isAcademyAdmin(role) || role === 'INSTRUCTOR'

export const ACADEMY_STATUS_LABELS = {
  PENDING_APPROVAL: '승인 대기',
  ACTIVE: '운영 중',
  REJECTED: '반려됨',
  SUSPENDED: '이용 정지',
}
