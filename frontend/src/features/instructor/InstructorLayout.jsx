import { useCallback, useEffect, useMemo } from 'react'
import { LogOut } from 'lucide-react'
import { Link, NavLink, Outlet, useMatch, useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { ACADEMY_ROLE_LABELS } from '../../app/roles'
import FullScreenStatus from '../../components/layout/FullScreenStatus'
import { Button } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { toErrorMessage } from '../../utils/errorMessages'
import { listMyAcademies, listMyJoinRequests } from '../academy/api'
import { instructorGate, resolveAcademy } from '../academy/academyState'
import styles from './Instructor.module.css'

const NAV = [
  { to: '', label: '대시보드', end: true },
  { to: 'feedbacks', label: '첨삭 검토' },
  { to: 'artworks', label: '학생 작품' },
  { to: 'manage', label: '학원 관리' },
]

/** v1.0 강사 웹: 넓은 화면(데스크톱 우선) 레이아웃. 학생 앱(480px)과 별도 */
export default function InstructorLayout() {
  const { profile, signOut } = useAuth()
  // 레이아웃(부모 라우트)에서는 자식의 :academyId를 useParams로 받을 수 없어 경로로 읽는다
  const academyId = useMatch('/instructor/academies/:academyId/*')?.params.academyId
  const navigate = useNavigate()

  // 학생 앱은 #root 최대 너비 480px → 강사 화면에서만 넓게
  useEffect(() => {
    const root = document.documentElement
    root.dataset.layout = 'wide'
    return () => {
      delete root.dataset.layout
    }
  }, [])

  const load = useCallback(
    () =>
      Promise.all([listMyAcademies(), listMyJoinRequests()]).then(([academies, requests]) => ({
        academies: academies.items,
        requests: requests.items,
      })),
    [],
  )
  const { data, error, reload } = useAsync(load)
  const gate = useMemo(
    () => (data ? instructorGate(data.academies, data.requests) : null),
    [data],
  )
  const academy = gate && academyId ? resolveAcademy(gate.active, academyId) : null

  if (error) {
    return (
      <FullScreenStatus title="학원 정보를 불러오지 못했어요" description={toErrorMessage(error)}>
        <Button onClick={reload}>다시 시도</Button>
      </FullScreenStatus>
    )
  }
  if (!gate) return <FullScreenStatus />

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link to="/instructor" className={styles.brand}>
          <span className={styles.mark}>A</span>
          <span className={styles.brandText}>ART MATE</span>
          <span className={styles.brandRole}>강사</span>
        </Link>
        {gate.active.length > 0 && (
          <select
            className={styles.academySelect}
            aria-label="학원 선택"
            value={academy?.id ?? ''}
            onChange={(e) => navigate(`/instructor/academies/${e.target.value}`)}
          >
            {!academy && <option value="">학원 선택</option>}
            {gate.active.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {ACADEMY_ROLE_LABELS[a.my_role]}
              </option>
            ))}
          </select>
        )}
        <div className={styles.headerRight}>
          <span className={styles.userName}>{profile.display_name}</span>
          <button type="button" className={styles.iconButton} onClick={signOut} aria-label="로그아웃">
            <LogOut size={20} />
          </button>
        </div>
      </header>
      {academy && (
        <nav className={styles.nav} aria-label="강사 메뉴">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={`/instructor/academies/${academy.id}${item.to ? `/${item.to}` : ''}`}
              end={item.end}
              className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navActive : ''}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      )}
      <main className={styles.main}>
        <Outlet context={{ gate, academy, reloadAcademies: reload }} />
      </main>
    </div>
  )
}
