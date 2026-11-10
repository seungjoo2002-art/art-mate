import { CircleUser, House, Image, Palette, Users } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import styles from './BottomNav.module.css'

const TABS = [
  { to: '/home', label: '홈', icon: House },
  { to: '/practice', label: '실기', icon: Palette },
  { to: '/archive', label: '아카이브', icon: Image },
  { to: '/community', label: '커뮤니티', icon: Users },
  { to: '/my', label: '마이', icon: CircleUser },
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
          <Icon size={26} strokeWidth={1.8} aria-hidden />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
