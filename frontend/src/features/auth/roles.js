import { GraduationCap, Palette } from 'lucide-react'

export const ROLES = {
  STUDENT: {
    eyebrow: 'STUDENT',
    title: '학생으로 시작하기',
    description: '작품과 첨삭을 기록하고, 반복되는 약점과 성장 과정을 확인해 보세요.',
    icon: Palette,
    iconVariant: 'soft',
    signupBadge: '학생 계정 만들기',
  },
  INSTRUCTOR: {
    eyebrow: 'TEACHER',
    title: '강사로 시작하기',
    description: '학생의 작품과 피드백을 관리하고, 실기 수업을 체계적으로 운영해 보세요.',
    icon: GraduationCap,
    iconVariant: 'dark',
    signupBadge: '강사 계정 만들기',
  },
}
