import StudentHomePage from '../pages/student/HomePage'
import TeacherHomePage from '../pages/teacher/HomePage'
import { useAuth } from './providers/AuthContext'

/** /home: 사용자 유형별 메인 화면 */
export default function RoleHome() {
  const { profile } = useAuth()
  return profile.user_type === 'INSTRUCTOR' ? <TeacherHomePage /> : <StudentHomePage />
}
