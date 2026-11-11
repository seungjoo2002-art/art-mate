import { Archive, House, MessageCircle, PencilLine, User } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import styles from './BottomNav.module.css'

const TABS = [
  { to: '/home', label: '홈', icon: House },
  { to: '/practice', label: '실기', icon: PencilLine },
  { to: '/archive', label: '아카이브', icon: Archive },
  { to: '/community', label: '커뮤니티', icon: MessageCircle },
  { to: '/my', label: '마이', icon: User },
]

export default function BottomNav() {
  return (
    <nav className={styles.nav} aria-label="주요 메뉴">
      {TABS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) => `${styles.tab} ${isActive ? styles.active : ''}`}
        >
          <Icon size={26} strokeWidth={2} aria-hidden />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
