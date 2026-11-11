import { useCallback } from 'react'
import { Bell } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../../app/providers/AuthContext'
import { listNotifications } from '../../features/notifications/api'
import { useAsync } from '../../hooks/useAsync'
import styles from './AppHeader.module.css'

/** 로그인 후 화면 상단: 로고 · 알림(안 읽은 점) · 내 프로필(닉네임 첫 글자) */
export default function AppHeader() {
  const { profile } = useAuth()
  const { pathname } = useLocation()
  // 화면을 옮길 때마다 안 읽은 알림 수를 다시 확인 (서버가 목록 조회 때 안내를 다시 계산)
  const load = useCallback(() => listNotifications({ limit: 1 }), [pathname]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data } = useAsync(load)
  const unread = data?.unread_count ?? 0

  return (
    <header className={styles.header}>
      <Link to="/home" className={styles.logo}>
        <span className={styles.mark}>A</span>
        <span className={styles.wordmark}>ART MATE</span>
      </Link>
      <div className={styles.actions}>
        <Link
          to="/notifications"
          className={styles.bell}
          aria-label={unread ? `알림 (안 읽은 알림 ${unread}개)` : '알림'}
        >
          <Bell size={26} strokeWidth={1.8} />
          {unread > 0 && <span className={styles.dot} aria-hidden />}
        </Link>
        <Link to="/my" className={styles.avatar} aria-label="마이페이지">
          {profile?.display_name.slice(0, 1)}
        </Link>
      </div>
    </header>
  )
}
