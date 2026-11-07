import { ChevronLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import styles from './TopBar.module.css'

/**
 * 하위 화면 상단: 뒤로가기 + 제목 + 오른쪽 표시(단계 "1 / 2" 또는 상태 배지)
 * belowHeader: AppHeader 아래에 붙는 경우 (SubLayout)
 */
export default function TopBar({ title, step, right, belowHeader = false }) {
  const navigate = useNavigate()

  return (
    <header className={`${styles.bar} ${belowHeader ? styles.belowHeader : ''}`}>
      <button type="button" className={styles.back} onClick={() => navigate(-1)} aria-label="뒤로">
        <ChevronLeft size={28} />
      </button>
      <h1 className={styles.title}>{title}</h1>
      <span className={styles.step}>{right ?? step}</span>
    </header>
  )
}
