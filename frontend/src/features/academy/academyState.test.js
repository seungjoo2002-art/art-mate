import { describe, expect, it } from 'vitest'
import { landingPathFor, homePathFor, areaOf } from '../../app/roles'
import { dashboardStats, groupByStudent, instructorGate, resolveAcademy, unassignedMembers } from './academyState'

describe('역할별 첫 화면 (v1.0)', () => {
  it('유형별 홈', () => {
    expect(homePathFor({ user_type: 'STUDENT' })).toBe('/home')
    expect(homePathFor({ user_type: 'INSTRUCTOR' })).toBe('/instructor')
    expect(homePathFor({ user_type: 'ADMIN' })).toBe('/admin/academies')
    expect(homePathFor(null)).toBe('/home')
  })
  it('기억해 둔 경로는 내 영역일 때만 쓴다', () => {
    expect(areaOf('/instructor/academies/a')).toBe('INSTRUCTOR')
    expect(areaOf('/instructors')).toBe('STUDENT')
    expect(landingPathFor({ user_type: 'INSTRUCTOR' }, '/instructor/academies/a')).toBe('/instructor/academies/a')
    expect(landingPathFor({ user_type: 'INSTRUCTOR' }, '/artworks/1')).toBe('/instructor')
    expect(landingPathFor({ user_type: 'STUDENT' }, '/admin/academies')).toBe('/home')
    expect(landingPathFor({ user_type: 'STUDENT' }, '/artworks/1')).toBe('/artworks/1')
  })
})

describe('instructorGate (승인 전 강사 기능 제한)', () => {
  const a = (id, status, my_role) => ({ id, status, my_role })
  it('운영 중 학원에 강사 이상이면 ready', () => {
    const gate = instructorGate([a('1', 'ACTIVE', 'INSTRUCTOR'), a('2', 'PENDING_APPROVAL', 'OWNER')])
    expect(gate.state).toBe('ready')
    expect(gate.active.map((x) => x.id)).toEqual(['1'])
    expect(gate.pendingAcademies.map((x) => x.id)).toEqual(['2'])
  })
  it('등록 승인 대기나 소속 신청 대기만 있으면 waiting', () => {
    expect(instructorGate([a('2', 'PENDING_APPROVAL', 'OWNER')]).state).toBe('waiting')
    expect(instructorGate([], [{ id: 'r', status: 'PENDING' }]).state).toBe('waiting')
  })
  it('학생으로만 소속되었거나 반려만 있으면 none', () => {
    expect(instructorGate([a('3', 'ACTIVE', 'STUDENT')]).state).toBe('none')
    const gate = instructorGate([a('4', 'REJECTED', 'OWNER')], [{ id: 'r', status: 'REJECTED' }])
    expect(gate.state).toBe('none')
    expect(gate.rejectedAcademies).toHaveLength(1)
    expect(gate.rejectedRequests).toHaveLength(1)
  })
  it('URL 학원은 운영 중 소속 학원일 때만', () => {
    const active = [a('1', 'ACTIVE', 'OWNER')]
    expect(resolveAcademy(active, '1')?.id).toBe('1')
    expect(resolveAcademy(active, 'other')).toBeNull()
  })
})

describe('대시보드 계산', () => {
  it('숫자 카드', () => {
    const stats = dashboardStats({
      classes: [{ student_count: 3 }, { student_count: 2 }],
      artworks: { total: 7 },
      queue: { total: 2 },
      approved: { total: 5 },
    })
    expect(stats).toEqual({ classes: 2, students: 5, artworks: 7, waiting: 2, approved: 5 })
    expect(dashboardStats({})).toEqual({ classes: 0, students: 0, artworks: 0, waiting: 0, approved: 0 })
  })
  it('학생별 작품 묶음', () => {
    const s1 = { membership_id: 'm1', display_name: '가' }
    const s2 = { membership_id: 'm2', display_name: '나' }
    const groups = groupByStudent([
      { id: 'a', student: s1 },
      { id: 'b', student: s2 },
      { id: 'c', student: s1 },
    ])
    expect(groups.map((g) => [g.student.membership_id, g.artworks.map((x) => x.id)])).toEqual([
      ['m1', ['a', 'c']],
      ['m2', ['b']],
    ])
  })
  it('반에 아직 배정되지 않은 학생·강사', () => {
    const members = [
      { id: 's1', role: 'STUDENT' },
      { id: 's2', role: 'STUDENT' },
      { id: 't1', role: 'INSTRUCTOR' },
      { id: 'o1', role: 'OWNER' },
    ]
    const classMembers = [
      { membership_id: 's1', status: 'ACTIVE' },
      { membership_id: 's2', status: 'REMOVED' },
      { membership_id: 'o1', status: 'ACTIVE' },
    ]
    expect(unassignedMembers(members, classMembers, 'STUDENT').map((m) => m.id)).toEqual(['s2'])
    expect(unassignedMembers(members, classMembers, 'INSTRUCTOR').map((m) => m.id)).toEqual(['t1'])
  })
})
