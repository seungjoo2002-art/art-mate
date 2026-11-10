import { LayoutGrid } from 'lucide-react'
import { Link } from 'react-router-dom'
import styles from './AppHeader.module.css'

export default function AppHeader() {
  return (
    <header className={styles.header}>
      <Link to="/home" className={styles.logo}>
        <span className={styles.mark}>A</span>
        <span className={styles.wordmark}>ART MATE</span>
      </Link>
      <button type="button" className={styles.menu} aria-label="전체 메뉴">
        <LayoutGrid size={26} />
      </button>
    </header>
  )
}
