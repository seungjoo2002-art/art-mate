// v1.0 강사 화면 상태 계산 (순수 함수)
import { isAcademyStaff } from '../../app/roles'

/**
 * 강사 첫 화면 분기.
 * academies: GET /academies?mine=true 의 items ({ id, name, status, my_role })
 * joinRequests: GET /users/me/join-requests 의 items
 * 반환 state:
 *  - 'ready'    운영 중(ACTIVE) 학원에 강사 이상으로 소속 → 대시보드
 *  - 'waiting'  등록 신청한 학원이 승인 대기이거나, 소속 신청이 대기 중 (승인 전 기능 제한)
 *  - 'none'     아무 학원에도 소속·신청 없음 → 학원 등록 또는 소속 신청
 */
export function instructorGate(academies = [], joinRequests = []) {
  const staff = academies.filter((a) => isAcademyStaff(a.my_role))
  const active = staff.filter((a) => a.status === 'ACTIVE')
  const pendingAcademies = staff.filter((a) => a.status === 'PENDING_APPROVAL')
  const rejectedAcademies = staff.filter((a) => a.status === 'REJECTED' || a.status === 'SUSPENDED')
  const pendingRequests = joinRequests.filter((r) => r.status === 'PENDING')
  const rejectedRequests = joinRequests.filter((r) => r.status === 'REJECTED')
  let state = 'none'
  if (active.length) state = 'ready'
  else if (pendingAcademies.length || pendingRequests.length) state = 'waiting'
  return { state, active, pendingAcademies, rejectedAcademies, pendingRequests, rejectedRequests }
}

/** URL의 학원이 내가 강사 이상으로 소속된 운영 중 학원인지 (아니면 첫 학원) */
export function resolveAcademy(active, academyId) {
  return active.find((a) => a.id === academyId) ?? null
}

/** 대시보드 숫자 카드 */
export function dashboardStats({ classes = [], artworks, queue, approved }) {
  const studentCount = classes.reduce((sum, c) => sum + (c.student_count ?? 0), 0)
  return {
    classes: classes.length,
    students: studentCount,
    artworks: artworks?.total ?? 0,
    waiting: queue?.total ?? 0,
    approved: approved?.total ?? 0,
  }
}

/** 작품 목록에서 학생별로 묶기 (최근 작품순 유지) */
export function groupByStudent(artworks = []) {
  const groups = new Map()
  for (const artwork of artworks) {
    const key = artwork.student?.membership_id ?? 'unknown'
    if (!groups.has(key)) groups.set(key, { student: artwork.student, artworks: [] })
    groups.get(key).artworks.push(artwork)
  }
  return [...groups.values()]
}

/** 반에 아직 배정되지 않은 멤버 (학생 또는 강사) */
export function unassignedMembers(members = [], classMembers = [], role) {
  const assigned = new Set(
    classMembers.filter((m) => m.status === 'ACTIVE').map((m) => m.membership_id),
  )
  const wanted = role === 'STUDENT' ? ['STUDENT'] : ['OWNER', 'MANAGER', 'INSTRUCTOR']
  return members.filter((m) => wanted.includes(m.role) && !assigned.has(m.id))
}
